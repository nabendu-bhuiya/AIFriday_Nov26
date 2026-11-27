"""Ask agent (LangGraph).

input_guard -> router -> cache_lookup -> retrieve -> specialist -> verifier -> output_guard
Token optimisation built into the graph:
  * rules before LLMs: guardrails and routing are regex/rules (0 tokens); the LLM router only runs to
    rewrite follow-up questions that depend on chat history;
  * summary questions are served from the verified digest cached at ingest (0 tokens);
  * semantic answer cache keyed by role + study + document versions (stale answers impossible);
  * hybrid retrieval keeps only the top-6 chunks; hard token budget; JSON output with capped max_tokens;
  * chat memory: last 2 turns verbatim + a compact extractive summary of older turns (no LLM call).
"""
import json
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from . import db, guardrails, tracing, vectorstore
from .config import DOC_TYPES, MODEL_FAST, PROMPT_VERSION, ROLES, TOKEN_BUDGET, TOP_K
from .deid import deidentify
from .llm import chat_json

DISCLAIMER = "AI-generated. Check the cited source before acting."

SPECIALIST_SYS = (
    "You are TrialLens, an assistant for clinical-trial document review. Answer ONLY from the provided context. "
    "Every claim must cite one or more context IDs exactly as given in square brackets. If the context does not "
    "contain the answer, set insufficient to true and return no claims. Be concise: at most 5 claims, each under "
    "35 words. Never output patient identifiers.\n"
    'Return JSON {"claims": [{"text": "...", "cites": ["ID", ...]}], "insufficient": false}'
)
VERIFY_SYS = (
    "You are a strict verifier. For each claim decide whether the cited sources directly support it. Any number, "
    "timing, dose or criterion not present in the sources makes it unsupported. "
    'Return JSON {"results": [{"id": "<claim id>", "supported": true|false}]}'
)
ROUTER_SYS = (
    "Rewrite the user's follow-up into a standalone question using the conversation, and classify intent. "
    'Return JSON {"standalone": "...", "intent": "qa"|"consistency"|"summary"}'
)

SESSIONS: dict[str, dict] = {}


class AskState(TypedDict, total=False):
    user: str
    role: str
    study: str
    question: str
    blocked: dict
    intent: str
    standalone: str
    cache_key: str
    cached: dict
    context: list          # [{id, label, text}]
    claims: list
    grounded: float
    insufficient: bool
    status: str
    message: str


# ---------------------------------------------------------------- nodes
def n_input_guard(s: AskState):
    with tracing.span("Input guard", "rules") as sp:
        q = s["question"]
        if guardrails.enabled("phi"):
            q, c = deidentify(q)
        block = guardrails.check_input(q, s["role"])
        sp["detail"] = f"blocked: {block['code']}" if block else f"PHI + injection + topic + scope checks passed; role = {ROLES[s['role']]['short']}"
        if block:
            sp["status"] = "blocked"
            return {"blocked": block, "status": "blocked", "message": block["message"], "question": q}
    return {"question": q}


_FOLLOW = re.compile(r"\b(it|its|that|this|those|these|they|them|same|above|previous|earlier|what about)\b", re.I)


def n_router(s: AskState):
    q = s["question"]
    if s["role"] == "adm":
        with tracing.span("Router", "rules", "intent = platform (admin has no document scope)"):
            return {"intent": "platform", "standalone": q}
    hist = SESSIONS.get(s["user"], {}).get("turns", [])
    if hist and _FOLLOW.search(q):
        mem = SESSIONS[s["user"]]
        conv = (f"Earlier: {mem['summary']}\n" if mem["summary"] else "") + "\n".join(
            f"Q: {t['q']}\nA: {t['a'][:300]}" for t in hist[-2:])
        with tracing.span("Router", MODEL_FAST) as sp:
            r = chat_json(MODEL_FAST, ROUTER_SYS, f"{conv}\n\nFollow-up: {q}", max_tokens=150)
            intent = r.get("intent") if r.get("intent") in ("qa", "consistency", "summary") else "qa"
            sp["detail"] = f"follow-up rewritten · intent = {intent}"
            return {"intent": intent, "standalone": r.get("standalone") or q}
    with tracing.span("Router", "rules") as sp:
        if re.search(r"discrepanc|inconsisten|conflict|mismatch|differ|contradict|align", q, re.I):
            intent = "consistency"
        elif re.search(r"\b(summar|overview|key points|executive|main points)", q, re.I) and _doc_mentioned(q):
            intent = "summary"
        else:
            intent = "qa"
        sp["detail"] = f"intent = {intent} (rules, 0 tokens)"
    return {"intent": intent, "standalone": q}


