import re
from typing import Any, Dict, List

from ..errors import AppError
from .embeddings import ollama_embed, ollama_generate
from .options import _parse_int
from .vector_store import ensure_collection_ready, qdrant_scroll, qdrant_search


def keyword_boost(payload: Dict[str, Any], question: str) -> int:
    text = (payload.get("text") or "").lower()
    terms = [term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", question)]

    score = 0
    for term in terms:
        if term in text:
            score += 50
        if len(term) >= 10 and (term[:6] in text or term[-6:] in text):
            score += 5

    if "parameter description default" in text:
        score += 40
    if "mandatory parameters" in text:
        score += 30
    if "data parameters" in text:
        score += 30
    if "delivery options" in text:
        score += 25
    if "render request" in text or "/render" in text:
        score += 25
    if any(marker in text for marker in ("status service", "response body", "convertercount", "uptimeseconds", "/status", "/ping")):
        score -= 40

    return score


def rerank_score(hit: Dict[str, Any], question: str) -> float:
    semantic = float(hit.get("score", 0.0) or 0.0)
    lexical = float(keyword_boost(hit.get("payload", {}) or {}, question))
    return (semantic * 100.0) + lexical


def answer_question(
    question: str,
    top_k: int,
    debug: bool,
    strictness: str,
    min_semantic_score: float,
    max_sources: int,
    answer_style: str,
    reasoning_mode: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    ensure_collection_ready(cfg)

    qvec = ollama_embed(question, cfg)
    raw_hits = qdrant_search(qvec, limit=max(top_k * 10, 50), cfg=cfg)
    top_semantic = max((float(hit.get("score", 0.0) or 0.0) for hit in raw_hits), default=0.0)

    if strictness == "strict" and top_semantic < min_semantic_score:
        response = {
            "answer": "Not found in provided documentation context.",
            "citations": [],
            "sources": [],
            "meta": {"strictness": strictness, "top_semantic_score": round(top_semantic, 4), "threshold": min_semantic_score},
        }
        if debug:
            response["retrieved"] = []
        return response

    raw_hits.sort(key=lambda hit: rerank_score(hit, question), reverse=True)
    hits = raw_hits[:top_k]

    context_blocks: List[str] = []
    citations: List[str] = []
    sources: List[Dict[str, Any]] = []
    debug_hits: List[Dict[str, Any]] = []
    seen = set()

    for hit in hits:
        if len(citations) >= max_sources:
            break

        payload = hit.get("payload", {}) or {}
        source = payload.get("source", "unknown")
        page = payload.get("page")
        chunk_index = payload.get("chunk_index", 0)
        text = payload.get("text") or ""
        semantic_score = float(hit.get("score", 0.0) or 0.0)

        if strictness == "strict" and semantic_score < min_semantic_score:
            continue

        citation = f"{source}#chunk:{chunk_index}" if page is None else f"{source}#page:{page}:chunk:{chunk_index}"
        if citation in seen:
            continue
        seen.add(citation)

        preview = (text[:400] + "...") if len(text) > 400 else text
        citations.append(citation)
        context_blocks.append(f"[{citation}]\n{text}")
        sources.append(
            {
                "citation": citation,
                "doc": source,
                "page": page,
                "chunk": chunk_index,
                "semantic_score": round(semantic_score, 4),
                "label": f"{source} (p.{page})" if page is not None else source,
                "preview": preview,
                "data_source_id": payload.get("data_source_id"),
                "document_chunk_id": payload.get("document_chunk_id"),
            }
        )
        debug_hits.append({"citation": citation, "preview": preview})

    if strictness == "strict" and not context_blocks:
        response = {
            "answer": "Not found in provided documentation context.",
            "citations": [],
            "sources": [],
            "meta": {"strictness": strictness, "top_semantic_score": round(top_semantic, 4), "threshold": min_semantic_score},
        }
        if debug:
            response["retrieved"] = []
        return response

    is_parameter_query = bool(re.search(r"\b(parameter|parameters|param|params|option|options|argument|arguments|names only)\b", question, flags=re.IGNORECASE))
    reasoning_applied = reasoning_mode == "reasoned" and len(context_blocks) >= 2 and top_semantic >= max(min_semantic_score, 0.35)

    system_rules = (
        "You are RagDoc, a documentation-grounded RAG assistant.\n"
        "Answer using ONLY the documentation context provided.\n"
        "Do NOT use prior knowledge.\n"
        "If the answer is not supported by the provided context, say: 'Not found in provided documentation context.'.\n"
        "Use citations exactly as shown in the context labels.\n"
        "Every claim must include at least one citation in square brackets.\n"
        "Be concise and practical.\n"
    )
    if reasoning_applied:
        system_rules += (
            "You may infer practical conclusions only when strongly supported by multiple context snippets.\n"
            "Mark inferred statements with the prefix 'Inference:'.\n"
            "Each inferred statement must cite at least two sources.\n"
        )

    if answer_style == "parameters" or (answer_style == "auto" and is_parameter_query):
        format_rules = (
            "Write the answer as:\n"
            "Parameters (extractive):\n"
            "- If the user asked for 'names only', output ONLY: <parameter> [citation]\n"
            "- Otherwise output: <parameter> - <meaning> [citation]\n"
        )
    elif answer_style == "steps":
        format_rules = "Write one direct answer sentence, then a numbered step-by-step list. End every step with citations."
    elif answer_style == "detailed":
        format_rules = "Write one direct answer sentence, then up to 8 concise bullets. End every bullet with citations."
    else:
        format_rules = "Write one direct answer sentence, then up to 5 concise bullets. End every bullet with citations."

    prompt = (
        f"{system_rules}\n\nQUESTION:\n{question}\n\nDOCUMENTATION CONTEXT:\n\n"
        + "\n\n---\n\n".join(context_blocks)
        + f"\n\n{format_rules}\n\nANSWER:\n"
    )

    answer = ollama_generate(prompt, cfg)
    response = {
        "answer": answer,
        "citations": citations,
        "sources": sources,
        "meta": {
            "strictness": strictness,
            "top_semantic_score": round(top_semantic, 4),
            "threshold": min_semantic_score,
            "answer_style": answer_style,
            "max_sources": max_sources,
            "reasoning_mode_requested": reasoning_mode,
            "reasoning_applied": reasoning_applied,
        },
    }
    if debug:
        response["retrieved"] = debug_hits
    return response


def find_in_docs(query: str, limit: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    ensure_collection_ready(cfg)
    if not query:
        raise AppError("q is required.", 400)

    safe_limit = _parse_int(limit, "limit", 1, 200)
    query_lower = query.lower()
    matches: List[Dict[str, Any]] = []

    for point in qdrant_scroll(cfg=cfg, limit=256, with_payload=True):
        payload = point.get("payload", {}) or {}
        text = payload.get("text") or ""
        if query_lower not in text.lower():
            continue

        source = payload.get("source", "unknown")
        page = payload.get("page")
        chunk_index = payload.get("chunk_index", 0)
        citation = f"{source}#chunk:{chunk_index}" if page is None else f"{source}#page:{page}:chunk:{chunk_index}"
        matches.append(
            {
                "citation": citation,
                "preview": text[:300],
                "data_source_id": payload.get("data_source_id"),
                "document_chunk_id": payload.get("document_chunk_id"),
            }
        )
        if len(matches) >= safe_limit:
            break

    return {"query": query, "matches": matches}
