"""ChromaDB (local, persistent) + keyword scoring = hybrid retrieval, filtered by role at query time."""
import math
import re
from collections import Counter

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from . import db
from .config import ANSWER_CACHE_SIMILARITY, CANDIDATES, CHROMA_DIR, ROLES, TOP_K

_client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
_ef = embedding_functions.DefaultEmbeddingFunction()   # all-MiniLM-L6-v2, runs locally (ONNX)
chunks_col = _client.get_or_create_collection("chunks", embedding_function=_ef, metadata={"hnsw:space": "cosine"})
cache_col = _client.get_or_create_collection("answer_cache", embedding_function=_ef, metadata={"hnsw:space": "cosine"})


def add_chunks(rows: list[dict]) -> None:
    """rows: chunk_id, text, doc_id, doc_type, study_id, version, page, section."""
    for i in range(0, len(rows), 64):
        part = rows[i:i + 64]
        chunks_col.upsert(
            ids=[r["chunk_id"] for r in part],
            documents=[r["text"] for r in part],
            metadatas=[{"doc_id": r["doc_id"], "doc_type": r["doc_type"], "study_id": r["study_id"],
                        "version": r["version"], "page": r["page"], "section": r["section"][:120],
                        "is_current": 1} for r in part])


def set_current(doc_id: int, is_current: bool) -> None:
    got = chunks_col.get(where={"doc_id": doc_id}, include=["metadatas"])
    if got["ids"]:
        metas = [{**m, "is_current": 1 if is_current else 0} for m in got["metadatas"]]
        chunks_col.update(ids=got["ids"], metadatas=metas)


def _where(study_id: str, doc_types: list[str]) -> dict:
    return {"$and": [{"study_id": study_id}, {"is_current": 1}, {"doc_type": {"$in": doc_types}}]}


_tok = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_STOP = set("the a an of to in for and or on is are was be with by what which how does do at as from this that it".split())


def _terms(text: str) -> list[str]:
    return [t for t in _tok.findall(text.lower()) if t not in _STOP]


def _keyword_rank(question: str, study_id: str, doc_types: list[str]) -> list[str]:
    """BM25-style scoring over the study's current chunks (exact drug names, codes and numbers matter)."""
    marks = ",".join("?" * len(doc_types))
    rows = db.q(f"SELECT c.chunk_id, c.text FROM chunks c JOIN documents d ON d.id=c.doc_id "
                f"WHERE d.study_id=? AND d.is_current=1 AND d.doc_type IN ({marks})", (study_id, *doc_types))
    if not rows:
        return []
    qt = set(_terms(question))
    docs = [(r["chunk_id"], Counter(_terms(r["text"]))) for r in rows]
    n = len(docs)
    avg = sum(sum(c.values()) for _, c in docs) / n
    df = Counter(t for _, c in docs for t in qt if t in c)
    scored = []
    for cid, c in docs:
        dl = sum(c.values())
        s = 0.0
        for t in qt:
            if t in c:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * c[t] * 2.2 / (c[t] + 1.2 * (0.25 + 0.75 * dl / avg))
        if s > 0:
            scored.append((s, cid))
    return [cid for _, cid in sorted(scored, reverse=True)[:CANDIDATES]]


def hybrid_search(question: str, study_id: str, role: str, k: int = TOP_K) -> tuple[list[dict], int]:
    """Returns (top-k chunks, total candidate characters considered)."""
    doc_types = ROLES[role]["docs"]
    if not doc_types:
        return [], 0
    vec_ids: list[str] = []
    if chunks_col.count():
        res = chunks_col.query(query_texts=[question], n_results=CANDIDATES, where=_where(study_id, doc_types))
        vec_ids = res["ids"][0] if res["ids"] else []
    kw_ids = _keyword_rank(question, study_id, doc_types)
    fused: Counter = Counter()
    for ranked in (vec_ids, kw_ids):            # reciprocal-rank fusion
        for rank, cid in enumerate(ranked):
            fused[cid] += 1 / (60 + rank)
    ordered = [cid for cid, _ in fused.most_common()]
    if not ordered:
        return [], 0
    marks = ",".join("?" * len(ordered))
    rows = {r["chunk_id"]: r for r in db.q(
        f"SELECT c.*, d.code, d.doc_type, d.version, d.title FROM chunks c JOIN documents d ON d.id=c.doc_id "
        f"WHERE c.chunk_id IN ({marks})", ordered)}
    cand_chars = sum(len(rows[c]["text"]) for c in ordered if c in rows)
    return [rows[c] for c in ordered[:k] if c in rows], cand_chars


# ---- Semantic answer cache (keyed by role + study + document versions + prompt version) ----
def cache_lookup(question: str, key: str) -> dict | None:
    if not cache_col.count():
        return None
    res = cache_col.query(query_texts=[question], n_results=1, where={"key": key})
    if res["ids"] and res["ids"][0]:
        sim = 1 - res["distances"][0][0]
        if sim >= ANSWER_CACHE_SIMILARITY:
            return {"id": res["ids"][0][0], "similarity": round(sim, 3), **(res["metadatas"][0][0] or {})}
        return {"miss_similarity": round(sim, 3)}
    return None


def cache_store(question: str, key: str, answer_json: str, trace_id: str, tokens: int) -> None:
    cache_col.add(ids=[trace_id], documents=[question],
                  metadatas=[{"key": key, "answer": answer_json, "trace_id": trace_id, "tokens": tokens}])
