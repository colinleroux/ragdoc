from flask import Blueprint, abort, current_app, render_template

from .runtime import pipeline_config_payload
from .topics import RAG_TOPICS, get_topic

rag_bp = Blueprint("rag", __name__, url_prefix="/rag")


@rag_bp.route("/")
def index():
    return render_template("rag/index.html", topics=RAG_TOPICS)


@rag_bp.route("/pipeline")
def pipeline():
    return render_template(
        "rag/pipeline.html",
        pipeline_config=pipeline_config_payload(current_app.config),
    )


@rag_bp.route("/<slug>")
def topic(slug):
    topic_detail = get_topic(slug)
    if topic_detail is None:
        abort(404)

    return render_template("rag/topic.html", topic=topic_detail)