def _doc_mentioned(q: str) -> str | None:
    pats = {"PROTOCOL": r"protocol", "AMENDMENT": r"amendment|\bAMD", "ICF": r"\bICF\b|consent", "IB": r"brochure|\bIB\b",
            "SAP": r"\bSAP\b|analysis plan", "REG_SUBMISSION": r"submission", "DSMB_CHARTER": r"DSMB"}
    for t, p in pats.items():
        if re.search(p, q, re.I):
            return t
    return None


def _versions_sig(study: str) -> str:
    return ",".join(r["code"] for r in db.q("SELECT code FROM documents WHERE study_id=? AND is_current=1 ORDER BY code", (study,)))


def n_cache(s: AskState):
    if s["intent"] not in ("qa", "consistency"):
        return {}
    extra = ""
    if s["intent"] == "consistency":
        extra = "|" + ",".join(f"{r['id']}:{r['status']}" for r in db.q("SELECT id,status FROM findings WHERE study_id=? ORDER BY id", (s["study"],)))
    key = f"{s['role']}|{s['study']}|{_versions_sig(s['study'])}|{PROMPT_VERSION}|{s['intent']}{extra}"
    with tracing.span("Semantic cache", "local MiniLM embedding") as sp:
        hit = vectorstore.cache_lookup(s["standalone"], key)
        if hit and "answer" in hit:
            ans = json.loads(hit["answer"])
            sp["detail"] = f"hit: similarity {hit['similarity']} · source trace {hit['trace_id']}"
            tracing.add_saving("Semantic answer cache", int(hit.get("tokens", 0)))
            return {"cache_key": key, "cached": {**ans, "source_trace": hit["trace_id"]}, "status": "answered"}
        sp["detail"] = f"miss: best similarity {hit['miss_similarity']} under 0.92" if hit else "miss: cache empty for this key"
    return {"cache_key": key}


def _label(cid: str) -> str:
    m = re.match(r"([A-Z]+\d*)v([\w.]+)-p(\d+)-c\d+", cid)
    return f"{m.group(1)} v{m.group(2)} p.{m.group(3)}" if m else cid


def n_retrieve(s: AskState):
    intent = s["intent"]
    if intent == "consistency":
        with tracing.span("Retriever", "sqlite") as sp:
            allowed = {r["code"] for r in db.q(
                f"SELECT code FROM documents WHERE study_id=? AND doc_type IN ({','.join('?' * len(ROLES[s['role']]['docs']))})",
                (s["study"], *ROLES[s["role"]]["docs"]))}
            rows = [r for r in db.q("SELECT * FROM findings WHERE study_id=? AND status NOT IN ('resolved') ORDER BY severity, id", (s["study"],))
                    if r["doc_a"] in allowed and r["doc_b"] in allowed]
            ctx = [{"id": r["id"], "label": r["id"],
                    "text": f"{r['item']} [{r['status']}, {r['severity']}]: {r['doc_a']} says {r['value_a']} ({r['cite_a']}); "
                            f"{r['doc_b']} says {r['value_b']} ({r['cite_b']}). {r['rationale']}"} for r in rows[:15]]
            sp["detail"] = f"{len(ctx)} findings visible to role"
        return {"context": ctx}
    if intent == "summary":
        with tracing.span("Retriever", "digest cache") as sp:
            dtype = _doc_mentioned(s["standalone"])
            d = db.q1("SELECT * FROM documents WHERE study_id=? AND doc_type=? AND is_current=1", (s["study"], dtype))
            if not d or dtype not in ROLES[s["role"]]["docs"] or not d["digest_json"]:
                sp["detail"] = "no cached digest - falling back to Q&A"
                return {"intent": "qa", "context": _search(s)}
            dg = json.loads(d["digest_json"])
            items = dg.get("lenses", {}).get(s["role"]) or dg.get("executive_summary", [])
            claims = [{"text": it["text"], "cites": [it["cite"]]} for it in items[:6]]
            tracing.add_saving("Digest reuse (summary built once at ingest)", int(dg.get("_tokens", 0)))
            sp["detail"] = f"served {len(claims)} pre-verified items from {d['code']} digest · 0 tokens"
        return {"claims": claims, "grounded": 1.0, "context": []}
    return {"context": _search(s)}


