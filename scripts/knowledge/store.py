"""
store.py — Shared ChromaDB helpers for the knowledge pipeline.

Collection: "daily_reads"
Default DB path: ~/.jeetz-knowledge/chroma/
Override with KNOWLEDGE_CHROMA_DIR env var or chroma_dir kwarg.

Embeddings are computed locally with a stdlib-only hash trick and passed
directly to ChromaDB — no onnxruntime or sentence-transformers needed.
"""

import math
import os
import re

DEFAULT_CHROMA_DIR = os.path.expanduser("~/.jeetz-knowledge/chroma")

_DIM = 512


def _embed(text: str) -> list[float]:
    """Bag-of-words hash-trick embedding — pure Python stdlib."""
    words = re.findall(r"\b\w+\b", text.lower())
    vec = [0.0] * _DIM
    for word in words:
        vec[hash(word) % _DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class _HashEF:
    """Chromadb-compatible embedding function — no onnxruntime needed."""

    @staticmethod
    def name() -> str:
        return "hash_ef"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [_embed(text) for text in input]


def _get_collection(chroma_dir: str | None = None):
    try:
        import chromadb
    except ImportError:
        raise ImportError("chromadb not installed — run: pip install chromadb")

    path = chroma_dir or os.environ.get("KNOWLEDGE_CHROMA_DIR", DEFAULT_CHROMA_DIR)
    os.makedirs(path, exist_ok=True)
    client = chromadb.PersistentClient(path=path)
    return client.get_or_create_collection(
        "daily_reads",
        embedding_function=_HashEF(),
        metadata={"hnsw:space": "cosine"},
    )


def add_note(note: dict, chroma_dir: str | None = None) -> str:
    """Upsert a distilled note into ChromaDB. Returns the doc ID."""
    col = _get_collection(chroma_dir)

    doc_id = note["source_file"] + "__" + note["ingested_at"]

    doc_text = " ".join(filter(None, [
        note.get("summary", ""),
        " ".join(note.get("takeaways", [])),
        " ".join(note.get("key_data_points", [])),
        " ".join(note.get("tags", [])),
        " ".join(note.get("entities", [])),
    ]))

    metadata = {
        "date": note.get("date", ""),
        "source_file": note.get("source_file", ""),
        "source_path": note.get("source_path", ""),
        "file_type": note.get("file_type", ""),
        "summary": note.get("summary", ""),
        "takeaways": " | ".join(note.get("takeaways", [])),
        "key_data_points": " | ".join(note.get("key_data_points", [])),
        "tags": ",".join(note.get("tags", [])),
        "relevance": ",".join(note.get("relevance", [])),
        "entities": ",".join(note.get("entities", [])),
    }

    col.upsert(ids=[doc_id], documents=[doc_text], metadatas=[metadata])
    return doc_id


def query_notes(
    query: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    n_results: int = 10,
    chroma_dir: str | None = None,
) -> list[dict]:
    """
    Search notes. Returns list of dicts with metadata + score.

    - query:  semantic/keyword search (most useful)
    - date:   exact date filter "YYYY-MM-DD"
    - tag:    post-filter by tag substring
    - Combine query + date for best results.
    """
    col = _get_collection(chroma_dir)
    total = col.count()
    if total == 0:
        return []

    where = {"date": {"$eq": date}} if date else None
    fetch = min(n_results * 3, total)  # over-fetch for post-filtering

    if query:
        raw = col.query(
            query_texts=[query],
            n_results=fetch,
            where=where,
            include=["metadatas", "documents", "distances"],
        )
        ids = raw["ids"][0]
        metas = raw["metadatas"][0]
        distances = raw["distances"][0]
        results = [
            {**m, "_id": i, "_score": round(1 - d, 4)}
            for i, m, d in zip(ids, metas, distances)
        ]
    else:
        raw = col.get(where=where, limit=fetch, include=["metadatas", "documents"])
        results = [
            {**m, "_id": i, "_score": None}
            for i, m in zip(raw["ids"], raw["metadatas"])
        ]

    if tag:
        results = [r for r in results if tag.lower() in r.get("tags", "").lower()
                   or tag.lower() in r.get("relevance", "").lower()]

    return results[:n_results]
