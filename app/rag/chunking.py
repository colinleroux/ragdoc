import hashlib
import re
from typing import List

EMBED_MODEL_LIMITS = {
    "mxbai-embed-large": {"max_words": 320, "max_chars": 1200},
    "nomic-embed-text": {"max_words": 1200, "max_chars": 4800},
}


def chunk_text(
    text: str,
    chunk_chars: int = 1200,
    overlap: int = 200,
    split_strategy: str = "fixed",
    min_chunk_chars: int = 200,
) -> List[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    if split_strategy == "paragraph":
        return _chunk_paragraphs(text, chunk_chars, overlap, min_chunk_chars)
    if split_strategy == "sentence":
        return _chunk_sentences(text, chunk_chars, overlap, min_chunk_chars)
    return _chunk_fixed(text, chunk_chars, overlap, min_chunk_chars)


def _chunk_fixed(text: str, chunk_chars: int, overlap: int, min_chunk_chars: int) -> List[str]:
    chunks: List[str] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + chunk_chars, text_length)
        chunk = text[start:end].strip()
        if chunk and (len(chunk) >= min_chunk_chars or not chunks):
            chunks.append(chunk)
        if end == text_length:
            break
        start = max(0, end - overlap)

    return chunks


def _chunk_paragraphs(text: str, chunk_chars: int, overlap: int, min_chunk_chars: int) -> List[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n+", text) if item.strip()]
    if not paragraphs:
        return _chunk_fixed(text, chunk_chars, overlap, min_chunk_chars)

    chunks: List[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > chunk_chars:
            if buffer.strip():
                chunks.append(buffer.strip())
                buffer = ""
            chunks.extend(_chunk_fixed(paragraph, chunk_chars, overlap, min_chunk_chars))
            continue

        candidate = paragraph if not buffer else f"{buffer}\n\n{paragraph}"
        if len(candidate) <= chunk_chars:
            buffer = candidate
            continue

        if buffer.strip() and (len(buffer.strip()) >= min_chunk_chars or not chunks):
            chunks.append(buffer.strip())
        buffer = _tail_overlap(buffer, overlap)
        buffer = paragraph if not buffer else f"{buffer}\n\n{paragraph}"

    if buffer.strip():
        chunks.append(buffer.strip())
    return [chunk for chunk in chunks if chunk]


def _chunk_sentences(text: str, chunk_chars: int, overlap: int, min_chunk_chars: int) -> List[str]:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
    if not sentences:
        return _chunk_fixed(text, chunk_chars, overlap, min_chunk_chars)

    chunks: List[str] = []
    buffer = ""
    for sentence in sentences:
        if len(sentence) > chunk_chars:
            if buffer.strip():
                chunks.append(buffer.strip())
                buffer = ""
            chunks.extend(_chunk_fixed(sentence, chunk_chars, overlap, min_chunk_chars))
            continue

        candidate = sentence if not buffer else f"{buffer} {sentence}"
        if len(candidate) <= chunk_chars:
            buffer = candidate
            continue

        if buffer.strip() and (len(buffer.strip()) >= min_chunk_chars or not chunks):
            chunks.append(buffer.strip())
        buffer = _tail_overlap(buffer, overlap)
        buffer = sentence if not buffer else f"{buffer} {sentence}"

    if buffer.strip():
        chunks.append(buffer.strip())
    return [chunk for chunk in chunks if chunk]


def _tail_overlap(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    return text[-overlap:].strip()


def stable_id(text: str) -> int:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def estimate_token_count(text: str) -> int:
    return len(text.split())


def constrain_chunk_for_embedding(text: str, embed_model: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    model_name = (embed_model or "").strip().lower()
    limits = EMBED_MODEL_LIMITS.get(model_name)
    if not limits:
        return [text]

    max_words = int(limits["max_words"])
    max_chars = int(limits["max_chars"])

    words = text.split()
    if len(words) <= max_words and len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    buffer_words: List[str] = []
    buffer_char_count = 0

    for word in words:
        added_chars = len(word) if not buffer_words else len(word) + 1
        would_exceed_words = len(buffer_words) + 1 > max_words
        would_exceed_chars = buffer_char_count + added_chars > max_chars

        if buffer_words and (would_exceed_words or would_exceed_chars):
            chunks.append(" ".join(buffer_words).strip())
            overlap_words = buffer_words[- min(20, len(buffer_words)) :]
            buffer_words = overlap_words.copy()
            buffer_char_count = len(" ".join(buffer_words))

        buffer_words.append(word)
        buffer_char_count = buffer_char_count + added_chars if buffer_char_count else len(word)

    if buffer_words:
        chunks.append(" ".join(buffer_words).strip())

    return [chunk for chunk in chunks if chunk]