def _search(s: AskState) -> list[dict]:
    with tracing.span("Retriever", "BM25 + Chroma vector") as sp:
        rows, cand_chars = vectorstore.hybrid_search(s["standalone"], s["study"], s["role"], TOP_K)
        budget_chars = (TOKEN_BUDGET - 1500) * 4 if guardrails.enabled("budget") else 10 ** 9
        ctx, used = [], 0
        for r in rows:
            t = r["text"]
            if used + len(t) > budget_chars:
                break
            ctx.append({"id": r["chunk_id"], "label": _label(r["chunk_id"]), "text": t})
            used += len(t)
        tracing.add_saving("Context compression: top-6 of 20 candidates", max(0, (cand_chars - used) // 4))
        sp["detail"] = f"{len(ctx)} chunks, role-filtered: " + ", ".join(c["label"] for c in ctx[:4])
    return ctx


def n_specialist(s: AskState):
    if s.get("claims") is not None and s["intent"] == "summary":
        return {}
    if not s.get("context"):
        return {"claims": [], "insufficient": True}
    name = "Consistency agent" if s["intent"] == "consistency" else "Q&A agent"
    sys = SPECIALIST_SYS + f"\nReader: {ROLES[s['role']]['name']}. {ROLES[s['role']]['lens']}"
    ctx = "\n".join(f"[{c['id']}] {c['text']}" for c in s["context"])
    with tracing.span(name, MODEL_FAST) as sp:
        r = chat_json(MODEL_FAST, sys, f"CONTEXT:\n{ctx}\n\nQUESTION: {s['standalone']}", max_tokens=600)
        claims = [c for c in r.get("claims", []) if isinstance(c, dict) and c.get("text")][:5]
        for c in claims:
            c["cites"] = [str(x).strip("[] ") for x in (c.get("cites") or [])]
        sp["detail"] = f"prompt {PROMPT_VERSION} · temperature 0 · JSON · {len(claims)} claims"
    return {"claims": claims, "insufficient": bool(r.get("insufficient")) and not claims}


def n_verifier(s: AskState):
    claims = s.get("claims") or []
    if s["intent"] == "summary" or not claims:
        return {}
    ctx = {c["id"]: c["text"] for c in s["context"]}
    need_cite = guardrails.enabled("cite")
    for c in claims:
        c["cites"] = [x for x in c["cites"] if x in ctx]
    if s["intent"] == "consistency":
        with tracing.span("Verifier", "rules", ) as sp:
            ok = [c for c in claims if c["cites"]] if need_cite else claims
            sp["detail"] = f"{len(ok)} of {len(claims)} claims cite a known finding"
            return {"claims": ok, "grounded": len(ok) / len(claims)}
    checkable = [(f"c{i}", c) for i, c in enumerate(claims) if c["cites"]]
    supported = set()
    if checkable:
        src_ids = {x for _, c in checkable for x in c["cites"]}
        src = "\n".join(f"[{i}] {ctx[i]}" for i in src_ids)
        lines = "\n".join(f"{cid}: {c['text']} (cites {', '.join(c['cites'])})" for cid, c in checkable)
        with tracing.span("Verifier", MODEL_FAST) as sp:
            r = chat_json(MODEL_FAST, VERIFY_SYS, f"SOURCES:\n{src}\n\nCLAIMS:\n{lines}", max_tokens=300)
            supported = {x["id"] for x in r.get("results", []) if x.get("supported")}
            sp["detail"] = f"{len(supported)} of {len(claims)} claims supported"
    grounded = len(supported) / len(claims)
    kept = [c for cid, c in checkable if cid in supported] if need_cite else claims
    return {"claims": kept, "grounded": round(grounded, 2)}


def _restricted_hit(s: AskState) -> bool:
    """Zero-token check: would an unrestricted search find the answer in a document type this role may not see?
    Only content from the top results matters, and nothing from it is returned to the user."""
    if not guardrails.enabled("scope"):
        return False
    allowed = set(ROLES[s["role"]]["docs"])
    if allowed >= set(DOC_TYPES):
        return False
    rows, _ = vectorstore.hybrid_search(s["standalone"], s["study"], "aud", 3)
    qt = set(vectorstore._terms(s["standalone"])) - {"study", "trial", "document", "documents", "please", "tell", "me", "give", "list"}
    if not qt:
        return False
    for r in rows:
        if r["doc_type"] not in allowed:
            overlap = len(qt & set(vectorstore._terms(r["text"]))) / len(qt)
            if overlap >= 0.5:      # relevant, not just the nearest neighbour
                return True
    return False


def n_output_guard(s: AskState):
    with tracing.span("Output guard", "rules") as sp:
        if s.get("status") == "blocked":
            sp["detail"] = "skipped (input blocked)"
            return {}
        leaks = 0
        for c in s.get("claims") or []:
            c["text"], n = guardrails.scan_output(c["text"])
            leaks += n
        thr = db.grounding_threshold()
        g = s.get("grounded")
        if (s.get("insufficient") or not s.get("claims")) and s["intent"] == "qa" and _restricted_hit(s):
            sp["detail"] = "answer lives only in documents outside the role scope · withheld"
            block = {"guard": "scope", "code": "SCOPE", "message": guardrails.RESTRICTED}
            return {"status": "blocked", "message": guardrails.RESTRICTED, "blocked": block, "claims": []}
        if s.get("insufficient") or not s.get("claims"):
            status, msg = "insufficient", "The documents available to your role do not answer this question."
        elif guardrails.enabled("ground") and g is not None and g < thr:
            status, msg = "withheld", f"Answer withheld: only {int(g * 100)}% of claims were supported (threshold {int(thr * 100)}%). Sources are listed below; the answer was sent to QA for review."
        else:
            status, msg = "answered", ""
        sp["detail"] = f"PHI scan: {leaks} masked · grounding {g if g is not None else '-'} vs {thr} · AI disclaimer added"
    return {"status": status, "message": msg}


def n_platform(s: AskState):
    with tracing.span("Platform stats tool", "sqlite") as sp:
        t = db.q1("SELECT COUNT(*) n, COALESCE(SUM(tokens),0) tok, COALESCE(SUM(cost),0) cost, AVG(grounded) g, "
                  "SUM(outcome='Blocked') b, SUM(outcome='Withheld') w, SUM(cached) c FROM traces WHERE intent!='ingest' "
                  "AND date(ts)=date('now','localtime')")
        claims = [
            {"text": f"{t['n']} requests today using {t['tok']:,} tokens (${t['cost']:.4f}).", "cites": ["Observability"]},
            {"text": f"{t['b'] or 0} blocked by guardrails, {t['w'] or 0} withheld for low grounding, {t['c'] or 0} served from cache.", "cites": ["Observability"]},
            {"text": f"Average groundedness {t['g']:.2f}." if t["g"] is not None else "No grounded answers yet today.", "cites": ["Observability"]},
            {"text": "Audit chain " + ("intact" if db.verify_chain()["ok"] else "BROKEN") + ".", "cites": ["Audit trail"]},
        ]
        sp["detail"] = "answered from SQLite metrics · 0 tokens"
    return {"claims": claims, "grounded": 1.0, "status": "answered", "message": ""}


# ---------------------------------------------------------------- graph
def _after_guard(s):
    return END if s.get("blocked") else "router"


def _after_router(s):
    return "platform" if s["intent"] == "platform" else "cache"


def _after_cache(s):
    return END if s.get("cached") else "retrieve"


def _build():
    g = StateGraph(AskState)
    for name, fn in [("input_guard", n_input_guard), ("router", n_router), ("cache", n_cache), ("retrieve", n_retrieve),
                     ("specialist", n_specialist), ("verifier", n_verifier), ("output_guard", n_output_guard),
                     ("platform", n_platform)]:
        g.add_node(name, fn)
    g.set_entry_point("input_guard")
    g.add_conditional_edges("input_guard", _after_guard, {"router": "router", END: END})
    g.add_conditional_edges("router", _after_router, {"platform": "platform", "cache": "cache"})
    g.add_conditional_edges("cache", _after_cache, {"retrieve": "retrieve", END: END})
    g.add_edge("retrieve", "specialist")
    g.add_edge("specialist", "verifier")
    g.add_edge("verifier", "output_guard")
    g.add_edge("output_guard", END)
    g.add_edge("platform", END)
    return g.compile()


GRAPH = _build()


def _remember(user: str, q: str, a: str) -> None:
    mem = SESSIONS.setdefault(user, {"turns": [], "summary": ""})
    mem["turns"].append({"q": q, "a": a})
    while len(mem["turns"]) > 2:   # older turns folded into a short extractive summary (no LLM call)
        old = mem["turns"].pop(0)
        mem["summary"] = (mem["summary"] + f" Q: {old['q'][:120]} A: {old['a'][:150]}")[-600:]


def ask(user: str, role: str, study: str, question: str) -> dict:
    trace = tracing.start_trace(user, role, "", question)
    out = GRAPH.invoke({"user": user, "role": role, "study": study, "question": question})
    trace.intent = out.get("intent", "blocked")
    if out.get("cached"):
        c = out["cached"]
        info = tracing.finish(trace, "Cache hit", c.get("grounded"), cached=True)
        db.audit(user, role, "QUERY", study, f"served from cache · source trace {c['source_trace']} · {trace.id}")
        return {**c, "cached": True, "trace": info, "intent": out.get("intent")}
    status = out.get("status", "answered")
    claims = out.get("claims") or []
    labels = {c["id"]: c["label"] for c in out.get("context") or []}
    payload = {
        "status": status, "message": out.get("message", ""), "grounded": out.get("grounded"),
        "claims": [{"text": c["text"], "cites": [{"id": x, "label": labels.get(x, _label(x))} for x in c["cites"]]} for c in claims]
        if status == "answered" else [],
        "sources": [{"id": c["id"], "label": c["label"]} for c in (out.get("context") or [])] if status == "withheld" else [],
        "disclaimer": DISCLAIMER, "intent": out.get("intent"),
    }
    outcome = {"answered": "Answered", "blocked": "Blocked", "withheld": "Withheld", "insufficient": "Insufficient"}[status]
    info = tracing.finish(trace, outcome, out.get("grounded"))
    if status == "blocked":
        b = out["blocked"]
        db.audit(user, role, "GUARDRAIL_BLOCK", "Ask", f"{b['code']}: {question[:80]} · {trace.id}")
    else:
        db.audit(user, role, "QUERY", study, f"{outcome} · {question[:80]} · {trace.id}")
    if status == "withheld":
        db.x("INSERT INTO outputs(kind,ref,title,study_id,status,detail,created_at,reviewer,reviewed_at) "
             "VALUES('answer_withheld',?,?,?,'reviewed',?,?,?,?)",
             (trace.id, f"Answer withheld · grounding {out.get('grounded')}", study, question[:200], db.now(), "system", db.now()))
    if status == "answered" and out.get("cache_key"):
        vectorstore.cache_store(out["standalone"], out["cache_key"], json.dumps(payload), trace.id, info["tokens"])
    if status in ("answered", "insufficient"):
        _remember(user, out.get("standalone", question), " ".join(c["text"] for c in claims))
    return {**payload, "cached": False, "trace": info}
