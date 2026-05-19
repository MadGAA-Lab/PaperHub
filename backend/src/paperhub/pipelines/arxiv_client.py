"""arXiv API client: search + e-print source download.

Adapted from paper2slides-plus/src/arxiv_utils.py — extraction + download
patterns copied + edited to fit the Plan-C Paper Pipeline contract.
"""
from __future__ import annotations

import logging
import random
import re
import tarfile
import time
from pathlib import Path

import arxiv
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_client = arxiv.Client()

# Tarballs can be 30+ MB and export.arxiv.org sometimes throttles to a few
# hundred KB/s. 120 s total read budget covers ~50 MB at 400 KB/s with margin;
# connect stays tight so a hung DNS / firewall fails fast.
_DOWNLOAD_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
# arXiv asks for a contactable User-Agent per their Terms of Use.
# https://info.arxiv.org/help/api/tou.html
_USER_AGENT = "PaperHub/0.1 (https://github.com/whats2000/PaperHub)"

# arxiv's export mirror occasionally drops large transfers mid-stream
# (httpx.RemoteProtocolError "peer closed connection without sending
# complete message body"). Retry with backoff before failing the ingest.
_DOWNLOAD_MAX_ATTEMPTS = 3
_DOWNLOAD_BACKOFF_BASE_S = 2.0
_TRANSIENT_DOWNLOAD_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)


class TarballCorrupt(RuntimeError):
    """Raised when arxiv's e-print tarball downloaded successfully (HTTP
    OK, full byte count) but is structurally unreadable as a gzip+tar
    archive. The Paper Pipeline catches this and falls back to PDF
    ingest — equation fidelity is lower but the paper is still
    ingestible end-to-end.
    """


