import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    workspace_dir: Path
    db_path: Path
    papers_cache_dir: Path
    chroma_dir: Path
    router_model: str
    chitchat_model: str
    paper_qa_model: str
    embedding_model: str
    reranker_model: str
    log_level: str


def load_settings() -> Settings:
    workspace = Path(os.environ.get("PAPERHUB_WORKSPACE", "./workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return Settings(
        workspace_dir=workspace,
        db_path=workspace / "paperhub.db",
        papers_cache_dir=workspace / "papers_cache",
        chroma_dir=workspace / "chroma",
        router_model=os.environ.get("PAPERHUB_ROUTER_MODEL", "gemini/gemini-2.5-flash"),
        chitchat_model=os.environ.get("PAPERHUB_CHITCHAT_MODEL", "gemini/gemini-2.5-flash"),
        paper_qa_model=os.environ.get("PAPERHUB_PAPER_QA_MODEL", "gemini/gemini-2.5-pro"),
        embedding_model=os.environ.get("PAPERHUB_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        reranker_model=os.environ.get(
            "PAPERHUB_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        ),
        log_level=os.environ.get("PAPERHUB_LOG_LEVEL", "INFO"),
    )
