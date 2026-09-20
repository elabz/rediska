"""One rule for the text that gets embedded, and the model's task prefixes.

The embeddings server (llama.cpp behind LiteLLM, `nomic-embed-text-v1.5`)
rejects inputs above roughly 512 tokens with HTTP 500, so nothing longer than
``EMBED_MAX_CHARS`` is ever sent. Longer documents are split on paragraph
boundaries into at most ``EMBED_MAX_CHUNKS`` chunks; the caller embeds each and
stores the normalised mean, so a document always has exactly one vector.

The model is trained with task prefixes: stored documents are embedded as
``search_document: <text>`` and search-box queries as ``search_query: <text>``.
Similarity by raw text compares like with like and so uses the document prefix.
The scheme is part of ``PREP_VERSION``: changing either the budget or the
prefixes changes the version, which marks every stored vector as stale and lets
the sweeper re-embed it.

Content is prepared verbatim — no filtering, no redaction.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Optional

# Bumped whenever the preparation below changes in a way that moves vectors.
PREP_VERSION = "v1-prefix"

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

DEFAULT_MAX_CHARS = 1400
MAX_CHUNKS = 4

_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def collapse(text: Optional[str]) -> str:
    """Collapse runs of spaces and blank lines, keeping paragraph breaks."""
    if not text:
        return ""
    return _BLANK_LINES.sub("\n\n", _WHITESPACE.sub(" ", text.replace("\r\n", "\n"))).strip()


def prepare_embedding_text(
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> str:
    """Title, a blank line, then the body — whitespace collapsed.

    Either part may be missing. The external-listing details block is part of
    the stored body and is deliberately kept.
    """
    parts = [collapse(title), collapse(body)]
    return "\n\n".join(p for p in parts if p).strip()


def text_hash(text: str) -> str:
    """Stable hash of prepared text + prep version (change ⇒ re-embed)."""
    return hashlib.blake2b(
        f"{PREP_VERSION}\x00{text}".encode("utf-8"), digest_size=16
    ).hexdigest()


def _split_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Split a paragraph that is itself over the budget, on whitespace."""
    words = paragraph.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars:
            if current:
                chunks.append(current)
            # A single word longer than the budget: cut it.
            current = word[:max_chars]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_chunks: int = MAX_CHUNKS,
) -> list[str]:
    """Split prepared text into at most ``max_chunks`` chunks within the budget.

    Chunks break on paragraph boundaries where possible. Text that fits is
    returned as a single chunk; empty text yields no chunks.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_paragraph(paragraph, max_chars))
        elif not current:
            current = paragraph
        elif len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
        if len(chunks) >= max_chunks:
            break
    if current and len(chunks) < max_chunks:
        chunks.append(current)
    return chunks[:max_chunks]


def as_document(text: str) -> str:
    """Prefix stored-document text for the embeddings model."""
    return f"{DOCUMENT_PREFIX}{text}"


def as_query(text: str) -> str:
    """Prefix search-box text for the embeddings model."""
    return f"{QUERY_PREFIX}{text}"


def mean_vector(vectors: Iterable[Iterable[float]]) -> Optional[list[float]]:
    """L2-normalised mean of chunk vectors (None when there are none)."""
    rows = [list(v) for v in vectors if v]
    if not rows:
        return None
    if len(rows) == 1:
        return _normalise(rows[0])
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        raise ValueError("Cannot average vectors of different dimensions")
    summed = [sum(r[i] for r in rows) / len(rows) for i in range(width)]
    return _normalise(summed)


def _normalise(vector: list[float]) -> list[float]:
    norm = sum(v * v for v in vector) ** 0.5
    if norm == 0:
        return vector
    return [v / norm for v in vector]


__all__ = [
    "PREP_VERSION",
    "DOCUMENT_PREFIX",
    "QUERY_PREFIX",
    "DEFAULT_MAX_CHARS",
    "MAX_CHUNKS",
    "collapse",
    "prepare_embedding_text",
    "text_hash",
    "chunk_text",
    "as_document",
    "as_query",
    "mean_vector",
]
