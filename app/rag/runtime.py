from pathlib import Path
from typing import Any, Dict, List

from ..errors import AppError
from ..extensions import db
from ..models import ModelCatalog, PipelineSetting
from .embeddings import ollama_list_models, ollama_running_models
from .vector_store import qdrant_collection_exists, _http_request

SETTING_MAP = {
    "ollama_base_url": "OLLAMA_BASE_URL",
    "model_name": "MODEL_NAME",
    "embed_model": "EMBED_MODEL",
    "qdrant_url": "QDRANT_URL",
    "collection_name": "COLLECTION_NAME",
    "docs_path": "DOCS_PATH",
}

MODEL_PRESETS = {
    "generation": [
        {
            "name": "llama3.2:3b",
            "size_label": "2.0GB",
            "size_bytes": 2_000_000_000,
            "family": "Llama 3.2",
            "notes": "Good all-round small chat model for RAG and summarization.",
            "source_url": "https://ollama.com/library/llama3.2",
            "recommended": True,
        },
        {
            "name": "llama3.2:1b",
            "size_label": "1.3GB",
            "size_bytes": 1_300_000_000,
            "family": "Llama 3.2",
            "notes": "Very light option when you want fast local iteration.",
            "source_url": "https://ollama.com/library/llama3.2",
            "recommended": False,
        },
        {
            "name": "gemma3:1b",
            "size_label": "815MB",
            "size_bytes": 815_000_000,
            "family": "Gemma 3",
            "notes": "Tiny and handy for quick answer-style comparisons.",
            "source_url": "https://ollama.com/library/gemma3",
            "recommended": False,
        },
        {
            "name": "gemma3:4b",
            "size_label": "3.3GB",
            "size_bytes": 3_300_000_000,
            "family": "Gemma 3",
            "notes": "Strong small model if your machine can comfortably hold it.",
            "source_url": "https://ollama.com/library/gemma3",
            "recommended": True,
        },
        {
            "name": "qwen2.5:3b",
            "size_label": "1.9GB",
            "size_bytes": 1_900_000_000,
            "family": "Qwen 2.5",
            "notes": "Worth trying when you want stronger structured output behavior.",
            "source_url": "https://ollama.com/library/qwen2.5",
            "recommended": True,
        },
        {
            "name": "qwen2.5:1.5b",
            "size_label": "986MB",
            "size_bytes": 986_000_000,
            "family": "Qwen 2.5",
            "notes": "Small multilingual option with low download cost.",
            "source_url": "https://ollama.com/library/qwen2.5",
            "recommended": False,
        },
    ],
    "embedding": [
        {
            "name": "nomic-embed-text",
            "size_label": "274MB",
            "size_bytes": 274_000_000,
            "family": "Nomic",
            "notes": "Good default embedding model and already a strong fit for this app.",
            "source_url": "https://ollama.com/library/nomic-embed-text",
            "recommended": True,
        },
        {
            "name": "mxbai-embed-large",
            "size_label": "670MB",
            "size_bytes": 670_000_000,
            "family": "Mixedbread",
            "notes": "A heavier but stronger embedding option for retrieval experiments.",
            "source_url": "https://ollama.com/library/mxbai-embed-large",
            "recommended": True,
        },
    ],
}


def _seed_model_catalog_defaults() -> None:
    if ModelCatalog.query.count() > 0:
        return

    rows = []
    for kind, items in MODEL_PRESETS.items():
        for index, item in enumerate(items):
            rows.append(
                ModelCatalog(
                    name=item["name"],
                    kind=kind,
                    family=item.get("family"),
                    size_label=item.get("size_label"),
                    size_bytes=item.get("size_bytes"),
                    notes=item.get("notes"),
                    source_url=item.get("source_url"),
                    recommended=bool(item.get("recommended")),
                    active=True,
                    sort_order=index,
                )
            )

    if not rows:
        return

    try:
        db.session.add_all(rows)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _config_value(app_cfg: Dict[str, Any], setting_key: str) -> str:
    return str(app_cfg[SETTING_MAP[setting_key]])


def get_pipeline_overrides() -> Dict[str, str]:
    return {row.key: row.value for row in PipelineSetting.query.all() if row.key in SETTING_MAP}


