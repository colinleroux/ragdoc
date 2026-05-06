from typing import Any, Dict, Iterator, List

from ..errors import AppError
from .embeddings import _http_request, ollama_embed


def qdrant_collection_exists(cfg: Dict[str, Any]) -> bool:
    response = _http_request("GET", f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}", timeout=30)
    return response.status_code == 200


def qdrant_create_collection(vector_size: int, cfg: Dict[str, Any]) -> None:
    response = _http_request(
        "PUT",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}",
        timeout=60,
        json_body={"vectors": {"size": vector_size, "distance": "Cosine"}},
    )
    if response.status_code not in (200, 201):
        raise AppError(f"Create collection failed: {response.text}", 500)


def qdrant_delete_collection(cfg: Dict[str, Any]) -> bool:
    if not qdrant_collection_exists(cfg):
        return False

    response = _http_request(
        "DELETE",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}",
        timeout=120,
    )
    if response.status_code not in (200, 202):
        raise AppError(f"Delete collection failed: {response.text}", 500)
    return True


def qdrant_upsert(points: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    response = _http_request(
        "PUT",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points?wait=true",
        timeout=300,
        json_body={"points": points},
    )
    if response.status_code != 200:
        raise AppError(f"Upsert failed: {response.text}", 500)


def qdrant_delete_sources(sources: List[str], cfg: Dict[str, Any]) -> None:
    if not sources or not qdrant_collection_exists(cfg):
        return

    response = _http_request(
        "POST",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points/delete?wait=true",
        timeout=120,
        json_body={
            "filter": {
                "should": [
                    {"key": "source", "match": {"value": source}}
                    for source in sources
                ]
            }
        },
    )
    if response.status_code != 200:
        raise AppError(f"Delete existing source vectors failed: {response.text}", 500)


def qdrant_search(vector: List[float], limit: int, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    response = _http_request(
        "POST",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points/search",
        timeout=60,
        json_body={"vector": vector, "limit": limit, "with_payload": True},
    )
    if response.status_code != 200:
        raise AppError(f"Search failed: {response.text}", 500)
    return response.json().get("result", [])


def qdrant_scroll(cfg: Dict[str, Any], limit: int = 256, with_payload: bool = True) -> Iterator[Dict[str, Any]]:
    offset = None
    while True:
        body: Dict[str, Any] = {"limit": limit, "with_payload": with_payload}
        if offset is not None:
            body["offset"] = offset

        response = _http_request(
            "POST",
            f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points/scroll",
            timeout=60,
            json_body=body,
        )
        if response.status_code != 200:
            raise AppError(f"Failed to query Qdrant scroll endpoint: {response.text}", 502)

        data = response.json().get("result", {})
        yield from data.get("points", [])

        offset = data.get("next_page_offset")
        if offset is None:
            break


def ensure_collection_ready(cfg: Dict[str, Any]) -> None:
    if qdrant_collection_exists(cfg):
        return
    qdrant_create_collection(vector_size=len(ollama_embed("dimension check", cfg)), cfg=cfg)
