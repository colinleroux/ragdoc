from collections import defaultdict
from statistics import mean

from flask import Blueprint, abort, current_app, render_template, request

from ..models import PromptRun
from .runtime import pipeline_config_payload
from .topics import RAG_TOPICS, get_topic

rag_bp = Blueprint("rag", __name__, url_prefix="/rag")


def _run_question(run):
    input_json = run.input_json or {}
    return input_json.get("question") or run.name or "Untitled run"


def _run_top_score(run):
    response_json = run.response_json or {}
    meta = response_json.get("meta", {}) or {}
    value = meta.get("top_semantic_score")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _run_satisfactory(run):
    for evaluation in run.evaluations:
        if evaluation.evaluator == "user" and evaluation.metric == "satisfactory":
            if evaluation.score is None:
                return None
            return bool(int(evaluation.score))
    return None


def _run_judge_label(run):
    for evaluation in run.evaluations:
        if evaluation.metric == "rag_answer_eval" and isinstance(evaluation.rubric_json, dict):
            return evaluation.rubric_json.get("label")
    return None


def _input_value(run, key, default="-"):
    input_json = run.input_json or {}
    return input_json.get(key, default)


def _ask_settings_signature(run):
    input_json = run.input_json or {}
    return " | ".join(
        [
            str(input_json.get("answer_style") or "-"),
            f"top_k {input_json.get('top_k', '-')}",
            f"sources {input_json.get('max_sources', '-')}",
            str(input_json.get("strictness") or "-"),
            f"min {input_json.get('min_semantic_score', '-')}",
            str(input_json.get("reasoning_mode") or "-"),
        ]
    )


def _group_rows(runs, group_by):
    grouped = defaultdict(list)
    for run in runs:
        if group_by == "ask_settings":
            key = _ask_settings_signature(run)
        elif group_by == "ingestion":
            key = _input_value(run, "ingestion_preset_name")
        else:
            key = run.model or "Unknown model"
        grouped[key].append(run)

    rows = []
    for label, items in grouped.items():
        scores = [_run_top_score(run) for run in items]
        scores = [score for score in scores if score is not None]
        latencies = [run.latency_ms for run in items if run.latency_ms is not None]
        ratings = [_run_satisfactory(run) for run in items]
        rated = [rating for rating in ratings if rating is not None]
        satisfied_count = sum(1 for rating in rated if rating)
        judge_labels = sorted({label for label in (_run_judge_label(run) for run in items) if label})
        models = sorted({run.model or "-" for run in items})
        rows.append(
            {
                "label": label,
                "run_count": len(items),
                "avg_score": mean(scores) if scores else None,
                "avg_latency_ms": int(mean(latencies)) if latencies else None,
                "rated_count": len(rated),
                "satisfied_count": satisfied_count,
                "satisfactory_rate": (satisfied_count / len(rated)) if rated else None,
                "latest_run_at": max((run.created_at for run in items if run.created_at), default=None),
                "judge_labels": judge_labels,
                "models": models,
            }
        )

    rows.sort(
        key=lambda item: (
            item["satisfactory_rate"] is None,
            -(item["satisfactory_rate"] or 0),
            item["avg_score"] is None,
            -(item["avg_score"] or 0),
            item["label"],
        )
    )
    return rows


@rag_bp.route("/")
def index():
    return render_template("rag/index.html", topics=RAG_TOPICS)


@rag_bp.route("/pipeline")
def pipeline():
    return render_template(
        "rag/pipeline.html",
        pipeline_config=pipeline_config_payload(current_app.config),
    )


@rag_bp.route("/pipeline-help")
def pipeline_help():
    return render_template("rag/pipeline_help.html")


@rag_bp.route("/question-compare")
def question_compare():
    question = (request.args.get("question") or "").strip()
    group_by = (request.args.get("group_by") or "model").strip().lower()
    selected_model = (request.args.get("model") or "").strip()
    if group_by not in {"model", "ask_settings", "ingestion"}:
        group_by = "model"

    runs = (
        PromptRun.query.order_by(PromptRun.created_at.desc())
        .limit(300)
        .all()
    )
    matching_runs = [run for run in runs if _run_question(run).strip() == question] if question else []
    model_options = sorted({run.model for run in matching_runs if run.model})

    filtered_runs = matching_runs
    if selected_model:
        filtered_runs = [run for run in matching_runs if (run.model or "") == selected_model]

    comparison_rows = _group_rows(filtered_runs, group_by)
    max_latency_ms = max((row["avg_latency_ms"] or 0 for row in comparison_rows), default=0)

    return render_template(
        "rag/question_compare.html",
        question=question,
        runs=filtered_runs,
        all_matching_runs=matching_runs,
        comparison_rows=comparison_rows,
        max_latency_ms=max_latency_ms,
        group_by=group_by,
        selected_model=selected_model,
        model_options=model_options,
        run_top_score=_run_top_score,
        run_satisfactory=_run_satisfactory,
        run_judge_label=_run_judge_label,
        ask_settings_signature=_ask_settings_signature,
    )


@rag_bp.route("/<slug>")
def topic(slug):
    topic_detail = get_topic(slug)
    if topic_detail is None:
        abort(404)

    return render_template("rag/topic.html", topic=topic_detail)
