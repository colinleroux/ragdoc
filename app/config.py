import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DB = BASE_DIR / "instance" / "app.db"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{INSTANCE_DB.as_posix()}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False

    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
    MODEL_NAME = os.environ.get("MODEL_NAME", "dolphin3:latest")
    EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
    JUDGE_ENABLED = os.environ.get("JUDGE_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    JUDGE_PROVIDER = os.environ.get("JUDGE_PROVIDER", "ollama")
    JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen2.5:3b")

    QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
    COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "ragdoc_docs_v1")
    DOCS_PATH = os.environ.get("DOCS_PATH", str(BASE_DIR / "docs"))
