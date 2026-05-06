import json
import time
import uuid

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from ..extensions import db
from ..errors import AppError
from ..models import DataSource, DocumentChunk, EmbeddingRecord, Prompt, PromptRun, RunArtifact
from ..rag.service import (
    answer_question,
    check_pipeline_settings,
    clear_pipeline_settings,
    delete_ingested_source,
    ensure_required_models,
    find_in_docs,
    ingest_docs,
    iter_required_models_progress,
    list_corpus_files,
    list_ingested_docs,
    ollama_list_models,
    ollama_runtime_status,
    parse_chat_options,
    pipeline_config_payload,
    pipeline_model_options,
    resolve_pipeline_config,
    reset_ingestion,
    save_pipeline_settings,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _chunk_payload(chunk):
    metadata = chunk.metadata_json or {}
    return {
        "id": chunk.id,
        "source": chunk.data_source.location or chunk.data_source.name,
        "source_id": chunk.data_source_id,
        "chunk_index": chunk.chunk_index,
        "token_count": chunk.token_count,
        "page": metadata.get("page"),
        "doc_type": metadata.get("doc_type"),
        "content_hash": metadata.get("content_hash"),
        "embedding_count": len(chunk.embeddings),
        "content": chunk.content,
    }


def _pipeline_prompt():
    prompt = Prompt.query.filter_by(name="Pipeline Ask").first()
    if prompt is not None:
        return prompt

    prompt = Prompt(
        name="Pipeline Ask",
        purpose="Captured RAG pipeline questions and answers from the pipeline UI.",
        template="Question: {{ question }}",
        input_schema_json={
            "question": "string",
            "top_k": "integer",
            "max_sources": "integer",
            "min_semantic_score": "number",
            "strictness": "balanced|strict",
            "answer_style": "auto|concise|detailed|steps|parameters",
            "reasoning_mode": "grounded|reasoned",
        },
    )
    db.session.add(prompt)
    db.session.flush()
    return prompt


def _run_payload(run, include_artifacts=False):
    payload = {
        "id": run.id,
        "name": run.name,
        "provider": run.provider,
        "model": run.model,
        "input": run.input_json or {},
        "answer": run.response_text,
        "meta": (run.response_json or {}).get("meta", {}),
        "sources": (run.response_json or {}).get("sources", []),
        "latency_ms": run.latency_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if include_artifacts:
        payload["artifacts"] = [
            {
                "id": artifact.id,
                "label": artifact.label,
                "artifact_type": artifact.artifact_type,
                "content": json.loads(artifact.content_text) if artifact.content_text else None,
                "metadata": artifact.metadata_json or {},
            }
            for artifact in run.artifacts
        ]
    return payload


def _capture_ask_run(question, opts, result, latency_ms, cfg):
    prompt = _pipeline_prompt()
    chunk_ids = [
        source.get("document_chunk_id")
        for source in result.get("sources", [])
        if source.get("document_chunk_id")
    ]
    chunks = (
        [_chunk_payload(chunk) for chunk in DocumentChunk.query.filter(DocumentChunk.id.in_(chunk_ids)).all()]
        if chunk_ids
        else []
    )

    run = PromptRun(
        prompt=prompt,
        name=question[:160],
        provider="ollama",
        model=cfg["MODEL_NAME"],
        input_json={"question": question, **opts},
        response_text=result.get("answer"),
        response_json={
            "meta": result.get("meta", {}),
            "citations": result.get("citations", []),
            "sources": result.get("sources", []),
        },
        latency_ms=latency_ms,
    )
    db.session.add(run)
    db.session.flush()
    db.session.add(
        RunArtifact(
            run=run,
            label="Retrieved sources",
            artifact_type="retrieval_sources",
            content_text=json.dumps(result.get("sources", [])),
            metadata_json={"count": len(result.get("sources", []))},
        )
    )
    db.session.add(
        RunArtifact(
            run=run,
            label="Chunk snapshots",
            artifact_type="retrieved_chunks",
            content_text=json.dumps(chunks),
            metadata_json={"count": len(chunks)},
        )
    )
    db.session.commit()
    return run


@api_bp.route("/health")
def health():
    cfg = resolve_pipeline_config(current_app.config)
    return jsonify(
        {
            "status": "ok",
            "model": cfg["MODEL_NAME"],
            "embed_model": cfg["EMBED_MODEL"],
            "collection": cfg["COLLECTION_NAME"],
            "framework": "flask",
        }
    )


@api_bp.route("/stats")
def stats():
    return jsonify(
        {
            "sources": DataSource.query.count(),
            "chunks": DocumentChunk.query.count(),
            "embeddings": EmbeddingRecord.query.count(),
            "prompts": Prompt.query.count(),
            "runs": PromptRun.query.count(),
        }
    )


@api_bp.post("/setup-models")
def setup_models():
    cfg = resolve_pipeline_config(current_app.config)
    result = ensure_required_models(cfg)
    return jsonify(
        {
            "ok": True,
            "embed_model": cfg["EMBED_MODEL"],
            "model_name": cfg["MODEL_NAME"],
            "pulled": result,
        }
    )


@api_bp.get("/setup-models/stream")
def setup_models_stream():
    cfg = resolve_pipeline_config(current_app.config)

    @stream_with_context
    def event_stream():
        yield "event: start\ndata: {\"ok\": true}\n\n"
        try:
            for update in iter_required_models_progress(cfg):
                yield f"event: progress\ndata: {json.dumps(update)}\n\n"
            done_payload = {
                "ok": True,
                "embed_model": cfg["EMBED_MODEL"],
                "model_name": cfg["MODEL_NAME"],
            }
            yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
        except AppError as exc:
            fail_payload = {"ok": False, "detail": exc.message}
            yield f"event: failed\ndata: {json.dumps(fail_payload)}\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_bp.get("/ingested-docs")
def ingested_docs():
    return jsonify(list_ingested_docs(resolve_pipeline_config(current_app.config)))


@api_bp.delete("/ingested-docs")
def delete_ingested_doc():
    source = (request.args.get("source") or "").strip()
    return jsonify(delete_ingested_source(source, resolve_pipeline_config(current_app.config)))


@api_bp.get("/corpus-files")
def corpus_files():
    cfg = resolve_pipeline_config(current_app.config)
    return jsonify(list_corpus_files(cfg["DOCS_PATH"]))


@api_bp.get("/chunks")
def chunks():
    source = (request.args.get("source") or "").strip()
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError as exc:
        raise AppError("limit must be an integer.", 400) from exc

    if limit < 1 or limit > 250:
        raise AppError("limit must be between 1 and 250.", 400)

    query = DocumentChunk.query.join(DataSource).order_by(
        DataSource.name.asc(), DocumentChunk.chunk_index.asc()
    )
    if source:
        query = query.filter(DataSource.location == source)

    rows = []
    for chunk in query.limit(limit).all():
        rows.append(_chunk_payload(chunk))

    return jsonify({"source": source or None, "chunks": rows, "count": len(rows), "limit": limit})


@api_bp.get("/chunks/<int:chunk_id>")
def chunk_detail(chunk_id):
    chunk = DocumentChunk.query.get_or_404(chunk_id)
    return jsonify(_chunk_payload(chunk))


@api_bp.post("/ingest")
def ingest():
    return jsonify(ingest_docs(resolve_pipeline_config(current_app.config)))


@api_bp.post("/reset-ingestion")
def reset_ingestion_route():
    return jsonify(reset_ingestion(resolve_pipeline_config(current_app.config)))


@api_bp.get("/pipeline-config")
def pipeline_config():
    return jsonify(pipeline_config_payload(current_app.config))


@api_bp.put("/pipeline-config")
def pipeline_config_update():
    body = request.get_json(silent=True) or {}
    return jsonify(save_pipeline_settings(body, current_app.config))


@api_bp.delete("/pipeline-config")
def pipeline_config_reset():
    return jsonify(clear_pipeline_settings(current_app.config))


@api_bp.get("/pipeline-model-options")
def pipeline_model_options_route():
    cfg = resolve_pipeline_config(current_app.config)
    installed = []
    upstream_error = None
    try:
        installed = ollama_list_models(cfg)
    except AppError as exc:
        upstream_error = exc.message

    return jsonify(
        {
            "installed": installed,
            "recommended": pipeline_model_options(installed),
            "ollama_url": cfg["OLLAMA_BASE_URL"],
            "upstream_error": upstream_error,
        }
    )


@api_bp.post("/pipeline-config/check")
def pipeline_config_check():
    body = request.get_json(silent=True) or {}
    return jsonify(check_pipeline_settings(body, current_app.config))


@api_bp.get("/ollama-runtime")
def ollama_runtime():
    return jsonify(ollama_runtime_status(current_app.config))


@api_bp.post("/ask")
def ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        raise AppError("question is required.", 400)

    opts = parse_chat_options(
        {
            "top_k": body.get("top_k", 5),
            "debug": body.get("debug", False),
            "strictness": body.get("strictness", "balanced"),
            "min_semantic_score": body.get("min_semantic_score", 0.35),
            "max_sources": body.get("max_sources", 5),
            "answer_style": body.get("answer_style", "auto"),
            "reasoning_mode": body.get("reasoning_mode", "grounded"),
        }
    )

    cfg = resolve_pipeline_config(current_app.config)
    started_at = time.perf_counter()
    result = answer_question(
        question,
        opts["top_k"],
        opts["debug"],
        opts["strictness"],
        opts["min_semantic_score"],
        opts["max_sources"],
        opts["answer_style"],
        opts["reasoning_mode"],
        cfg,
    )
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    run = _capture_ask_run(question, opts, result, latency_ms, cfg)
    result["run"] = _run_payload(run)
    return jsonify(result)


@api_bp.get("/ask-runs")
def ask_runs():
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError as exc:
        raise AppError("limit must be an integer.", 400) from exc

    if limit < 1 or limit > 100:
        raise AppError("limit must be between 1 and 100.", 400)

    runs = (
        PromptRun.query.join(Prompt)
        .filter(Prompt.name == "Pipeline Ask")
        .order_by(PromptRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify({"runs": [_run_payload(run) for run in runs], "count": len(runs)})


@api_bp.get("/ask-runs/<int:run_id>")
def ask_run_detail(run_id):
    run = PromptRun.query.get_or_404(run_id)
    return jsonify(_run_payload(run, include_artifacts=True))


@api_bp.delete("/ask-runs/<int:run_id>")
def ask_run_delete(run_id):
    run = PromptRun.query.get_or_404(run_id)
    run_name = run.name
    try:
        db.session.delete(run)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return jsonify({"ok": True, "run_id": run_id, "name": run_name})


@api_bp.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        raise AppError("message is required.", 400)

    cfg = resolve_pipeline_config(current_app.config)
    session_id = (body.get("session_id") or "").strip() or str(uuid.uuid4())
    opts = parse_chat_options(body)
    result = answer_question(
        message,
        opts["top_k"],
        opts["debug"],
        opts["strictness"],
        opts["min_semantic_score"],
        opts["max_sources"],
        opts["answer_style"],
        opts["reasoning_mode"],
        cfg,
    )
    result["session_id"] = session_id
    return jsonify(result)


@api_bp.get("/find")
def find():
    query = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", 20)
    return jsonify(find_in_docs(query=query, limit=limit, cfg=resolve_pipeline_config(current_app.config)))
