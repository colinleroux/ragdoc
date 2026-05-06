import json
from typing import Any, Dict, Iterator, List, Optional

import requests

from ..errors import AppError


def _http_request(method: str, url: str, timeout: int, json_body: Optional[Dict[str, Any]] = None):
    try:
        return requests.request(method=method, url=url, json=json_body, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise AppError(f"Upstream request failed for {url}: {exc}", 502) from exc


def _is_model_not_found_error(response_text: str, model_name: str) -> bool:
    text = (response_text or "").lower()
    model = (model_name or "").strip().lower()
    return bool(text and model and "not found" in text and model in text)


def ollama_pull_model(model_name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    model_name = (model_name or "").strip()
    if not model_name:
        raise AppError("Model name is required for pull.", 400)

    response = _http_request(
        "POST",
        f"{cfg['OLLAMA_BASE_URL']}/api/pull",
        timeout=1200,
        json_body={"name": model_name, "stream": False},
    )
    if response.status_code != 200:
        raise AppError(f"Ollama pull failed for {model_name}: {response.text}", 500)

    data = response.json() if response.text else {}
    return {"model": model_name, "status": data.get("status", "ok")}


def ollama_list_models(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    response = _http_request("GET", f"{cfg['OLLAMA_BASE_URL']}/api/tags", timeout=30)
    if response.status_code != 200:
        raise AppError(f"Ollama model listing failed: {response.text}", 500)

    models = response.json().get("models", [])
    rows = []
    for item in models:
        rows.append(
            {
                "name": item.get("name") or item.get("model"),
                "model": item.get("model"),
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
                "details": item.get("details") or {},
            }
        )
    return rows


def ollama_running_models(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    response = _http_request("GET", f"{cfg['OLLAMA_BASE_URL']}/api/ps", timeout=30)
    if response.status_code != 200:
        raise AppError(f"Ollama running model check failed: {response.text}", 500)

    models = response.json().get("models", [])
    rows = []
    for item in models:
        rows.append(
            {
                "name": item.get("name") or item.get("model"),
                "model": item.get("model"),
                "size": item.get("size"),
                "size_vram": item.get("size_vram"),
                "context_length": item.get("context_length"),
                "details": item.get("details") or {},
            }
        )
    return rows


def ollama_embed(text: str, cfg: Dict[str, Any]) -> List[float]:
    response = _http_request(
        "POST",
        f"{cfg['OLLAMA_BASE_URL']}/api/embeddings",
        timeout=120,
        json_body={"model": cfg["EMBED_MODEL"], "prompt": text},
    )
    if response.status_code != 200:
        if _is_model_not_found_error(response.text, cfg["EMBED_MODEL"]):
            ollama_pull_model(cfg["EMBED_MODEL"], cfg)
            response = _http_request(
                "POST",
                f"{cfg['OLLAMA_BASE_URL']}/api/embeddings",
                timeout=120,
                json_body={"model": cfg["EMBED_MODEL"], "prompt": text},
            )
        if response.status_code != 200:
            raise AppError(f"Ollama embeddings failed: {response.text}", 500)

    embedding = response.json().get("embedding")
    if not isinstance(embedding, list):
        raise AppError("Ollama embeddings response did not include an embedding vector.", 500)
    return embedding


def ollama_generate(prompt: str, cfg: Dict[str, Any]) -> str:
    response = _http_request(
        "POST",
        f"{cfg['OLLAMA_BASE_URL']}/api/generate",
        timeout=300,
        json_body={"model": cfg["MODEL_NAME"], "prompt": prompt, "stream": False},
    )
    if response.status_code != 200:
        if _is_model_not_found_error(response.text, cfg["MODEL_NAME"]):
            ollama_pull_model(cfg["MODEL_NAME"], cfg)
            response = _http_request(
                "POST",
                f"{cfg['OLLAMA_BASE_URL']}/api/generate",
                timeout=300,
                json_body={"model": cfg["MODEL_NAME"], "prompt": prompt, "stream": False},
            )
        if response.status_code != 200:
            raise AppError(f"Ollama generate failed: {response.text}", 500)
    return (response.json().get("response") or "").strip()


def ensure_required_models(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "embedding": ollama_pull_model(cfg["EMBED_MODEL"], cfg),
        "generation": ollama_pull_model(cfg["MODEL_NAME"], cfg),
    }


def iter_model_pull_progress(model_name: str, cfg: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    model_name = (model_name or "").strip()
    if not model_name:
        raise AppError("Model name is required for pull.", 400)

    url = f"{cfg['OLLAMA_BASE_URL']}/api/pull"
    try:
        response = requests.post(url, json={"name": model_name, "stream": True}, timeout=1800, stream=True)
    except requests.exceptions.RequestException as exc:
        raise AppError(f"Ollama pull failed for {model_name}: {exc}", 502) from exc

    if response.status_code != 200:
        raise AppError(f"Ollama pull failed for {model_name}: {response.text}", 500)

    last_percent = 0.0
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue

        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        completed = item.get("completed")
        total = item.get("total")
        percent = last_percent
        if isinstance(completed, (int, float)) and isinstance(total, (int, float)) and total > 0:
            percent = max(0.0, min(100.0, (float(completed) / float(total)) * 100.0))
            last_percent = percent

        yield {
            "model": model_name,
            "status": item.get("status", "pulling"),
            "completed": completed,
            "total": total,
            "percent": round(percent, 1),
        }


def iter_required_models_progress(cfg: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    models = [("embedding", cfg["EMBED_MODEL"]), ("generation", cfg["MODEL_NAME"])]
    total_models = len(models)

    for index, (kind, model_name) in enumerate(models):
        for update in iter_model_pull_progress(model_name, cfg):
            model_percent = float(update.get("percent", 0.0) or 0.0)
            yield {
                "model_type": kind,
                "model": model_name,
                "status": update.get("status", "pulling"),
                "completed": update.get("completed"),
                "total": update.get("total"),
                "model_percent": round(model_percent, 1),
                "overall_percent": round(((index + (model_percent / 100.0)) / total_models) * 100.0, 1),
            }
