from collections import defaultdict
from statistics import mean
from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Prompt, PromptRun
from .presets import QUERY_DEFAULTS, prompt_query_defaults, query_defaults_from_form, store_prompt_query_defaults

prompts_bp = Blueprint("prompts", __name__, url_prefix="/prompts")


def _redirect_with_notice(message, kind="success", fallback_endpoint="prompts.index", **fallback_values):
    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    query = urlencode({"message": message, "kind": kind})
    if next_url:
        separator = "&" if "?" in next_url else "?"
        return redirect(f"{next_url}{separator}{query}")
    return redirect(f"{url_for(fallback_endpoint, **fallback_values)}?{query}")


def _run_top_score(run):
    response_json = run.response_json or {}
    meta = response_json.get("meta", {}) or {}
    value = meta.get("top_semantic_score")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _run_question(run):
    input_json = run.input_json or {}
    return input_json.get("question") or run.name or "Untitled run"


def _run_satisfactory(run):
    for evaluation in run.evaluations:
        if evaluation.evaluator == "user" and evaluation.metric == "satisfactory":
            if evaluation.score is None:
                return None
            return bool(int(evaluation.score))
    return None


def _model_comparison_rows(runs):
    grouped = defaultdict(list)
    for run in runs:
        grouped[run.model or "Unknown model"].append(run)

    rows = []
    for model_name, model_runs in grouped.items():
        scores = [_run_top_score(run) for run in model_runs]
        scores = [score for score in scores if score is not None]
        latencies = [run.latency_ms for run in model_runs if run.latency_ms is not None]
        ratings = [_run_satisfactory(run) for run in model_runs]
        rated = [rating for rating in ratings if rating is not None]
        satisfied_count = sum(1 for rating in rated if rating)
        rows.append(
            {
                "model": model_name,
                "run_count": len(model_runs),
                "avg_score": mean(scores) if scores else None,
                "avg_latency_ms": int(mean(latencies)) if latencies else None,
                "rated_count": len(rated),
                "satisfied_count": satisfied_count,
                "satisfactory_rate": (satisfied_count / len(rated)) if rated else None,
                "latest_run_at": max((run.created_at for run in model_runs if run.created_at), default=None),
            }
        )

    rows.sort(
        key=lambda item: (
            item["satisfactory_rate"] is None,
            -(item["satisfactory_rate"] or 0),
            (item["avg_score"] is None),
            -(item["avg_score"] or 0),
            item["model"],
        )
    )
    return rows


@prompts_bp.route("/")
def index():
    prompts = Prompt.query.filter(Prompt.name != "Pipeline Ask").order_by(Prompt.updated_at.desc()).all()
    recent_runs = PromptRun.query.order_by(PromptRun.created_at.desc()).limit(8).all()
    return render_template(
        "prompts/index.html",
        prompts=prompts,
        recent_runs=recent_runs,
        query_defaults=QUERY_DEFAULTS,
        prompt_query_defaults=prompt_query_defaults,
    )


@prompts_bp.route("/<int:prompt_id>")
def detail(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    runs = (
        PromptRun.query.filter_by(prompt_id=prompt.id)
        .order_by(PromptRun.created_at.desc())
        .limit(50)
        .all()
    )
    comparison_rows = _model_comparison_rows(runs)
    max_latency_ms = max((row["avg_latency_ms"] or 0 for row in comparison_rows), default=0)
    return render_template(
        "prompts/detail.html",
        prompt=prompt,
        runs=runs,
        comparison_rows=comparison_rows,
        max_latency_ms=max_latency_ms,
        run_top_score=_run_top_score,
        run_question=_run_question,
        run_satisfactory=_run_satisfactory,
        query_defaults=QUERY_DEFAULTS,
        prompt_query_defaults=prompt_query_defaults,
    )


@prompts_bp.post("/create")
def create():
    name = (request.form.get("name") or "").strip()
    purpose = (request.form.get("purpose") or "").strip()
    template = (request.form.get("template") or "").strip()

    if not name:
        return _redirect_with_notice("Prompt name is required.", "error")
    if not template:
        return _redirect_with_notice("Prompt template is required.", "error")

    prompt = Prompt(name=name, purpose=purpose or None, template=template, version=1)
    store_prompt_query_defaults(prompt, query_defaults_from_form(request.form))
    db.session.add(prompt)
    db.session.commit()
    return _redirect_with_notice(f'Created prompt "{name}".')


@prompts_bp.post("/<int:prompt_id>/update")
def update(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    if prompt.name == "Pipeline Ask":
        return _redirect_with_notice(
            "The Pipeline Ask prompt is system-managed and cannot be edited here.",
            "error",
            fallback_endpoint="prompts.detail",
            prompt_id=prompt.id,
        )

    name = (request.form.get("name") or "").strip()
    purpose = (request.form.get("purpose") or "").strip()
    template = (request.form.get("template") or "").strip()

    if not name:
        return _redirect_with_notice("Prompt name is required.", "error", fallback_endpoint="prompts.detail", prompt_id=prompt.id)
    if not template:
        return _redirect_with_notice(
            "Prompt template is required.",
            "error",
            fallback_endpoint="prompts.detail",
            prompt_id=prompt.id,
        )

    prompt.name = name
    prompt.purpose = purpose or None
    prompt.template = template
    store_prompt_query_defaults(prompt, query_defaults_from_form(request.form))
    prompt.version = (prompt.version or 1) + 1
    db.session.commit()
    return _redirect_with_notice(f'Updated prompt "{name}".', fallback_endpoint="prompts.detail", prompt_id=prompt.id)


@prompts_bp.post("/<int:prompt_id>/delete")
def delete(prompt_id):
    prompt = Prompt.query.get_or_404(prompt_id)
    if prompt.name == "Pipeline Ask":
        return _redirect_with_notice(
            "The Pipeline Ask prompt is system-managed and cannot be deleted here.",
            "error",
            fallback_endpoint="prompts.detail",
            prompt_id=prompt.id,
        )

    name = prompt.name
    db.session.delete(prompt)
    db.session.commit()
    return _redirect_with_notice(f'Deleted prompt "{name}".')