class ArxivResult(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    pdf_url: str | None = None


_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def _id_from_entry_id(entry_id: str) -> str:
    """Strip URL prefix + version suffix: 'http://arxiv.org/abs/2403.01234v2' → '2403.01234'."""
    m = _ARXIV_ID_RE.search(entry_id)
    if not m:
        raise ValueError(f"unexpected arxiv entry_id: {entry_id!r}")
    return m.group(1)


def search_arxiv(query: str, max_results: int = 10) -> list[ArxivResult]:
    """Return metadata-only search results from arXiv. No download."""
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results: list[ArxivResult] = []
    for r in _client.results(search):
        results.append(
            ArxivResult(
                arxiv_id=_id_from_entry_id(r.entry_id),
                title=r.title.strip(),
                authors=[a.name for a in r.authors],
                year=getattr(r.published, "year", None),
                abstract=r.summary.strip(),
                pdf_url=r.pdf_url if isinstance(getattr(r, "pdf_url", None), str) else None,
            )
        )
    return results


def _download_with_resume(url: str, target_path: Path) -> None:
    """Download ``url`` to ``target_path`` with byte-range resume across
    retries. On a mid-stream disconnect, the next attempt issues
    ``Range: bytes=<existing>-`` and appends to the partial file
    instead of restarting from byte 0.

    Server behaviour matrix:
      * 206 Partial Content   — server honoured the range; append to file
      * 200 OK + Range sent   — server ignored the range; wipe and rewrite
      * 416 Range Not Satisfiable AND existing file size matches the
        Content-Range "*/N" tail — file is already complete; return
      * any other 4xx/5xx     — raise (caller decides)

    On transient connection errors (RemoteProtocolError, ReadError, …)
    the partial bytes are KEPT so the next attempt can resume.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, _DOWNLOAD_MAX_ATTEMPTS + 1):
        existing_bytes = target_path.stat().st_size if target_path.exists() else 0
        headers: dict[str, str] = {"User-Agent": _USER_AGENT}
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"

        try:
            with httpx.stream(
                "GET", url,
                timeout=_DOWNLOAD_TIMEOUT,
                follow_redirects=True,
                headers=headers,
            ) as resp:
                if resp.status_code == 416 and existing_bytes > 0:
                    # Most likely the file is already fully downloaded —
                    # the existing bytes equal Content-Length and the
                    # server has nothing more to give us. Treat as done.
                    logger.info(
                        "download_with_resume %s: 416 Range Not Satisfiable "
                        "with existing=%d bytes; treating as complete",
                        url, existing_bytes,
                    )
                    return
                if existing_bytes > 0 and resp.status_code == 200:
                    # Server ignored our Range header (some mirrors do
                    # this under load). Wipe and restart from byte 0.
                    logger.info(
                        "download_with_resume %s: server returned 200 "
                        "despite Range header; restarting from byte 0",
                        url,
                    )
                    target_path.unlink(missing_ok=True)
                    existing_bytes = 0
                resp.raise_for_status()
                mode = "ab" if existing_bytes > 0 else "wb"
                with target_path.open(mode) as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
            return  # success
        except _TRANSIENT_DOWNLOAD_EXCEPTIONS as exc:
            last_exc = exc
            new_bytes = target_path.stat().st_size if target_path.exists() else 0
            if attempt >= _DOWNLOAD_MAX_ATTEMPTS:
                logger.warning(
                    "download_with_resume %s: failed after %d attempts "
                    "(%s: %s); final partial size=%d bytes",
                    url, attempt, type(exc).__name__, exc, new_bytes,
                )
                raise
            backoff = _DOWNLOAD_BACKOFF_BASE_S * (2 ** (attempt - 1))
            backoff += random.uniform(0, 0.5)
            logger.warning(
                "download_with_resume %s: attempt %d/%d failed "
                "(%s: %s); partial=%d bytes, retrying in %.1fs with resume",
                url, attempt, _DOWNLOAD_MAX_ATTEMPTS,
                type(exc).__name__, exc, new_bytes, backoff,
            )
            time.sleep(backoff)
    # pragma: no cover — loop exits via return or raise.
    if last_exc is not None:
        raise last_exc


def download_arxiv_pdf(arxiv_id: str, *, cache_root: Path) -> Path:
    """Download the rendered PDF for ``arxiv_id`` to
    ``cache_root / arxiv_id / source.pdf`` and return the path.

    Used as the fallback when ``download_arxiv_source`` exhausts its
    retry budget on the e-print tarball — every arxiv paper publishes
    a PDF even when the LaTeX source is missing or refuses to download.
    Equation fidelity is lower than LaTeX rendering but the paper is
    still ingestible end-to-end.

    Resume-capable via the same byte-range path as
    ``download_arxiv_source``.
    """
    target_dir = cache_root / arxiv_id
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / "source.pdf"
    pdf_url = f"https://export.arxiv.org/pdf/{arxiv_id}"
    _download_with_resume(pdf_url, pdf_path)
    return pdf_path


def download_arxiv_source(arxiv_id: str, *, cache_root: Path) -> Path:
    """Download the e-print source tarball for an arxiv_id, unpack into
    cache_root / arxiv_id / source/ — preserving the tarball's directory
    structure so ``\\input{sections/foo}`` directives resolve.  Returns the
    source directory.
    """
    target_dir = cache_root / arxiv_id
    source_dir = target_dir / "source"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Build the source URL directly from the arxiv_id.  The URL is
    # deterministic: https://export.arxiv.org/src/<arxiv_id>.
    # Use export.arxiv.org per arXiv's programmatic-access policy
    # (https://info.arxiv.org/help/robots.html): the export mirror is set
    # aside for programmatic harvesting so the main site stays responsive
    # for interactive readers.
    src_url = f"https://export.arxiv.org/src/{arxiv_id}"

    # Resume-capable downloader: across attempts, partial bytes are KEPT
    # and continued via Range requests rather than re-fetched from byte
    # 0. Critical for big papers (40+ MB e-prints) where export.arxiv
    # drops connections under load.
    tar_path = target_dir / f"{arxiv_id}.tar.gz"
    _download_with_resume(src_url, tar_path)

    source_dir.mkdir(parents=True, exist_ok=True)
    # Resolve once so we can sanity-check that every extracted member stays
    # inside source_dir even after symlink/`..` resolution.
    source_dir_resolved = source_dir.resolve()
    try:
        # If the tarball turned out corrupt (e.g. all retries together
        # still left a truncated gzip stream), surface a TarballCorrupt
        # so the caller can fall back to PDF rather than aborting ingest.
        try:
            tar = tarfile.open(tar_path, "r:gz")  # noqa: SIM115
        except (tarfile.ReadError, EOFError, OSError) as exc:
            tar_path.unlink(missing_ok=True)
            raise TarballCorrupt(
                f"arxiv source tarball for {arxiv_id} is unreadable: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        with tar:
            # Preserve directory layout.  Many arxiv papers organise their
            # LaTeX with subdirectories (sections/, figures/, etc.); flattening
            # would break `\input{sections/foo}` resolution silently.  Refuse
            # any member whose path would escape source_dir.
            for member in tar.getmembers():
                if not member.isreg():
                    continue
                rel = Path(member.name)
                if rel.is_absolute() or any(part == ".." for part in rel.parts):
                    continue  # path-traversal — skip silently
                target_path = source_dir / rel
                # Re-check after resolve() in case of symlink shenanigans.
                if not str(target_path.resolve()).startswith(
                    str(source_dir_resolved),
                ):
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                fobj = tar.extractfile(member)
                if fobj is None:
                    continue
                target_path.write_bytes(fobj.read())
    finally:
        tar_path.unlink(missing_ok=True)
    return source_dir
