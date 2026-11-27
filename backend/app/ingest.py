"""Ingestion agent (LangGraph): parse -> detect metadata -> HIPAA gate -> section split & index
-> digest (executive + role summaries + facts, one call) -> verify claims -> consistency check.

Token optimisation: one digest call per document version produces every role's summary and the
facts used by the consistency judge; results are cached on the document row and reused by all users.
"""
import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from . import db, tracing, vectorstore
from .config import (DOC_CODES, DOC_TYPES, FACT_TOPICS, LENS_ROLES, MODEL_FAST, PROMPT_VERSION, REPO_DIR, ROLES)
from .deid import deidentify
from .llm import chat_json

STEPS = ["Parse", "Detect metadata", "De-identify (HIPAA gate)", "Section split & index",
         "Digest: executive + role summaries + facts", "Verify claims", "Cross-document consistency"]
SUPPORTED = {".pdf", ".txt", ".md", ".docx"}
MAX_DIGEST_CHARS = 100_000
_ingest_lock = threading.Lock()


# ---------------------------------------------------------------- helpers
def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pseudo_pages(text: str, size: int = 3000) -> list[str]:
    if "\f" in text:
        return [p for p in text.split("\f") if p.strip()]
    pages, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(cur) + len(para) > size and cur:
            pages.append(cur)
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        pages.append(cur)
    return pages


def parse_file(path: Path) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return [(p.extract_text() or "") for p in PdfReader(str(path)).pages]
    if ext == ".docx":
        import docx
        d = docx.Document(str(path))
        text = "\n".join(p.text for p in d.paragraphs)
        for t in d.tables:
            for row in t.rows:
                text += "\n" + " | ".join(c.text.strip() for c in row.cells)
        return _pseudo_pages(text)
    return _pseudo_pages(path.read_text(encoding="utf-8", errors="ignore"))


HEADING = re.compile(r"^(?:#{1,4}\s+\S.{0,90}|(?:section\s+)?\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+[A-Z][^\n]{2,90}|[A-Z][A-Z0-9 ,&/()'-]{4,80})$", re.I)


def _is_heading(line: str) -> bool:
    s = line.strip()
    return 3 < len(s) < 95 and not s.endswith((".", ",", ";")) and bool(HEADING.match(s)) and len(s.split()) <= 12


def chunk_pages(pages: list[str], code: str, max_chars: int = 1100) -> list[dict]:
    chunks, section = [], "Front matter"
    for pno, page in enumerate(pages, start=1):
        n, buf = 0, []

        def flush():
            nonlocal n, buf
            body = "\n".join(buf).strip()
            if len(body) > 40:
                n += 1
                chunks.append({"chunk_id": f"{code}-p{pno}-c{n}", "page": pno, "section": section, "text": body})
            buf = []

        for line in page.splitlines():
            if _is_heading(line):
                flush()
                section = line.strip().lstrip("#").strip()[:90]
                buf.append(line.strip())
                continue
            buf.append(line)
            if sum(len(b) for b in buf) > max_chars:
                flush()
        flush()
    return chunks


