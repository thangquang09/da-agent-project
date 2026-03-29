from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import PROJECT_ROOT
from app.logger import logger


TOKEN_PATTERN = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


@dataclass(frozen=True)
class ChunkRecord:
    source: str
    chunk_id: int
    text: str
    vector: Counter[str]


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def _embed_text(text: str) -> Counter[str]:
    return Counter(_tokenize(text))


def _chunk_text(text: str, chunk_size: int = 140, overlap: int = 30) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + chunk_size)
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(0, end - overlap)
    return chunks


def _load_markdown_docs(docs_dir: Path) -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    for path in sorted(docs_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        docs.append((path.name, content))
    return docs


@lru_cache(maxsize=1)
def build_local_index(docs_dir: str | None = None) -> tuple[ChunkRecord, ...]:
    base_dir = Path(docs_dir) if docs_dir else (PROJECT_ROOT / "docs")
    if not base_dir.exists():
        logger.warning("RAG docs directory does not exist: {path}", path=base_dir)
        return tuple()

    records: list[ChunkRecord] = []
    for source_name, content in _load_markdown_docs(base_dir):
        for chunk_id, chunk in enumerate(_chunk_text(content), start=1):
            records.append(
                ChunkRecord(
                    source=source_name,
                    chunk_id=chunk_id,
                    text=chunk,
                    vector=_embed_text(chunk),
                )
            )

    logger.info("Built local RAG index with {count} chunks", count=len(records))
    return tuple(records)


def cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0

    common_tokens = set(left.keys()) & set(right.keys())
    dot = sum(left[token] * right[token] for token in common_tokens)
    left_norm = math.sqrt(sum(v * v for v in left.values()))
    right_norm = math.sqrt(sum(v * v for v in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def query_index(query: str, top_k: int = 4, source_filter: set[str] | None = None) -> list[dict]:
    query_vector = _embed_text(query)
    if not query_vector:
        return []

    candidates = build_local_index()
    scored: list[tuple[float, ChunkRecord]] = []
    for record in candidates:
        if source_filter and record.source not in source_filter:
            continue
        score = cosine_similarity(query_vector, record.vector)
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_records = scored[:top_k]
    return [
        {
            "source": record.source,
            "chunk_id": record.chunk_id,
            "score": round(score, 4),
            "text": record.text,
        }
        for score, record in top_records
    ]

