"""Cross-document consistency agent (LangGraph): gather facts -> rule-based version check
-> LLM judge (gpt-4.1, the only place the bigger model is used) -> persist findings.

Facts were extracted once per document at ingest, so the judge sees compact cited facts, not raw documents.
"""
import json
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from . import db, tracing
from .config import DOC_TYPES, MODEL_JUDGE

JUDGE_SYS = (
    "You are a clinical-trial cross-document consistency judge. You receive cited facts extracted from the current "
    "documents of ONE study. Report genuine conflicts or omissions where documents must agree; ignore wording "
    "differences and facts that only one document is expected to contain. Rules: the ICF must reflect the protocol's "
    "visits, procedures, eligibility essentials, re-consent needs and key risks; Protocol, IB and SAP must agree on "
    "dosing/titration, endpoints and safety rules; an amendment overrides the protocol it amends, so compare the "
    "amended value; the regulatory submission must match the protocol on design, sample size and endpoints.\n"
    'Return JSON {"compared": <number of fact pairs you compared>, "findings": [{"topic", "item" (short label, max 6 '
    'words), "doc_a" (doc code), "value_a", "cite_a" (chunk id from doc_a facts), "doc_b", "value_b", "cite_b", '
    '"severity" ("High" if it affects subject safety, consent validity or the primary endpoint, else "Medium" or "Low"), '
    '"owner_role" ("mr" for safety, dosing, endpoints; "cra" for consent, eligibility, site procedures; "com" for '
    'visit schedule, timelines, versions, operations), "rationale" (one sentence)}]}'
)


class CState(TypedDict, total=False):
    study: str
    user: str
    role: str
    docs: list
    rule_findings: list
    llm_findings: list
    compared: int


def n_gather(s: CState):
    with tracing.span("Gather facts", "sqlite") as sp:
        docs = db.q("SELECT id, code, doc_type, version, facts_json, references_json FROM documents "
                    "WHERE study_id=? AND is_current=1 ORDER BY doc_type", (s["study"],))
        n = sum(len(json.loads(d["facts_json"] or "[]")) for d in docs)
        sp["detail"] = f"{len(docs)} current documents · {n} cited facts (from ingest cache, 0 tokens)"
    return {"docs": docs}


def _first_chunk(doc_id: int, needle: str | None = None) -> str:
    if needle:
        r = db.q1("SELECT chunk_id FROM chunks WHERE doc_id=? AND text LIKE ? ORDER BY page LIMIT 1", (doc_id, f"%{needle}%"))
        if r:
            return r["chunk_id"]
    r = db.q1("SELECT chunk_id FROM chunks WHERE doc_id=? ORDER BY page LIMIT 1", (doc_id,))
    return r["chunk_id"] if r else ""


def n_version_rules(s: CState):
    """Deterministic check, zero tokens: does any document reference a superseded version?"""
    with tracing.span("Version reference check", "rules") as sp:
        out = []
        cur = {d["doc_type"]: d for d in s["docs"]}
        for d in s["docs"]:
            for ref in json.loads(d["references_json"] or "[]"):
                tgt = cur.get(ref.get("doc_type"))
                rv = str(ref.get("version", "")).lstrip("vV ")
                if not tgt or not rv or tgt["id"] == d["id"]:
                    continue
                if re.findall(r"\d+", rv) != re.findall(r"\d+", tgt["version"]):
                    label = DOC_TYPES[tgt["doc_type"]]
                    out.append({
                        "topic": "version_reference", "item": f"{label} version referenced",
                        "doc_a": d["code"], "value_a": f"References {label} v{rv}", "cite_a": _first_chunk(d["id"], rv),
                        "doc_b": tgt["code"], "value_b": f"Current {label} is v{tgt['version']}", "cite_b": _first_chunk(tgt["id"]),
                        "severity": "High" if d["doc_type"] == "ICF" else "Medium", "owner_role": "com",
                        "rationale": f"{d['code']} is based on a superseded {label}; update it and check whether re-consent or re-training is needed.",
                        "source": "rule"})
        sp["detail"] = f"{len(out)} superseded references found"
    return {"rule_findings": out}