def _vtuple(v: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", v or "")) or (0,)


def _code(doc_type: str, version: str) -> str:
    v = re.sub(r"[^A-Za-z0-9.]", "", version or "") or "0"
    return f"{DOC_CODES.get(doc_type, 'DOC')}v{v}"


def _norm_phase(p: str) -> str:
    p = (p or "").upper()
    if "III" in p or "3" in p:
        return "Phase III"
    if "II" in p or "2" in p:
        return "Phase II"
    if "I" in p.replace("PHASE", "") or "1" in p:
        return "Phase I"
    return ""


# ---------------------------------------------------------------- prompts
META_SYS = (
    "You classify clinical trial documents. Return JSON with keys: "
    f"doc_type (one of {list(DOC_TYPES)}), title, version (e.g. '2.1', without 'v'; amendments use their number), "
    "study_id (protocol/study number such as 'CT-204', '' if absent), phase ('Phase I','Phase II','Phase III' or ''), "
    "effective_date (YYYY-MM-DD or ''), references (list of {doc_type, version} for OTHER trial documents this "
    "document explicitly says it is based on or refers to, e.g. an ICF based on Protocol version 2.0)."
)

DIGEST_SYS = (
    "You are a clinical-trial document analyst. You receive de-identified chunks, each prefixed with its ID in "
    "square brackets. Every item you output MUST cite exactly one chunk ID that directly supports it. Do not invent "
    "facts. Keep each text under 30 words. Return JSON with keys:\n"
    "executive_summary: 5-7 items {text, cite} covering purpose, design, population, endpoints, dosing, key risks and open issues;\n"
    "key_sections: up to 6 items {section, why, cite} naming the sections a reviewer must read and why;\n"
    "lenses: object keyed by the requested role codes, each a list of 5 items {text, cite} written for that role;\n"
    f"facts: up to 30 items {{topic, value, cite}} with topic from {FACT_TOPICS}; values must be specific "
    "(numbers, weeks, doses, criteria) so they can be compared with other documents."
)

VERIFY_SYS = (
    "You are a strict fact verifier. For each claim, decide whether the cited source text directly supports it. "
    "Paraphrase is fine; any number, timing, dose or criterion that is not in the source makes it unsupported. "
    'Return JSON {"results": [{"id": <claim id>, "supported": true|false}]}.'
)


# ---------------------------------------------------------------- graph
class IngestState(TypedDict, total=False):
    job_id: str
    path: str
    user: str
    role: str
    overrides: dict
    pages: list
    meta: dict
    redactions: dict
    doc_id: int
    chunks: list
    digest: dict
    duplicate: bool


def _steps(job_id: str) -> list[dict]:
    return json.loads(db.q1("SELECT steps_json FROM jobs WHERE id=?", (job_id,))["steps_json"])


def _set_step(job_id: str, i: int, status: str, detail: str = "") -> None:
    steps = _steps(job_id)
    steps[i]["status"], steps[i]["detail"] = status, detail
    db.x("UPDATE jobs SET steps_json=? WHERE id=?", (json.dumps(steps), job_id))


def step(i: int):
    """Decorator: marks the job step running/done and traces it as a span."""
    def wrap(fn):
        def node(state: IngestState):
            _set_step(state["job_id"], i, "running")
            with tracing.span(STEPS[i]) as sp:
                out, detail = fn(state)
                sp["detail"] = detail
            _set_step(state["job_id"], i, "done", detail)
            return out
        return node
    return wrap


@step(0)
def n_parse(s: IngestState):
    path = Path(s["path"])
    h = file_hash(path)
    dup = db.q1("SELECT id FROM documents WHERE file_hash=?", (h,))
    if dup:
        return {"duplicate": True, "doc_id": dup["id"]}, "Same file already ingested - skipped"
    pages = parse_file(path)
    chars = sum(len(p) for p in pages)
    if chars < 50:
        raise ValueError("No extractable text (scanned PDF?)")
    return {"pages": pages}, f"{len(pages)} pages · {chars:,} characters"


@step(1)
def n_detect(s: IngestState):
    head = "\n".join(s["pages"])[:6000]
    head, _ = deidentify(head)  # nothing un-redacted ever reaches the LLM
    meta = chat_json(MODEL_FAST, META_SYS, f"File name: {Path(s['path']).name}\n\n{head}", max_tokens=400)
    ov = {k: v for k, v in (s.get("overrides") or {}).items() if v}
    meta.update(ov)
    meta["doc_type"] = meta.get("doc_type") if meta.get("doc_type") in DOC_TYPES else "OTHER"
    meta["version"] = str(meta.get("version") or "1.0").lstrip("vV ")
    sid = (meta.get("study_id") or "").strip().upper()
    if not sid:
        existing = db.q("SELECT study_id, COUNT(*) n FROM documents GROUP BY study_id ORDER BY n DESC")
        sid = existing[0]["study_id"] if existing else "STUDY-1"
    meta["study_id"] = sid
    meta["phase"] = _norm_phase(meta.get("phase", ""))
    if not meta["phase"]:
        other = db.q1("SELECT phase FROM documents WHERE study_id=? AND phase!='' LIMIT 1", (sid,))
        meta["phase"] = other["phase"] if other else ""
    meta["references"] = [r for r in (meta.get("references") or []) if isinstance(r, dict) and r.get("doc_type") in DOC_TYPES]
    return {"meta": meta}, f"{DOC_TYPES[meta['doc_type']]} v{meta['version']} · {sid} · {meta['phase'] or 'phase unknown'}"


@step(2)
def n_deid(s: IngestState):
    total = {}
    clean = []
    for p in s["pages"]:
        t, c = deidentify(p)
        clean.append(t)
        for k, v in c.items():
            total[k] = total.get(k, 0) + v
    n = sum(total.values())
    detail = f"{n} identifiers masked" + (f" ({', '.join(f'{k} {v}' for k, v in total.items())})" if n else "")
    return {"pages": clean, "redactions": total}, detail


@step(3)
def n_index(s: IngestState):
    m, path = s["meta"], Path(s["path"])
    code = _code(m["doc_type"], m["version"])
    if m["doc_type"] not in ("AMENDMENT", "OTHER"):
        # same controlled document type+version re-uploaded with different content -> replace older copy
        for old in db.q("SELECT id FROM documents WHERE study_id=? AND code=?", (m["study_id"], code)):
            _remove_doc(old["id"])
    # codes prefix chunk IDs, so they must be globally unique (e.g. two "Other v1.0" documents)
    base, ver, n = DOC_CODES.get(m["doc_type"], "DOC"), code.split("v", 1)[1], 2
    while db.q1("SELECT 1 FROM documents WHERE code=?", (code,)):
        code, n = f"{base}{n}v{ver}", n + 1
    chunks = chunk_pages(s["pages"], code)
    doc_id = db.x(
        "INSERT INTO documents(file_name,file_hash,study_id,phase,doc_type,title,version,effective_date,code,pages,chars,"
        "is_current,redactions,redaction_detail,references_json,prompt_version,ingested_at,ingested_by) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)",
        (path.name, file_hash(path), m["study_id"], m["phase"], m["doc_type"], m.get("title") or path.stem,
         m["version"], m.get("effective_date", ""), code, len(s["pages"]), sum(len(p) for p in s["pages"]),
         sum(s["redactions"].values()), json.dumps(s["redactions"]), json.dumps(m["references"]), PROMPT_VERSION,
         db.now(), s["user"]))
    for c in chunks:
        db.x("INSERT OR REPLACE INTO chunks(chunk_id,doc_id,page,section,text) VALUES(?,?,?,?,?)",
             (c["chunk_id"], doc_id, c["page"], c["section"], c["text"]))
    vectorstore.add_chunks([{**c, "text": f"{c['section']}\n{c['text']}", "doc_id": doc_id, "doc_type": m["doc_type"],
                             "study_id": m["study_id"], "version": m["version"]} for c in chunks])
    superseded = _apply_versioning(doc_id)
    detail = f"{len(chunks)} chunks indexed in ChromaDB" + (f" · supersedes {', '.join(superseded)}" if superseded else "")
    return {"doc_id": doc_id, "chunks": chunks}, detail


def _apply_versioning(doc_id: int) -> list[str]:
    d = db.q1("SELECT * FROM documents WHERE id=?", (doc_id,))
    if d["doc_type"] in ("AMENDMENT", "OTHER"):
        return []
    others = db.q("SELECT * FROM documents WHERE study_id=? AND doc_type=? AND id!=?", (d["study_id"], d["doc_type"], doc_id))
    newest = max([d] + others, key=lambda r: _vtuple(r["version"]))
    out = []
    for r in [d] + others:
        cur = r["id"] == newest["id"]
        if bool(r["is_current"]) != cur:
            db.x("UPDATE documents SET is_current=? WHERE id=?", (1 if cur else 0, r["id"]))
            vectorstore.set_current(r["id"], cur)
            if not cur:
                out.append(f"v{r['version']}")
    return out


def _remove_doc(doc_id: int) -> None:
    ids = [r["chunk_id"] for r in db.q("SELECT chunk_id FROM chunks WHERE doc_id=?", (doc_id,))]
    if ids:
        vectorstore.chunks_col.delete(ids=ids)
    db.x("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    db.x("DELETE FROM documents WHERE id=?", (doc_id,))


@step(4)
def n_digest(s: IngestState):
    m = s["meta"]
    roles = [r for r in LENS_ROLES if m["doc_type"] in ROLES[r]["docs"]]
    body, used = [], 0
    for c in s["chunks"]:
        line = f"[{c['chunk_id']}] ({c['section']}) {c['text']}"
        if used + len(line) > MAX_DIGEST_CHARS:
            break
        body.append(line)
        used += len(line)
    user = (f"Document: {DOC_TYPES[m['doc_type']]} v{m['version']} ({m['study_id']}).\n"
            f"Role codes for lenses: {roles} - " + "; ".join(f"{r} = {ROLES[r]['lens']}" for r in roles) +
            "\n\nCHUNKS:\n" + "\n".join(body))
    with tracing.span("Digest call", MODEL_FAST) as sp:
        digest = chat_json(MODEL_FAST, DIGEST_SYS, user, max_tokens=3500)
        sp["detail"] = f"{len(body)} of {len(s['chunks'])} chunks in context"
    digest["_tokens"] = sum(x["tokens_in"] + x["tokens_out"] for x in tracing.current().spans if x["name"] == "Digest call")
    digest["lenses"] = {r: v for r, v in (digest.get("lenses") or {}).items() if r in roles}
    n = len(digest.get("executive_summary", [])) + sum(len(v) for v in digest["lenses"].values()) + len(digest.get("facts", []))
    return {"digest": digest}, f"{n} cited items · {len(digest['lenses'])} role lenses · 1 LLM call"


@step(5)
def n_verify(s: IngestState):
    digest = s["digest"]
    texts = {c["chunk_id"]: c["text"] for c in s["chunks"]}
    claims = []  # (id, ref-list, index, item)
    for key in ("executive_summary", "facts"):
        for i, it in enumerate(digest.get(key) or []):
            claims.append((f"{key[:2]}{i}", key, None, i, it))
    for role, items in digest["lenses"].items():
        for i, it in enumerate(items):
            claims.append((f"l{role}{i}", "lenses", role, i, it))
    supported = set()
    to_check = []
    for cid, _, _, _, it in claims:
        cite = (it.get("cite") or "").strip("[] ")
        it["cite"] = cite
        if cite in texts:
            to_check.append((cid, it))
    for b in range(0, len(to_check), 40):
        batch = to_check[b:b + 40]
        cites = {it["cite"] for _, it in batch}
        src = "\n".join(f"[{c}] {texts[c][:1100]}" for c in cites)
        lines = "\n".join(f"{cid}: {it.get('text') or (it.get('topic', '') + ': ' + str(it.get('value', '')))} (cites {it['cite']})"
                          for cid, it in batch)
        with tracing.span("Verifier call", MODEL_FAST):
            res = chat_json(MODEL_FAST, VERIFY_SYS, f"SOURCES:\n{src}\n\nCLAIMS:\n{lines}", max_tokens=1500)
        supported |= {r["id"] for r in res.get("results", []) if r.get("supported")}
    keep = lambda cid: cid in supported
    digest["executive_summary"] = [it for cid, k, _, i, it in claims if k == "executive_summary" and keep(cid)]
    digest["facts"] = [it for cid, k, _, i, it in claims if k == "facts" and keep(cid)]
    digest["lenses"] = {r: [it for cid, k, rr, i, it in claims if k == "lenses" and rr == r and keep(cid)]
                        for r in digest["lenses"]}
    total, ok = len(claims), len(supported)
    db.x("UPDATE documents SET digest_json=?, facts_json=?, claims_total=?, claims_supported=? WHERE id=?",
         (json.dumps(digest), json.dumps(digest["facts"]), total, ok, s["doc_id"]))
    d = db.q1("SELECT * FROM documents WHERE id=?", (s["doc_id"],))
    db.x("INSERT INTO outputs(kind,ref,title,study_id,status,detail,created_at) VALUES('summary',?,?,?,'draft',?,?)",
         (str(d["id"]), f"AI summary · {DOC_TYPES[d['doc_type']]} v{d['version']}", d["study_id"],
          f"{ok}/{total} claims verified", db.now()))
    return {}, f"{ok} of {total} claims supported by their source · {total - ok} dropped"


def n_consistency(s: IngestState):
    from .consistency import run_consistency
    _set_step(s["job_id"], 6, "running")
    with tracing.span(STEPS[6]) as sp:
        study = db.q1("SELECT study_id FROM documents WHERE id=?", (s["doc_id"],))["study_id"]
        res = run_consistency(study, s["user"], s["role"], nested=True)
        sp["detail"] = res["summary"]
    _set_step(s["job_id"], 6, "done", res["summary"])
    return {}


def _after_parse(s):
    return END if s.get("duplicate") else "detect"


def _after_verify(s):
    study = db.q1("SELECT study_id FROM documents WHERE id=?", (s["doc_id"],))["study_id"]
    n = db.q1("SELECT COUNT(*) n FROM documents WHERE study_id=? AND is_current=1", (study,))["n"]
    return "consistency" if n >= 2 else END


def _build():
    g = StateGraph(IngestState)
    g.add_node("parse", n_parse)
    g.add_node("detect", n_detect)
    g.add_node("deid", n_deid)
    g.add_node("index", n_index)
    g.add_node("digest", n_digest)
    g.add_node("verify", n_verify)
    g.add_node("consistency", n_consistency)
    g.set_entry_point("parse")
    g.add_conditional_edges("parse", _after_parse, {"detect": "detect", END: END})
    g.add_edge("detect", "deid")
    g.add_edge("deid", "index")
    g.add_edge("index", "digest")
    g.add_edge("digest", "verify")
    g.add_conditional_edges("verify", _after_verify, {"consistency": "consistency", END: END})
    g.add_edge("consistency", END)
    return g.compile()


GRAPH = _build()


# ---------------------------------------------------------------- jobs
def new_job(path: Path, user: str) -> str:
    jid = "job_" + uuid.uuid4().hex[:8]
    steps = [{"name": n, "status": "pending", "detail": ""} for n in STEPS]
    db.x("INSERT INTO jobs(id,file_name,status,steps_json,created_at,user) VALUES(?,?,?,?,?,?)",
         (jid, path.name, "queued", json.dumps(steps), db.now(), user))
    return jid


def run_job(jid: str, path: Path, user: str, role: str, overrides: dict | None = None) -> None:
    with _ingest_lock:
        db.x("UPDATE jobs SET status='running' WHERE id=?", (jid,))
        trace = tracing.start_trace(user, role, "ingest", f"Ingest {path.name}")
        t0 = time.perf_counter()
        try:
            out = GRAPH.invoke({"job_id": jid, "path": str(path), "user": user, "role": role, "overrides": overrides or {}})
            if out.get("duplicate"):
                for i in range(1, len(STEPS)):
                    _set_step(jid, i, "skipped")
                db.x("UPDATE jobs SET status='duplicate', doc_id=? WHERE id=?", (out.get("doc_id"), jid))
                tracing.finish(trace, "Duplicate")
                return
            if any(st["status"] == "pending" for st in _steps(jid)):
                _set_step(jid, 6, "skipped", "Needs at least 2 current documents in the study")
            ms = int((time.perf_counter() - t0) * 1000)
            db.x("UPDATE documents SET processing_ms=? WHERE id=?", (ms, out["doc_id"]))
            db.x("UPDATE jobs SET status='done', doc_id=? WHERE id=?", (out["doc_id"], jid))
            d = db.q1("SELECT * FROM documents WHERE id=?", (out["doc_id"],))
            db.audit(user, role, "DOC_INGEST", f"{d['code']} ({d['study_id']})",
                     f"{d['pages']} pp · {d['redactions']} PHI entities masked · {d['claims_supported']}/{d['claims_total']} claims verified · {trace.id}")
            tracing.finish(trace, "Ingested")
        except Exception as e:
            steps = _steps(jid)
            for i, st in enumerate(steps):
                if st["status"] == "running":
                    _set_step(jid, i, "error", str(e)[:300])
            db.x("UPDATE jobs SET status='error', error=? WHERE id=?", (str(e)[:500], jid))
            tracing.finish(trace, "Error")


def start_job(path: Path, user: str, role: str, overrides: dict | None = None) -> str:
    jid = new_job(path, user)
    threading.Thread(target=run_job, args=(jid, path, user, role, overrides), daemon=True).start()
    return jid


def sync_repository(user: str, role: str) -> list[str]:
    known = {r["file_hash"] for r in db.q("SELECT file_hash FROM documents")}
    jobs = []
    for p in sorted(REPO_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED and file_hash(p) not in known:
            jobs.append(start_job(p, user, role))
    return jobs
