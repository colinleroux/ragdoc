import json
import time
import uuid
from datetime import datetime

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from ..extensions import db
from ..ingestion_presets import (
    get_active_ingestion_preset,
    ingestion_preset_payload,
    ingestion_run_payload,
    latest_ingestion_run,
    list_active_presets,
    set_active_ingestion_preset,
)
from ..errors import AppError
from ..models import DataSource, DocumentChunk, EmbeddingRecord, Prompt, PromptRun, RunArtifact, RunEvaluation
from ..prompts.presets import prompt_query_defaults, store_prompt_query_defaults
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
    evaluate_run_with_judge,
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


def _resolve_prompt_for_run(prompt_id):
    if prompt_id in (None, "", 0, "0"):
        return _pipeline_prompt()

    try:
        prompt_id = int(prompt_id)
    except (TypeError, ValueError) as exc:
        raise AppError("prompt_id must be an integer.", 400) from exc

    prompt = Prompt.query.get(prompt_id)
    if prompt is None:
        raise AppError("Selected prompt was not found.", 404)
    if prompt.name == "Pipeline Ask":
        return _pipeline_prompt()
    return prompt


def _run_payload(run, include_artifacts=False):
    evaluation = _run_evaluation_payload(run)
    judge = _judge_payload(run)
    payload = {
        "id": run.id,
        "name": run.name,
        "prompt_id": run.prompt_id,
        "prompt_name": run.prompt.name if run.prompt else None,
        "provider": run.provider,
        "model": run.model,
        "input": run.input_json or {},
        "answer": run.response_text,
        "meta": (run.response_json or {}).get("meta", {}),
        "sources": (run.response_json or {}).get("sources", []),
        "latency_ms": run.latency_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "evaluation": evaluation,
        "judge": judge,
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


def _run_evaluation_payload(run):
    evaluation = (
        RunEvaluation.query.filter_by(prompt_run_id=run.id, evaluator="user", metric="satisfactory")
        .order_by(RunEvaluation.updated_at.desc())
        .first()
    )
    if evaluation is None:
        return {"satisfactory": None, "notes": "", "updated_at": None}
    return {
        "satisfactory": None if evaluation.score is None else bool(int(evaluation.score)),
        "notes": evaluation.notes or "",
        "updated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else None,
    }


def _judge_payload(run):
    judge_eval = (
        RunEvaluation.query.filter_by(prompt_run_id=run.id, metric="rag_answer_eval")
        .order_by(RunEvaluation.updated_at.desc())
        .first()
    )
    if judge_eval is None:
        return {
            "label": None,
            "acceptable": None,
            "score_total": None,
            "evaluator": None,
            "rubric": None,
            "updated_at": None,
        }

    rubric = judge_eval.rubric_json or {}
    return {
        "label": rubric.get("label"),
        "acceptable": rubric.get("acceptable"),
        "score_total": rubric.get("score_total"),
        "retrieval_sufficient": rubric.get("retrieval_sufficient"),
        "main_failure_mode": rubric.get("main_failure_mode"),
        "explanation": rubric.get("explanation"),
        "evaluator": judge_eval.evaluator,
        "rubric": rubric,
        "updated_at": judge_eval.updated_at.isoformat() if judge_eval.updated_at else None,
    }


def _prompt_payload(prompt):
    return {
        "id": prompt.id,
        "name": prompt.name,
        "purpose": prompt.purpose,
        "template": prompt.template,
        "query_defaults": prompt_query_defaults(prompt),
        "version": prompt.version,
        "run_count": len(prompt.runs),
        "is_system": prompt.name == "Pipeline Ask",
        "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
    }


def _capture_ask_run(question, opts, result, latency_ms, cfg, prompt_id=None):
    prompt = _resolve_prompt_for_run(prompt_id)
    latest_run = latest_ingestion_run(cfg["COLLECTION_NAME"])
    latest_run_payload = ingestion_run_payload(latest_run)
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
        input_json={
            "question": question,
            **opts,
            "prompt_id": prompt.id,
            "prompt_name": prompt.name,
            "ingestion_preset_id": latest_run_payload["preset_id"] if latest_run_payload else None,
            "ingestion_preset_name": latest_run_payload["preset_name"] if latest_run_payload else None,
            "ingestion_run_id": latest_run_payload["id"] if latest_run_payload else None,
            "embed_model": cfg["EMBED_MODEL"],
            "judge_enabled": cfg["JUDGE_ENABLED"],
            "judge_provider": cfg["JUDGE_PROVIDER"],
            "judge_model": cfg["JUDGE_MODEL"],
            "collection": cfg["COLLECTION_NAME"],
        },
        response_text=result.get("answer"),
        response_json={
            "meta": {
                **(result.get("meta", {}) or {}),
                "provider": "ollama",
                "model": cfg["MODEL_NAME"],
                "prompt_id": prompt.id,
                "prompt_name": prompt.name,
                "ingestion_preset_id": latest_run_payload["preset_id"] if latest_run_payload else None,
                "ingestion_preset_name": latest_run_payload["preset_name"] if latest_run_payload else None,
                "ingestion_run_id": latest_run_payload["id"] if latest_run_payload else None,
                "embed_model": cfg["EMBED_MODEL"],
                "judge_enabled": cfg["JUDGE_ENABLED"],
                "judge_provider": cfg["JUDGE_PROVIDER"],
                "judge_model": cfg["JUDGE_MODEL"],
                "collection": cfg["COLLECTION_NAME"],
            },
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
    latest_run = latest_ingestion_run(cfg["COLLECTION_NAME"])
    return jsonify(
        {
            "status": "ok",
            "model": cfg["MODEL_NAME"],
            "embed_model": cfg["EMBED_MODEL"],
            "judge_enabled": cfg["JUDGE_ENABLED"],
            "collection": cfg["COLLECTION_NAME"],
            "ingestion_preset": ingestion_run_payload(latest_run),
            "framework": "flask",
        }
    )


@api_bp.route("/stats")
def stats():
    latest_run = latest_ingestion_run()
    return jsonify(
        {
            "sources": DataSource.query.count(),
            "chunks": DocumentChunk.query.count(),
            "embeddings": EmbeddingRecord.query.count(),
            "prompts": Prompt.query.count(),
            "runs": PromptRun.query.count(),
            "latest_ingestion_run": ingestion_run_payload(latest_run),
        }
    )


@api_bp.get("/prompts")
def prompts():
    include_system = (request.args.get("include_system") or "0").strip().lower() in {"1", "true", "yes"}
    query = Prompt.query.order_by(Prompt.updated_at.desc())
    if not include_system:
        query = query.filter(Prompt.name != "Pipeline Ask")
    rows = query.all()
    return jsonify({"prompts": [_prompt_payload(prompt) for prompt in rows], "count": len(rows)})


@api_bp.post("/prompts")
def prompt_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    purpose = (body.get("purpose") or "").strip()
    template = (body.get("template") or "").strip()

    if not name:
        raise AppError("Prompt name is required.", 400)
    if not template:
        raise AppError("Prompt template is required.", 400)

    prompt = Prompt(name=name, purpose=purpose or None, template=template, version=1)
    store_prompt_query_defaults(
        prompt,
        {
            "answer_style": body.get("answer_style"),
            "top_k": body.get("top_k"),
            "max_sources": body.get("max_sources"),
            "strictness": body.get("strictness"),
            "min_semantic_score": body.get("min_semantic_score"),
            "reasoning_mode": body.get("reasoning_mode"),
        },
    )
    try:
        db.session.add(prompt)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return jsonify({"ok": True, "prompt": _prompt_payload(prompt)})


@api_bp.get("/ingestion-presets")
def ingestion_presets():
    active_preset = get_active_ingestion_preset()
    presets = [ingestion_preset_payload(preset) for preset in list_active_presets()]
    latest_run = latest_ingestion_run()
    return jsonify(
        {
            "presets": presets,
            "count": len(presets),
            "active_preset_id": active_preset.id,
            "active_preset": ingestion_preset_payload(active_preset),
            "latest_run": ingestion_run_payload(latest_run),
        }
    )


@api_bp.put("/ingestion-presets/active")
def ingestion_presets_set_active():
    body = request.get_json(silent=True) or {}
    preset_id = body.get("preset_id")
    if preset_id in (None, ""):
        raise AppError("preset_id is required.", 400)
    preset = set_active_ingestion_preset(int(preset_id))
    return jsonify({"ok": True, "active_preset": ingestion_preset_payload(preset)})


@api_bp.post("/setup-models")
def setup_models():
    cfg = resolve_pipeline_config(current_app.config)
    result = ensure_required_models(cfg)
    return jsonify(
        {
            "ok": True,
            "embed_model": cfg["EMBED_MODEL"],
            "model_name": cfg["MODEL_NAME"],
            "judge_enabled": cfg["JUDGE_ENABLED"],
            "judge_provider": cfg["JUDGE_PROVIDER"],
            "judge_model": cfg["JUDGE_MODEL"],
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
                "judge_enabled": cfg["JUDGE_ENABLED"],
                "judge_provider": cfg["JUDGE_PROVIDER"],
                "judge_model": cfg["JUDGE_MODEL"],
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
    run = _capture_ask_run(question, opts, result, latency_ms, cfg, body.get("prompt_id"))
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

    runs = PromptRun.query.order_by(PromptRun.created_at.desc()).limit(limit).all()
    return jsonify({"runs": [_run_payload(run) for run in runs], "count": len(runs)})


@api_bp.get("/ask-runs/<int:run_id>")
def ask_run_detail(run_id):
    run = PromptRun.query.get_or_404(run_id)
    return jsonify(_run_payload(run, include_artifacts=True))


@api_bp.put("/ask-runs/<int:run_id>/evaluation")
def ask_run_evaluation_update(run_id):
    run = PromptRun.query.get_or_404(run_id)
    body = request.get_json(silent=True) or {}

    satisfactory = body.get("satisfactory")
    notes = (body.get("notes") or "").strip()
    if satisfactory not in (None, True, False):
        raise AppError("satisfactory must be true, false, or null.", 400)

    evaluation = (
        RunEvaluation.query.filter_by(prompt_run_id=run.id, evaluator="user", metric="satisfactory")
        .order_by(RunEvaluation.updated_at.desc())
        .first()
    )

    if satisfactory is None and not notes:
        if evaluation is not None:
            db.session.delete(evaluation)
            db.session.commit()
        return jsonify(_run_payload(run))

    if evaluation is None:
        evaluation = RunEvaluation(
            run=run,
            evaluator="user",
            metric="satisfactory",
        )
        db.session.add(evaluation)

    evaluation.score = None if satisfactory is None else float(1 if satisfactory else 0)
    evaluation.notes = notes or None
    evaluation.rubric_json = {"kind": "boolean_satisfactory"}
    db.session.commit()
    return jsonify(_run_payload(run))


@api_bp.post("/ask-runs/<int:run_id>/judge")
def ask_run_judge(run_id):
    run = PromptRun.query.get_or_404(run_id)
    result = evaluate_run_with_judge(run, resolve_pipeline_config(current_app.config))
    return jsonify({"ok": True, "run": _run_payload(run), "judge": result})


@api_bp.get("/ask-runs/<int:run_id>/download")
def ask_run_download(run_id):
    run = PromptRun.query.get_or_404(run_id)
    payload = _run_payload(run, include_artifacts=True)
    timestamp = run.created_at.strftime("%Y%m%d-%H%M%S") if run.created_at else datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"ragdoc-ask-run-{run_id}-{timestamp}.json"
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_bp.get("/ask-runs/<int:run_id>/answer.txt")
def ask_run_answer_text(run_id):
    run = PromptRun.query.get_or_404(run_id)
    timestamp = run.created_at.strftime("%Y%m%d-%H%M%S") if run.created_at else datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"ragdoc-answer-{run_id}-{timestamp}.txt"
    answer = run.response_text or ""
    input_json = run.input_json or {}
    response_json = run.response_json or {}
    meta = response_json.get("meta", {}) or {}
    judge = _judge_payload(run)
    header_lines = [
        f"Run ID: {run.id}",
        f"Created: {run.created_at.isoformat() if run.created_at else '-'}",
        f"Provider: {run.provider or meta.get('provider') or '-'}",
        f"Generation model: {run.model or meta.get('model') or '-'}",
        f"Embedding model: {input_json.get('embed_model') or meta.get('embed_model') or '-'}",
        f"Judge enabled: {'Yes' if (input_json.get('judge_enabled') if input_json.get('judge_enabled') is not None else meta.get('judge_enabled')) else 'No'}",
        f"Judge provider: {input_json.get('judge_provider') or meta.get('judge_provider') or '-'}",
        f"Judge model: {input_json.get('judge_model') or meta.get('judge_model') or '-'}",
        f"Collection: {input_json.get('collection') or meta.get('collection') or '-'}",
        f"Ingestion preset: {input_json.get('ingestion_preset_name') or meta.get('ingestion_preset_name') or '-'}",
        f"Answer style: {input_json.get('answer_style') or '-'}",
        f"Reasoning mode: {input_json.get('reasoning_mode') or '-'}",
        f"Strictness: {input_json.get('strictness') or meta.get('strictness') or '-'}",
        f"Top K: {input_json.get('top_k') if input_json.get('top_k') is not None else '-'}",
        f"Max sources: {input_json.get('max_sources') if input_json.get('max_sources') is not None else '-'}",
        f"Minimum score: {input_json.get('min_semantic_score') if input_json.get('min_semantic_score') is not None else '-'}",
        f"Latency: {f'{run.latency_ms / 1000:.1f}s' if run.latency_ms is not None else '-'}",
        f"Judge label: {judge.get('label') or '-'}",
        "",
        "Question:",
        input_json.get("question") or run.name or "-",
        "",
        "Answer:",
    ]
    payload = "\n".join(header_lines) + "\n" + answer
    return Response(
        payload,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@api_bp.delete("/ask-runs")
def ask_runs_delete_all():
    runs = PromptRun.query.order_by(PromptRun.created_at.desc()).all()
    deleted_count = len(runs)
    try:
        for run in runs:
            db.session.delete(run)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return jsonify({"ok": True, "deleted_count": deleted_count})


@api_bp.get("/ask-runs/export")
def ask_runs_export():
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError as exc:
        raise AppError("limit must be an integer.", 400) from exc

    if limit < 1 or limit > 500:
        raise AppError("limit must be between 1 and 500.", 400)

    runs = PromptRun.query.order_by(PromptRun.created_at.desc()).limit(limit).all()
    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "count": len(runs),
        "runs": [_run_payload(run, include_artifacts=True) for run in runs],
    }
    filename = f"ragdoc-ask-runs-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
