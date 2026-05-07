import json
import re
from typing import Any, Dict, List

from ..errors import AppError
from ..extensions import db
from ..models import PromptRun, RunArtifact, RunEvaluation
from .embeddings import ollama_generate_with_model

JUDGE_METRIC = "rag_answer_eval"
JUDGE_PROMPT_VERSION = "v1"

JUDGE_PROMPT_TEMPLATE = """You are evaluating a RAG answer.

Judge ONLY against the retrieved chunks.
Do not use outside knowledge.

Question:
{question}

Answer:
{answer}

Retrieved chunks:
{retrieved_chunks}

Score the answer as JSON only:

{{
  "question_alignment": 0-5,
  "factual_correctness": 0-5,
  "groundedness": 0-5,
  "citation_quality": 0-5,
  "completeness": 0-5,
  "conciseness": 0-5,
  "hallucination_penalty": 0 to -5,
  "retrieval_sufficient": true/false,
  "acceptable": true/false,
  "main_failure_mode": "...",
  "explanation": "..."
}}

Rules:
- If the retrieved chunks do not explicitly support the answer, groundedness must be <= 2.
- If the answer makes a capability claim not present in the chunks, hallucination_penalty must be -3 or worse.
- If the chunks are insufficient and the answer says so clearly, groundedness may be high.
- An answer is acceptable only if:
  - groundedness >= 4
  - factual_correctness >= 4
  - question_alignment >= 4
  - hallucination_penalty == 0
"""


