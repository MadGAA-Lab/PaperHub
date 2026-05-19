"""Shared device-detection helper for the sentence-transformers + cross-encoder
singletons.

The HF stack defaults to CPU when no ``device=`` is passed (and logs the
no-device warning on every model load). Operators running on a GPU box
get silent CPU inference unless we detect the device ourselves.

``PAPERHUB_DEVICE`` overrides the auto-detect — set to ``cpu``, ``cuda``,
``cuda:1``, ``mps``, etc. ``auto`` (default) walks the preference order:
CUDA → MPS (Apple Silicon) → CPU. Import-error on the torch probe is
treated as "torch missing" and falls through to CPU — defensive against
weird embedded environments.
"""
from __future__ import annotations

import logging
import os

__all__ = ["resolve_device"]

_LOG = logging.getLogger(__name__)


def resolve_device() -> str:
    """Return the device string to pass into SentenceTransformer / CrossEncoder.

    Reads ``PAPERHUB_DEVICE`` for explicit override (operator force-CPU or
    pin a specific CUDA index); otherwise probes ``torch.cuda`` /
    ``torch.backends.mps`` for availability.
    """
    requested = os.environ.get("PAPERHUB_DEVICE", "auto").strip().lower()
    if requested and requested != "auto":
        _LOG.info("paperhub.device PAPERHUB_DEVICE override=%s", requested)
        return requested

    try:
        import torch
    except ImportError:
        _LOG.info("paperhub.device torch not importable → cpu")
        return "cpu"

    if torch.cuda.is_available():
        device = "cuda"
        _LOG.info(
            "paperhub.device auto-detected=%s (torch=%s cuda=%s gpus=%d)",
            device, torch.__version__, torch.version.cuda, torch.cuda.device_count(),
        )
        return device

    if (
        getattr(torch.backends, "mps", None) is not None
        and torch.backends.mps.is_available()
    ):
        _LOG.info("paperhub.device auto-detected=mps (torch=%s)", torch.__version__)
        return "mps"

    # CPU fallback. Distinguish "CPU-only torch wheel" (built without CUDA)
    # from "CUDA torch wheel but drivers/GPU not detected" — both manifest
    # as cuda.is_available() == False, but the operator fix is different.
    cuda_build = getattr(torch.version, "cuda", None)
    if cuda_build is None:
        _LOG.warning(
            "paperhub.device auto-detected=cpu — torch=%s is the CPU-only "
            "wheel (no CUDA build). To enable GPU on Windows/Linux, "
            "reinstall torch with the CUDA wheel index: "
            "`uv pip install --reinstall torch --index-url "
            "https://download.pytorch.org/whl/cu121` (substitute your CUDA "
            "version) or set PAPERHUB_DEVICE=cuda explicitly if you "
            "configured the wheel yourself.",
            torch.__version__,
        )
    else:
        _LOG.warning(
            "paperhub.device auto-detected=cpu — torch=%s built with "
            "cuda=%s but no GPU is visible to PyTorch (driver / nvidia-smi "
            "issue, or running in a container without --gpus). Run "
            "`python -c \"import torch; print(torch.cuda.is_available())\"` "
            "to verify your install, or set PAPERHUB_DEVICE=cuda to force.",
            torch.__version__, cuda_build,
        )
    return "cpu"
