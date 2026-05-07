QUERY_DEFAULTS = {
    "answer_style": "auto",
    "top_k": 5,
    "max_sources": 5,
    "strictness": "balanced",
    "min_semantic_score": 0.35,
    "reasoning_mode": "grounded",
}


def prompt_query_defaults(prompt):
    payload = prompt.input_schema_json or {}
    defaults = payload.get("query_defaults") if isinstance(payload, dict) else {}
    merged = dict(QUERY_DEFAULTS)
    if isinstance(defaults, dict):
        merged.update(_normalize_query_defaults(defaults))
    return merged


def query_defaults_from_form(form):
    raw = {
        "answer_style": form.get("answer_style"),
        "top_k": form.get("top_k"),
        "max_sources": form.get("max_sources"),
        "strictness": form.get("strictness"),
        "min_semantic_score": form.get("min_semantic_score"),
        "reasoning_mode": form.get("reasoning_mode"),
    }
    return _normalize_query_defaults(raw)


def store_prompt_query_defaults(prompt, defaults):
    payload = prompt.input_schema_json if isinstance(prompt.input_schema_json, dict) else {}
    payload = dict(payload)
    payload["query_defaults"] = _normalize_query_defaults(defaults)
    prompt.input_schema_json = payload


def _normalize_query_defaults(values):
    normalized = dict(QUERY_DEFAULTS)
    if not isinstance(values, dict):
        return normalized

    answer_style = (values.get("answer_style") or QUERY_DEFAULTS["answer_style"]).strip().lower()
    if answer_style in {"auto", "concise", "detailed", "steps", "parameters"}:
        normalized["answer_style"] = answer_style

    strictness = (values.get("strictness") or QUERY_DEFAULTS["strictness"]).strip().lower()
    if strictness in {"balanced", "strict"}:
        normalized["strictness"] = strictness

    reasoning_mode = (values.get("reasoning_mode") or QUERY_DEFAULTS["reasoning_mode"]).strip().lower()
    if reasoning_mode in {"grounded", "reasoned"}:
        normalized["reasoning_mode"] = reasoning_mode

    normalized["top_k"] = _int_in_range(values.get("top_k"), 1, 20, QUERY_DEFAULTS["top_k"])
    normalized["max_sources"] = _int_in_range(values.get("max_sources"), 1, 12, QUERY_DEFAULTS["max_sources"])
    normalized["min_semantic_score"] = _float_in_range(
        values.get("min_semantic_score"), 0.0, 1.0, QUERY_DEFAULTS["min_semantic_score"]
    )
    return normalized


def _int_in_range(value, minimum, maximum, fallback):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, value))


def _float_in_range(value, minimum, maximum, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, value))