def _normalize_score(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AppError("Judge model did not return valid JSON.", 500)

    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError("Judge model returned malformed JSON.", 500) from exc
    if not isinstance(data, dict):
        raise AppError("Judge model returned a non-object evaluation payload.", 500)
    return data


def _retrieved_chunks_for_run(run: PromptRun) -> List[Dict[str, Any]]:
    artifact = next(
        (item for item in run.artifacts if item.artifact_type == "retrieved_chunks"),
        None,
    )
    content = []
    if artifact and artifact.content_text:
        try:
            content = json.loads(artifact.content_text)
        except json.JSONDecodeError:
            content = []

    chunks = []
    for item in content or []:
        chunks.append(
            {
                "source": item.get("source"),
                "chunk_id": item.get("id"),
                "chunk_index": item.get("chunk_index"),
                "page": item.get("page"),
                "text": item.get("content") or "",
            }
        )
    return chunks


def _judge_prompt_payload(run: PromptRun) -> str:
    question = (run.input_json or {}).get("question") or run.name or ""
    answer = run.response_text or ""
    retrieved_chunks = _retrieved_chunks_for_run(run)
    return JUDGE_PROMPT_TEMPLATE.format(
        question=question,
        answer=answer,
        retrieved_chunks=json.dumps(retrieved_chunks, indent=2),
    )


def _derive_label(rubric: Dict[str, Any]) -> str:
    acceptable = _normalize_bool(rubric.get("acceptable"))
    retrieval_sufficient = _normalize_bool(rubric.get("retrieval_sufficient"))
    groundedness = _normalize_score(rubric.get("groundedness"), 0, 5)
    question_alignment = _normalize_score(rubric.get("question_alignment"), 0, 5)
    completeness = _normalize_score(rubric.get("completeness"), 0, 5)
    citation_quality = _normalize_score(rubric.get("citation_quality"), 0, 5)
    hallucination_penalty = _normalize_score(rubric.get("hallucination_penalty"), -5, 0)

    if acceptable and retrieval_sufficient and hallucination_penalty == 0:
        return "PASS"
    if hallucination_penalty <= -3:
        return "FAIL_HALLUCINATION"
    if not retrieval_sufficient:
        return "FAIL_RETRIEVAL"
    if citation_quality <= 2:
        return "FAIL_CITATION"
    if completeness <= 2:
        return "FAIL_INCOMPLETE"
    if question_alignment <= 2 or groundedness <= 2:
        return "FAIL_EVASIVE"
    return "FAIL_INCOMPLETE"


def normalize_judge_rubric(raw: Dict[str, Any]) -> Dict[str, Any]:
    rubric = {
        "question_alignment": _normalize_score(raw.get("question_alignment"), 0, 5),
        "factual_correctness": _normalize_score(raw.get("factual_correctness"), 0, 5),
        "groundedness": _normalize_score(raw.get("groundedness"), 0, 5),
        "citation_quality": _normalize_score(raw.get("citation_quality"), 0, 5),
        "completeness": _normalize_score(raw.get("completeness"), 0, 5),
        "conciseness": _normalize_score(raw.get("conciseness"), 0, 5),
        "hallucination_penalty": _normalize_score(raw.get("hallucination_penalty"), -5, 0),
        "retrieval_sufficient": _normalize_bool(raw.get("retrieval_sufficient")),
        "acceptable": _normalize_bool(raw.get("acceptable")),
        "main_failure_mode": str(raw.get("main_failure_mode") or "").strip(),
        "explanation": str(raw.get("explanation") or "").strip(),
    }
    rubric["score_total"] = sum(
        rubric[key]
        for key in (
            "question_alignment",
            "factual_correctness",
            "groundedness",
            "citation_quality",
            "completeness",
            "conciseness",
        )
    ) + rubric["hallucination_penalty"]
    rubric["label"] = _derive_label(rubric)
    return rubric


def _judge_evaluator_name(cfg: Dict[str, Any]) -> str:
    provider = (cfg.get("JUDGE_PROVIDER") or "ollama").strip().lower()
    model = (cfg.get("JUDGE_MODEL") or "").strip()
    return f"{provider}:{model}" if model else provider


def judge_evaluation_payload(run: PromptRun) -> Dict[str, Any]:
    evaluation = (
        RunEvaluation.query.filter_by(prompt_run_id=run.id, metric=JUDGE_METRIC)
        .order_by(RunEvaluation.updated_at.desc())
        .first()
    )
    if evaluation is None:
        return {
            "label": None,
            "acceptable": None,
            "score_total": None,
            "evaluator": None,
            "metric": JUDGE_METRIC,
            "rubric": None,
            "updated_at": None,
        }

    rubric = evaluation.rubric_json or {}
    return {
        "label": rubric.get("label"),
        "acceptable": rubric.get("acceptable"),
        "score_total": rubric.get("score_total"),
        "retrieval_sufficient": rubric.get("retrieval_sufficient"),
        "main_failure_mode": rubric.get("main_failure_mode"),
        "explanation": rubric.get("explanation"),
        "evaluator": evaluation.evaluator,
        "metric": evaluation.metric,
        "notes": evaluation.notes,
        "rubric": rubric,
        "updated_at": evaluation.updated_at.isoformat() if evaluation.updated_at else None,
    }


def evaluate_run_with_judge(run: PromptRun, cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not cfg.get("JUDGE_ENABLED", True):
        raise AppError("Judge is disabled in the current pipeline setup.", 400)

    provider = (cfg.get("JUDGE_PROVIDER") or "ollama").strip().lower()
    if provider != "ollama":
        raise AppError(
            "Only Ollama judge provider is available right now. External API support can be added later.",
            400,
        )

    prompt = _judge_prompt_payload(run)
    raw_response = ollama_generate_with_model(prompt, cfg["JUDGE_MODEL"], cfg)
    raw_rubric = _extract_json_object(raw_response)
    rubric = normalize_judge_rubric(raw_rubric)

    evaluation = (
        RunEvaluation.query.filter_by(prompt_run_id=run.id, metric=JUDGE_METRIC)
        .order_by(RunEvaluation.updated_at.desc())
        .first()
    )
    if evaluation is None:
        evaluation = RunEvaluation(run=run, metric=JUDGE_METRIC)
        db.session.add(evaluation)

    evaluation.evaluator = _judge_evaluator_name(cfg)
    evaluation.score = float(rubric["score_total"])
    evaluation.notes = rubric.get("main_failure_mode") or None
    evaluation.rubric_json = {
        **rubric,
        "provider": provider,
        "judge_model": cfg["JUDGE_MODEL"],
        "prompt_version": JUDGE_PROMPT_VERSION,
        "question": (run.input_json or {}).get("question") or run.name or "",
    }
    db.session.commit()
    return judge_evaluation_payload(run)