def resolve_pipeline_config(app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(app_cfg)
    for key, value in get_pipeline_overrides().items():
        cfg[SETTING_MAP[key]] = value
    return cfg


def pipeline_config_payload(app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    effective = resolve_pipeline_config(app_cfg)
    defaults = {
        "docs_path": _config_value(app_cfg, "docs_path"),
        "collection": _config_value(app_cfg, "collection_name"),
        "model": _config_value(app_cfg, "model_name"),
        "embed_model": _config_value(app_cfg, "embed_model"),
        "ollama_url": _config_value(app_cfg, "ollama_base_url"),
        "qdrant_url": _config_value(app_cfg, "qdrant_url"),
    }
    overrides = get_pipeline_overrides()
    return {
        "docs_path": str(effective["DOCS_PATH"]),
        "collection": str(effective["COLLECTION_NAME"]),
        "model": str(effective["MODEL_NAME"]),
        "embed_model": str(effective["EMBED_MODEL"]),
        "ollama_url": str(effective["OLLAMA_BASE_URL"]),
        "qdrant_url": str(effective["QDRANT_URL"]),
        "defaults": defaults,
        "has_overrides": bool(overrides),
        "overrides": overrides,
    }


def _normalize_settings_payload(payload: Dict[str, Any], app_cfg: Dict[str, Any]) -> Dict[str, str]:
    normalized = {
        "docs_path": str(payload.get("docs_path", _config_value(app_cfg, "docs_path"))).strip(),
        "collection_name": str(
            payload.get("collection", _config_value(app_cfg, "collection_name"))
        ).strip(),
        "model_name": str(payload.get("model", _config_value(app_cfg, "model_name"))).strip(),
        "embed_model": str(
            payload.get("embed_model", _config_value(app_cfg, "embed_model"))
        ).strip(),
        "ollama_base_url": str(
            payload.get("ollama_url", _config_value(app_cfg, "ollama_base_url"))
        ).strip(),
        "qdrant_url": str(payload.get("qdrant_url", _config_value(app_cfg, "qdrant_url"))).strip(),
    }

    for key, value in normalized.items():
        if not value:
            raise AppError(f"{key.replace('_', ' ')} is required.", 400)

    for key in ("ollama_base_url", "qdrant_url"):
        value = normalized[key].lower()
        if not (value.startswith("http://") or value.startswith("https://")):
            raise AppError(f"{key.replace('_', ' ')} must start with http:// or https://.", 400)

    return normalized


def save_pipeline_settings(payload: Dict[str, Any], app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_settings_payload(payload, app_cfg)

    try:
        for key, value in normalized.items():
            row = PipelineSetting.query.filter_by(key=key).first()
            if row is None:
                db.session.add(PipelineSetting(key=key, value=value))
            else:
                row.value = value
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return pipeline_config_payload(app_cfg)


def clear_pipeline_settings(app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    try:
        for row in PipelineSetting.query.all():
            db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return pipeline_config_payload(app_cfg)


def pipeline_model_options(installed_models: List[Dict[str, Any]]) -> Dict[str, Any]:
    _seed_model_catalog_defaults()

    installed_names = set()
    for item in installed_models:
        name = item.get("name") or ""
        model = item.get("model") or ""
        for value in (name, model):
            if not value:
                continue
            installed_names.add(value)
            if value.endswith(":latest"):
                installed_names.add(value[:-7])

    def attach_installed_flag(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for item in items:
            rows.append({**item, "installed": item["name"] in installed_names})
        return rows

    generation_rows = [
        {
            "name": row.name,
            "family": row.family,
            "size_label": row.size_label,
            "size_bytes": row.size_bytes,
            "notes": row.notes,
            "source_url": row.source_url,
            "recommended": row.recommended,
        }
        for row in ModelCatalog.query.filter_by(kind="generation", active=True)
        .order_by(ModelCatalog.sort_order.asc(), ModelCatalog.name.asc())
        .all()
    ]
    embedding_rows = [
        {
            "name": row.name,
            "family": row.family,
            "size_label": row.size_label,
            "size_bytes": row.size_bytes,
            "notes": row.notes,
            "source_url": row.source_url,
            "recommended": row.recommended,
        }
        for row in ModelCatalog.query.filter_by(kind="embedding", active=True)
        .order_by(ModelCatalog.sort_order.asc(), ModelCatalog.name.asc())
        .all()
    ]

    if not generation_rows and not embedding_rows:
        generation_rows = MODEL_PRESETS["generation"]
        embedding_rows = MODEL_PRESETS["embedding"]

    return {
        "generation": attach_installed_flag(generation_rows),
        "embedding": attach_installed_flag(embedding_rows),
    }


def _normalize_model_names(installed_models: List[Dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in installed_models:
        for value in (item.get("name") or "", item.get("model") or ""):
            if not value:
                continue
            names.add(value)
            if value.endswith(":latest"):
                names.add(value[:-7])
            else:
                names.add(f"{value}:latest")
    return names


def check_pipeline_settings(payload: Dict[str, Any], app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_settings_payload(payload, app_cfg)
    effective_cfg = dict(app_cfg)
    for key, config_key in SETTING_MAP.items():
        if key in normalized:
            effective_cfg[config_key] = normalized[key]

    docs_path = Path(normalized["docs_path"])
    checks: Dict[str, Any] = {
        "docs_path": {
            "value": normalized["docs_path"],
            "exists": docs_path.exists(),
            "is_dir": docs_path.is_dir(),
        },
        "ollama": {
            "url": normalized["ollama_base_url"],
            "reachable": False,
            "models_listed": False,
            "installed_count": 0,
            "generation_model": normalized["model_name"],
            "generation_installed": False,
            "embedding_model": normalized["embed_model"],
            "embedding_installed": False,
        },
        "qdrant": {
            "url": normalized["qdrant_url"],
            "reachable": False,
            "collection": normalized["collection_name"],
            "collection_exists": False,
        },
        "summary": [],
    }

    installed_models: List[Dict[str, Any]] = []
    try:
        installed_models = ollama_list_models(effective_cfg)
        installed_names = _normalize_model_names(installed_models)
        checks["ollama"]["reachable"] = True
        checks["ollama"]["models_listed"] = True
        checks["ollama"]["installed_count"] = len(installed_models)
        checks["ollama"]["generation_installed"] = normalized["model_name"] in installed_names
        checks["ollama"]["embedding_installed"] = normalized["embed_model"] in installed_names
    except AppError as exc:
        checks["ollama"]["error"] = exc.message

    try:
        response = _http_request("GET", f"{normalized['qdrant_url']}/collections", timeout=30)
        if response.status_code == 200:
            checks["qdrant"]["reachable"] = True
            checks["qdrant"]["collection_exists"] = qdrant_collection_exists(effective_cfg)
        else:
            checks["qdrant"]["error"] = response.text
    except AppError as exc:
        checks["qdrant"]["error"] = exc.message

    checks["same_ollama_for_both_models"] = True
    checks["summary"] = [
        "Generation and embedding models both use the same Ollama base URL in this app.",
        "Changing from dolphin3:latest to llama3.2:1b usually means changing the model tag only; the Ollama URL and port stay the same unless you are pointing at a different Ollama server.",
        "Embedding models also use the same Ollama URL. You typically change only the embedding model name.",
    ]

    return checks


def ollama_runtime_status(app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = resolve_pipeline_config(app_cfg)
    status = {
        "ollama_url": cfg["OLLAMA_BASE_URL"],
        "reachable": False,
        "gpu_detected": False,
        "gpu_state": "unknown",
        "running_models": [],
        "running_count": 0,
        "total_vram_bytes": 0,
        "note": "",
    }

    try:
        running = ollama_running_models(cfg)
    except AppError as exc:
        status["note"] = exc.message
        return status

    status["reachable"] = True
    status["running_models"] = running
    status["running_count"] = len(running)
    total_vram = sum(
        int(item.get("size_vram") or 0)
        for item in running
        if isinstance(item.get("size_vram"), (int, float))
    )
    status["total_vram_bytes"] = total_vram

    if running and total_vram > 0:
        status["gpu_detected"] = True
        status["gpu_state"] = "active"
        status["note"] = "At least one running model reports VRAM usage, so Ollama appears to be using a GPU."
    elif running:
        status["gpu_state"] = "not_detected"
        status["note"] = "Models are running, but no VRAM usage is reported. Ollama appears to be running CPU-only."
    else:
        status["gpu_state"] = "idle"
        status["note"] = "No models are currently loaded. GPU usage can only be inferred once Ollama has a model in memory."

    return status
