from typing import Any, Dict

from .errors import AppError
from .extensions import db
from .models import IngestionPreset, IngestionRun, PipelineSetting

DEFAULT_INGESTION_PRESET = {
    "split_strategy": "fixed",
    "chunk_chars": 1200,
    "overlap_chars": 200,
    "min_chunk_chars": 200,
    "pdf_mode": "page",
}

INGESTION_SETTING_KEY = "ingestion_preset_id"


def preset_defaults(preset: IngestionPreset | None) -> Dict[str, Any]:
    payload = dict(DEFAULT_INGESTION_PRESET)
    if preset is None:
        return payload
    config_json = preset.config_json or {}
    if isinstance(config_json, dict):
        payload.update(_normalize_ingestion_config(config_json))
    return payload


def normalize_ingestion_form(form: Any) -> Dict[str, Any]:
    raw = {
        "split_strategy": form.get("split_strategy"),
        "chunk_chars": form.get("chunk_chars"),
        "overlap_chars": form.get("overlap_chars"),
        "min_chunk_chars": form.get("min_chunk_chars"),
        "pdf_mode": form.get("pdf_mode"),
    }
    return _normalize_ingestion_config(raw)


def store_preset_config(preset: IngestionPreset, config: Dict[str, Any]) -> None:
    preset.config_json = _normalize_ingestion_config(config)


def list_active_presets() -> list[IngestionPreset]:
    return IngestionPreset.query.filter_by(active=True).order_by(IngestionPreset.updated_at.desc()).all()


def get_active_ingestion_preset() -> IngestionPreset:
    preset_id = get_active_ingestion_preset_id()
    if preset_id is not None:
        preset = IngestionPreset.query.get(preset_id)
        if preset is not None and preset.active:
            return preset

    preset = IngestionPreset.query.filter_by(active=True).order_by(IngestionPreset.id.asc()).first()
    if preset is None:
        raise AppError("No active ingestion presets are configured.", 500)
    return preset


def get_active_ingestion_preset_id() -> int | None:
    row = PipelineSetting.query.filter_by(key=INGESTION_SETTING_KEY).first()
    if row is None:
        return None
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return None


def set_active_ingestion_preset(preset_id: int) -> IngestionPreset:
    preset = IngestionPreset.query.get(preset_id)
    if preset is None or not preset.active:
        raise AppError("Ingestion preset not found.", 404)

    row = PipelineSetting.query.filter_by(key=INGESTION_SETTING_KEY).first()
    if row is None:
        db.session.add(PipelineSetting(key=INGESTION_SETTING_KEY, value=str(preset.id)))
    else:
        row.value = str(preset.id)
    db.session.commit()
    return preset


def latest_ingestion_run(collection: str | None = None) -> IngestionRun | None:
    query = IngestionRun.query.order_by(IngestionRun.created_at.desc())
    if collection:
        query = query.filter_by(collection=collection)
    return query.first()


def ingestion_preset_payload(preset: IngestionPreset) -> Dict[str, Any]:
    defaults = preset_defaults(preset)
    return {
        "id": preset.id,
        "name": preset.name,
        "purpose": preset.purpose,
        "config": defaults,
        "version": preset.version,
        "active": preset.active,
        "updated_at": preset.updated_at.isoformat() if preset.updated_at else None,
        "run_count": len(preset.runs),
    }


def ingestion_run_payload(run: IngestionRun | None) -> Dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "name": run.name,
        "preset_id": run.ingestion_preset_id,
        "preset_name": run.preset.name if run.preset else None,
        "collection": run.collection,
        "docs_path": run.docs_path,
        "config": run.config_json or {},
        "files_count": run.files_count,
        "doc_units_count": run.doc_units_count,
        "chunk_count": run.chunk_count,
        "embedding_count": run.embedding_count,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _normalize_ingestion_config(values: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(DEFAULT_INGESTION_PRESET)
    if not isinstance(values, dict):
        return normalized

    split_strategy = str(values.get("split_strategy") or normalized["split_strategy"]).strip().lower()
    if split_strategy in {"fixed", "paragraph", "sentence"}:
        normalized["split_strategy"] = split_strategy

    pdf_mode = str(values.get("pdf_mode") or normalized["pdf_mode"]).strip().lower()
    if pdf_mode in {"page", "document"}:
        normalized["pdf_mode"] = pdf_mode

    normalized["chunk_chars"] = _int_in_range(values.get("chunk_chars"), 200, 4000, normalized["chunk_chars"])
    normalized["overlap_chars"] = _int_in_range(values.get("overlap_chars"), 0, 1000, normalized["overlap_chars"])
    normalized["min_chunk_chars"] = _int_in_range(values.get("min_chunk_chars"), 50, 2000, normalized["min_chunk_chars"])

    if normalized["overlap_chars"] >= normalized["chunk_chars"]:
        normalized["overlap_chars"] = min(normalized["chunk_chars"] // 2, 400)
    if normalized["min_chunk_chars"] > normalized["chunk_chars"]:
        normalized["min_chunk_chars"] = normalized["chunk_chars"]

    return normalized


def _int_in_range(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))
