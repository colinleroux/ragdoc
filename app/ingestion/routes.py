from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, url_for

from ..extensions import db
from ..ingestion_presets import (
    get_active_ingestion_preset,
    ingestion_preset_payload,
    ingestion_run_payload,
    latest_ingestion_run,
    list_active_presets,
    normalize_ingestion_form,
    preset_defaults,
    set_active_ingestion_preset,
    store_preset_config,
)
from ..models import IngestionPreset, IngestionRun

ingestion_bp = Blueprint("ingestion", __name__, url_prefix="/ingestion-settings")


def _redirect_with_notice(message, kind="success", fallback_endpoint="ingestion.index", **fallback_values):
    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    query = urlencode({"message": message, "kind": kind})
    if next_url:
        separator = "&" if "?" in next_url else "?"
        return redirect(f"{next_url}{separator}{query}")
    return redirect(f"{url_for(fallback_endpoint, **fallback_values)}?{query}")


@ingestion_bp.route("/")
def index():
    presets = list_active_presets()
    recent_runs = IngestionRun.query.order_by(IngestionRun.created_at.desc()).limit(12).all()
    active_preset = get_active_ingestion_preset()
    return render_template(
        "ingestion/index.html",
        presets=presets,
        active_preset=active_preset,
        recent_runs=recent_runs,
        preset_defaults=preset_defaults,
    )


@ingestion_bp.post("/create")
def create():
    name = (request.form.get("name") or "").strip()
    purpose = (request.form.get("purpose") or "").strip()
    if not name:
        return _redirect_with_notice("Preset name is required.", "error")

    preset = IngestionPreset(name=name, purpose=purpose or None, version=1, active=True)
    store_preset_config(preset, normalize_ingestion_form(request.form))
    db.session.add(preset)
    db.session.commit()
    return _redirect_with_notice(f'Created ingestion preset "{name}".')


@ingestion_bp.post("/<int:preset_id>/update")
def update(preset_id):
    preset = IngestionPreset.query.get_or_404(preset_id)
    name = (request.form.get("name") or "").strip()
    purpose = (request.form.get("purpose") or "").strip()
    if not name:
        return _redirect_with_notice(
            "Preset name is required.",
            "error",
            fallback_endpoint="ingestion.detail",
            preset_id=preset.id,
        )

    preset.name = name
    preset.purpose = purpose or None
    store_preset_config(preset, normalize_ingestion_form(request.form))
    preset.version = (preset.version or 1) + 1
    db.session.commit()
    return _redirect_with_notice(
        f'Updated ingestion preset "{name}".',
        fallback_endpoint="ingestion.detail",
        preset_id=preset.id,
    )


@ingestion_bp.post("/<int:preset_id>/delete")
def delete(preset_id):
    preset = IngestionPreset.query.get_or_404(preset_id)
    if IngestionPreset.query.count() <= 1:
        return _redirect_with_notice("Keep at least one ingestion preset available.", "error")
    name = preset.name
    db.session.delete(preset)
    db.session.commit()
    if IngestionPreset.query.count() > 0:
        try:
            active = get_active_ingestion_preset()
        except Exception:
            set_active_ingestion_preset(IngestionPreset.query.order_by(IngestionPreset.id.asc()).first().id)
    return _redirect_with_notice(f'Deleted ingestion preset "{name}".')


@ingestion_bp.post("/<int:preset_id>/activate")
def activate(preset_id):
    preset = set_active_ingestion_preset(preset_id)
    return _redirect_with_notice(
        f'Active ingestion preset is now "{preset.name}".',
        fallback_endpoint="ingestion.detail",
        preset_id=preset.id,
    )


@ingestion_bp.route("/<int:preset_id>")
def detail(preset_id):
    preset = IngestionPreset.query.get_or_404(preset_id)
    runs = (
        IngestionRun.query.filter_by(ingestion_preset_id=preset.id)
        .order_by(IngestionRun.created_at.desc())
        .limit(30)
        .all()
    )
    active_preset = get_active_ingestion_preset()
    return render_template(
        "ingestion/detail.html",
        preset=preset,
        active_preset=active_preset,
        runs=runs,
        preset_defaults=preset_defaults,
        ingestion_run_payload=ingestion_run_payload,
        latest_collection_run=latest_ingestion_run,
    )