def n_judge(s: CState):
    blocks = []
    for d in s["docs"]:
        facts = json.loads(d["facts_json"] or "[]")[:40]
        if facts:
            blocks.append(f"## {d['code']} - {DOC_TYPES[d['doc_type']]} v{d['version']}\n" +
                          "\n".join(f"- [{f.get('topic')}] {f.get('value')} ({f.get('cite')})" for f in facts))
    if len(blocks) < 2:
        return {"llm_findings": [], "compared": 0}
    from .llm import chat_json
    with tracing.span("Consistency judge", MODEL_JUDGE) as sp:
        res = chat_json(MODEL_JUDGE, JUDGE_SYS, "\n\n".join(blocks), max_tokens=3000)
        f = [x for x in res.get("findings", []) if isinstance(x, dict) and x.get("doc_a") and x.get("doc_b")]
        sp["detail"] = f"{len(f)} conflicts across {len(blocks)} documents"
    for x in f:
        x["source"] = "llm"
    return {"llm_findings": f, "compared": int(res.get("compared") or 0)}


def _key(study: str, f: dict) -> str:
    docs = "|".join(sorted([f["doc_a"], f["doc_b"]]))
    item = re.sub(r"[^a-z0-9]+", " ", (f.get("item") or "").lower()).strip()[:40]
    return f"{study}|{f.get('topic')}|{docs}|{item}"


def n_persist(s: CState):
    with tracing.span("Persist findings", "sqlite") as sp:
        found = s["rule_findings"] + s["llm_findings"]
        keys, new = set(), 0
        trace = tracing.current()
        for f in found:
            k = _key(s["study"], f)
            keys.add(k)
            ex = db.q1("SELECT id, status FROM findings WHERE dedup_key=?", (k,))
            if ex:
                if ex["status"] == "resolved":
                    db.x("UPDATE findings SET status='open' WHERE id=?", (ex["id"],))
                continue
            n = db.q1("SELECT COUNT(*) n FROM findings")["n"] + 1
            sev = f.get("severity") if f.get("severity") in ("High", "Medium", "Low") else "Medium"
            owner = f.get("owner_role") if f.get("owner_role") in ("com", "cra", "mr") else "com"
            db.x("INSERT INTO findings(id,study_id,dedup_key,topic,item,doc_a,value_a,cite_a,doc_b,value_b,cite_b,severity,"
                 "owner_role,rationale,source,status,trace_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?)",
                 (f"DSC-{n:03d}", s["study"], k, f.get("topic", ""), f.get("item", ""), f["doc_a"], str(f.get("value_a", "")),
                  f.get("cite_a", ""), f["doc_b"], str(f.get("value_b", "")), f.get("cite_b", ""), sev, owner,
                  f.get("rationale", ""), f["source"], trace.id if trace else "", db.now()))
            new += 1
        resolved = 0
        for r in db.q("SELECT id, dedup_key FROM findings WHERE study_id=? AND status='open'", (s["study"],)):
            if r["dedup_key"] not in keys:
                db.x("UPDATE findings SET status='resolved', decided_at=?, decision='auto-resolved' WHERE id=?", (db.now(), r["id"]))
                resolved += 1
        compared = max(s.get("compared", 0), len(found))
        db.set_setting(f"compared:{s['study']}", compared)
        sp["detail"] = f"{new} new · {len(found) - new} unchanged · {resolved} no longer present"
    return {}


def _build():
    g = StateGraph(CState)
    g.add_node("gather", n_gather)
    g.add_node("rules", n_version_rules)
    g.add_node("judge", n_judge)
    g.add_node("persist", n_persist)
    g.set_entry_point("gather")
    g.add_edge("gather", "rules")
    g.add_edge("rules", "judge")
    g.add_edge("judge", "persist")
    g.add_edge("persist", END)
    return g.compile()


GRAPH = _build()


def run_consistency(study: str, user: str, role: str, nested: bool = False) -> dict:
    trace = None if nested else tracing.start_trace(user, role, "consistency", f"Consistency check {study}")
    GRAPH.invoke({"study": study, "user": user, "role": role})
    open_n = db.q1("SELECT COUNT(*) n FROM findings WHERE study_id=? AND status IN ('open','raised')", (study,))["n"]
    summary = f"{open_n} open findings in {study}"
    db.audit(user, role, "CONSISTENCY_RUN", study, summary + (f" · {trace.id}" if trace else ""))
    if trace:
        info = tracing.finish(trace, "Completed")
        return {"summary": summary, **info}
    return {"summary": summary}
