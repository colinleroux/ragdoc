from flask import Blueprint, render_template

from ..models import DataSource, DocumentChunk, EmbeddingRecord, Prompt, PromptRun
from ..rag.topics import RAG_TOPICS

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    stats = {
        "sources": DataSource.query.count(),
        "chunks": DocumentChunk.query.count(),
        "embeddings": EmbeddingRecord.query.count(),
        "prompts": Prompt.query.count(),
        "runs": PromptRun.query.count(),
    }
    return render_template("home.html", topics=RAG_TOPICS, stats=stats)
