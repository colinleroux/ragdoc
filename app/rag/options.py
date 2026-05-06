from typing import Any, Dict

from ..errors import AppError


def _parse_int(raw: Any, field_name: str, min_value: int, max_value: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise AppError(f"{field_name} must be an integer.", 400)
    if value < min_value or value > max_value:
        raise AppError(f"{field_name} must be between {min_value} and {max_value}.", 400)
    return value


def _parse_float(raw: Any, field_name: str, min_value: float, max_value: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AppError(f"{field_name} must be a number.", 400)
    if value < min_value or value > max_value:
        raise AppError(f"{field_name} must be between {min_value} and {max_value}.", 400)
    return value


def parse_chat_options(body: Dict[str, Any]) -> Dict[str, Any]:
    strictness = str(body.get("strictness", "balanced"))
    if strictness not in ("balanced", "strict"):
        raise AppError("strictness must be 'balanced' or 'strict'.", 400)

    answer_style = str(body.get("answer_style", "auto"))
    if answer_style not in ("auto", "concise", "detailed", "steps", "parameters"):
        raise AppError("answer_style must be one of auto, concise, detailed, steps, parameters.", 400)

    reasoning_mode = str(body.get("reasoning_mode", "grounded"))
    if reasoning_mode not in ("grounded", "reasoned"):
        raise AppError("reasoning_mode must be 'grounded' or 'reasoned'.", 400)

    return {
        "top_k": _parse_int(body.get("top_k", 5), "top_k", 1, 20),
        "max_sources": _parse_int(body.get("max_sources", 5), "max_sources", 1, 12),
        "min_semantic_score": _parse_float(body.get("min_semantic_score", 0.35), "min_semantic_score", 0.0, 1.0),
        "strictness": strictness,
        "answer_style": answer_style,
        "reasoning_mode": reasoning_mode,
        "debug": bool(body.get("debug", True)),
    }
