"""Role dashboards: KPIs, My Work (pending/completed), confidence scorecard, review-time metric.
Everything is computed from SQLite - no LLM calls."""
import json

from . import db
from .config import ASSISTED_MIN_PER_PAGE, DOC_TYPES, EXPECTED_DOCS, MANUAL_MIN_PER_PAGE, ROLES

SUMMARY_OWNER = {"PROTOCOL": "com", "AMENDMENT": "com", "REG_SUBMISSION": "com", "DSMB_CHARTER": "com",
                 "OTHER": "com", "ICF": "cra", "IB": "mr", "SAP": "mr"}


def studies() -> list[dict]:
    return db.q("SELECT study_id, MAX(phase) phase, SUM(is_current) docs FROM documents GROUP BY study_id ORDER BY study_id")


def default_study() -> str:
    s = studies()
    return s[0]["study_id"] if s else ""


def _docs(study: str, role: str, current_only=True) -> list[dict]:
    types = ROLES[role]["docs"] or list(DOC_TYPES)
    marks = ",".join("?" * len(types))
    cur = " AND is_current=1" if current_only else ""
    return db.q(f"SELECT * FROM documents WHERE study_id=? AND doc_type IN ({marks}){cur} ORDER BY doc_type, version",
                (study, *types))


def _findings(study: str, role: str) -> list[dict]:
    allowed = {d["code"] for d in _docs(study, role, current_only=False)}
    return [f for f in db.q("SELECT * FROM findings WHERE study_id=? ORDER BY id", (study,))
            if role in ("aud", "adm") or (f["doc_a"] in allowed and f["doc_b"] in allowed)]


def _phase(study: str) -> str:
    r = db.q1("SELECT phase FROM documents WHERE study_id=? AND phase!='' LIMIT 1", (study,))
    return r["phase"] if r else ""


def missing_docs(study: str) -> list[str]:
    expected = EXPECTED_DOCS.get(_phase(study) or "Phase III", EXPECTED_DOCS["Phase III"])
    present = {r["doc_type"] for r in db.q("SELECT doc_type FROM documents WHERE study_id=? AND is_current=1", (study,))}
    return [t for t in expected if t not in present]


def version_refs(study: str) -> list[dict]:
    """All explicit cross-references and whether they point to the current version."""
    docs = db.q("SELECT * FROM documents WHERE study_id=? AND is_current=1", (study,))
    cur = {d["doc_type"]: d for d in docs}
    out = []
    for d in docs:
        for r in json.loads(d["references_json"] or "[]"):
            t = cur.get(r.get("doc_type"))
            if not t or t["id"] == d["id"]:
                continue
            rv = str(r.get("version", "")).lstrip("vV ")
            ok = rv.replace(".0", "") == t["version"].replace(".0", "")
            out.append({"from": d["code"], "from_title": DOC_TYPES[d["doc_type"]], "to_type": DOC_TYPES[t["doc_type"]],
                        "ref_version": rv, "current_version": t["version"], "ok": ok})
    return out


def scorecard(study: str, role: str) -> dict:
    docs = _docs(study, role)
    expected = EXPECTED_DOCS.get(_phase(study) or "Phase III", EXPECTED_DOCS["Phase III"])
    miss = missing_docs(study)
    rows = []
    present = len(expected) - len(miss)
    rows.append(("Document completeness", present / len(expected),
                 f"{present} of {len(expected)} expected documents present" + (f" · missing {', '.join(DOC_TYPES[m] for m in miss)}" if miss else "")))
    refs = version_refs(study)
    bad = [r for r in refs if not r["ok"]]
    rows.append(("Version consistency", (len(refs) - len(bad)) / len(refs) if refs else 1.0,
                 (f"{bad[0]['from']} references {bad[0]['to_type']} v{bad[0]['ref_version']}; current is v{bad[0]['current_version']}"
                  + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else "")) if bad else
                 (f"All {len(refs)} cross-references point to current versions" if refs else "No cross-references detected")))
    fs = _findings(study, role)
    open_n = sum(1 for f in fs if f["status"] in ("open", "raised"))
    compared = max(db.get_setting(f"compared:{study}", 0) or 0, len(fs), 1)
    rows.append(("Cross-document consistency", 1 - open_n / compared,
                 f"{open_n} open conflicts out of {compared} fact comparisons"))
    tot = sum(d["claims_total"] or 0 for d in docs)
    sup = sum(d["claims_supported"] or 0 for d in docs)
    rows.append(("Evidence coverage", sup / tot if tot else 0.0, f"{sup} of {tot} AI claims verified against their cited source"))
    if role == "aud":
        outs = db.q("SELECT status FROM outputs WHERE study_id=?", (study,))
        done = sum(1 for o in outs if o["status"] in ("e_signed", "rejected"))
        rows.append(("Review status", done / len(outs) if outs else 0.0, f"{done} of {len(outs)} AI outputs QA-signed or rejected"))
    else:
        mine = [f for f in fs if role == "adm" or f["owner_role"] == role]
        done = sum(1 for f in mine if f["status"] not in ("open",))
        rows.append(("Review status", done / len(mine) if mine else 1.0,
                     f"{done} of {len(mine)} findings for your role reviewed by a human"))
    if not docs:
        return {"overall": None, "rows": [{"name": n, "value": None, "finding": "No documents ingested yet"} for n, _, _ in rows]}
    out = [{"name": n, "value": round(v * 100), "finding": t} for n, v, t in rows]
    return {"overall": round(sum(r["value"] for r in out) / len(out)), "rows": out}


def review_time(study: str, role: str) -> dict:
    docs = _docs(study, role)
    pages = sum(d["pages"] or 0 for d in docs)
    ai_min = sum((d["processing_ms"] or 0) for d in docs) / 60000
    manual = pages * MANUAL_MIN_PER_PAGE / 60
    assisted = (pages * ASSISTED_MIN_PER_PAGE + ai_min) / 60
    return {"pages": pages, "manual_h": round(manual, 1), "assisted_h": round(assisted, 1),
            "saved_pct": round((1 - assisted / manual) * 100) if manual else 0,
            "basis": f"Estimate: {MANUAL_MIN_PER_PAGE:g} min/page manual vs {ASSISTED_MIN_PER_PAGE:g} min/page reviewing cited summaries + measured AI processing time"}


def _short(ts: str) -> str:
    return (ts or "")[:16].replace("T", " ")


def my_work(study: str, role: str, user: str) -> dict:
    pend = []
    if role in ("com", "cra", "mr"):
        for o in db.q("SELECT o.*, d.doc_type FROM outputs o JOIN documents d ON CAST(o.ref AS INTEGER)=d.id "
                      "WHERE o.kind='summary' AND o.status='draft' AND o.study_id=? AND d.is_current=1", (study,)):
            if SUMMARY_OWNER.get(o["doc_type"]) == role:
                pend.append({"p": "Medium", "t": f"Approve {o['title']}", "sub": o["detail"], "btn": "Review",
                             "link": {"view": "docs", "id": int(o["ref"])}})
        for f in _findings(study, role):
            if f["owner_role"] == role and f["status"] == "open":
                pend.append({"p": f["severity"] if f["severity"] != "Low" else "Medium",
                             "t": f"{f['id']} · {f['item']}: {f['doc_a']} vs {f['doc_b']}",
                             "sub": f"{f['value_a']} vs {f['value_b']}"[:110], "btn": "Open", "link": {"view": "disc", "id": f["id"]}})
        if role == "com":
            for m in missing_docs(study):
                pend.append({"p": "Medium", "t": f"Expected document missing: {DOC_TYPES[m]}", "sub": "Request from owner",
                             "btn": "Open", "link": {"view": "ver"}})
    elif role == "aud":
        for o in db.q("SELECT * FROM outputs WHERE study_id=? AND status='reviewed' ORDER BY id", (study,)):
            trail = "AI ✓ · Reviewer ✓ · QA review pending · e-sign —" if o["kind"] != "answer_withheld" else "Below grounding threshold · QA assessment needed"
            pend.append({"p": "GxP", "t": o["title"], "sub": trail, "btn": "Review & sign", "link": {"view": "signoff", "id": o["id"]}})
        for f in db.q("SELECT * FROM findings WHERE study_id=? AND topic='version_reference' AND status IN ('open','raised')", (study,)):
            pend.append({"p": "High", "t": f"{f['value_a']} in {f['doc_a']} ({f['value_b']})", "sub": "Superseded version still referenced · CAPA needed",
                         "btn": "Open", "link": {"view": "disc", "id": f["id"]}})
        drafts = db.q1("SELECT COUNT(*) n FROM outputs WHERE study_id=? AND status='draft'", (study,))["n"]
        if drafts:
            pend.append({"p": "Medium", "t": f"{drafts} AI outputs still waiting for a reviewer", "sub": "Not yet eligible for QA sign-off",
                         "btn": "Open", "link": {"view": "signoff"}})
    else:
        t = db.q1("SELECT SUM(outcome='Blocked') b, SUM(outcome='Withheld') w FROM traces WHERE date(ts)=date('now','localtime')")
        if t["b"]:
            pend.append({"p": "High", "t": f"Investigate {t['b']} guardrail blocks today", "sub": "Admin console · Observability",
                         "btn": "Investigate", "link": {"view": "admin", "tab": "obs"}})
        if t["w"]:
            pend.append({"p": "Medium", "t": f"Review {t['w']} answers withheld for low grounding", "sub": "Agent trace",
                         "btn": "Review", "link": {"view": "admin", "tab": "trace"}})
        pend.append({"p": "Medium", "t": "Re-verify the audit hash chain", "sub": "Recommended daily", "btn": "Verify",
                     "link": {"view": "admin", "tab": "audit"}})
    order = {"GxP": 0, "High": 1, "Medium": 2, "Low": 3}
    pend.sort(key=lambda x: order.get(x["p"], 3))
    done_actions = ("SUMMARY_APPROVE", "SUMMARY_FLAG", "FINDING_RAISE", "FINDING_VALIDATE", "FINDING_DISMISS", "E_SIGN",
                    "QA_REJECT", "GUARDRAIL_CONFIG", "AUDIT_VERIFY", "CONSISTENCY_RUN", "DOC_INGEST")
    marks = ",".join("?" * len(done_actions))
    comp = [{"p": "Done", "t": f"{a['action'].replace('_', ' ').title()} · {a['object']}", "sub": f"{_short(a['ts'])} · audit {a['hash'][:4]}…{a['hash'][-2:]}",
             "btn": "View", "link": {"view": "audit" if role in ("aud", "adm") else "dash"}}
            for a in db.q(f"SELECT * FROM audit WHERE user=? AND action IN ({marks}) ORDER BY id DESC LIMIT 6", (user, *done_actions))]
    return {"pending": pend[:8], "completed": comp}


def kpis(study: str, role: str) -> list[dict]:
    fs = _findings(study, role)
    open_f = [f for f in fs if f["status"] in ("open", "raised")]
    docs = _docs(study, role)
    drafts = sum(1 for o in db.q("SELECT o.status, d.doc_type FROM outputs o JOIN documents d ON CAST(o.ref AS INTEGER)=d.id "
                                 "WHERE o.kind='summary' AND o.status='draft' AND o.study_id=?", (study,))
                 if SUMMARY_OWNER.get(o["doc_type"]) == role)
    if role in ("com", "cra", "mr"):
        mine = [f for f in open_f if f["owner_role"] == role]
        sup = db.q1("SELECT COUNT(*) n FROM documents WHERE study_id=? AND is_current=0", (study,))["n"]
        first = {"com": {"label": "Current documents", "value": len(docs), "note": f"{sup} superseded versions on file"},
                 "cra": {"label": "Site-level findings", "value": len(mine), "note": "consent, eligibility, procedures"},
                 "mr": {"label": "Safety & endpoint items", "value": len(mine), "note": "dosing, endpoints, AESIs"}}[role]
        return [first,
                {"label": "Open discrepancies", "value": len(open_f), "note": f"{sum(1 for f in open_f if f['severity'] == 'High')} high severity"},
                {"label": "Summaries to approve", "value": drafts, "note": "AI drafts awaiting your review"}]
    if role == "aud":
        o = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM outputs WHERE study_id=? GROUP BY status", (study,))}
        vr = sum(1 for r in version_refs(study) if not r["ok"])
        return [{"label": "Awaiting QA sign-off", "value": o.get("reviewed", 0), "note": "GxP human-in-the-loop"},
                {"label": "E-signed records", "value": o.get("e_signed", 0), "note": "21 CFR Part 11 style e-signature"},
                {"label": "Superseded refs", "value": vr, "note": "documents citing old versions"},
                {"label": "Rejected AI outputs", "value": o.get("rejected", 0), "note": "returned for regeneration"}]
    t = db.q1("SELECT COUNT(*) n, SUM(outcome='Blocked') b, AVG(grounded) g, COALESCE(SUM(tokens),0) tok FROM traces "
              "WHERE date(ts)=date('now','localtime')")
    saved = db.q1("SELECT COALESCE(SUM(tokens),0) s FROM savings")["s"]
    used = db.q1("SELECT COALESCE(SUM(tokens),0) s FROM traces")["s"]
    return [{"label": "Requests today", "value": t["n"], "note": f"{t['tok']:,} tokens"},
            {"label": "Guardrail blocks", "value": t["b"] or 0, "note": "today"},
            {"label": "Avg groundedness", "value": f"{t['g']:.2f}" if t["g"] is not None else "—", "note": f"threshold {db.grounding_threshold():.2f}"},
            {"label": "Tokens saved", "value": f"{round(saved / (saved + used) * 100) if saved + used else 0}%", "note": "cache, digest reuse, compression"}]


def panels(study: str, role: str) -> dict:
    fs = _findings(study, role)
    out = {}
    by_status = {}
    for f in fs:
        by_status[f["status"]] = by_status.get(f["status"], 0) + 1
    out["findings_by_status"] = [{"label": k.title(), "n": by_status.get(k, 0)} for k in ("open", "raised", "validated", "dismissed", "resolved")]
    docs = db.q("SELECT doc_type, COUNT(*) n FROM documents WHERE study_id=? AND is_current=1 GROUP BY doc_type", (study,))
    out["docs_by_type"] = [{"label": DOC_TYPES[d["doc_type"]], "n": d["n"]} for d in docs]
    topics = {}
    for f in fs:
        if f["status"] in ("open", "raised") and (role in ("aud", "adm") or f["owner_role"] == role):
            topics[f["topic"]] = topics.get(f["topic"], 0) + 1
    out["my_topics"] = [{"label": k.replace("_", " ").capitalize(), "n": v} for k, v in sorted(topics.items(), key=lambda x: -x[1])]
    if role == "aud":
        o = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM outputs WHERE study_id=? GROUP BY status", (study,))}
        out["lifecycle"] = [{"label": "AI draft", "n": o.get("draft", 0)}, {"label": "Reviewer approved", "n": o.get("reviewed", 0)},
                            {"label": "E-signed record", "n": o.get("e_signed", 0)}, {"label": "Rejected", "n": o.get("rejected", 0)}]
        out["version_table"] = [{"doc": DOC_TYPES[d["doc_type"]], "version": d["version"], "date": d["effective_date"] or d["ingested_at"][:10],
                                 "status": "Active" if d["is_current"] else "Superseded"}
                                for d in db.q("SELECT * FROM documents WHERE study_id=? ORDER BY doc_type, version DESC", (study,))]
        f = db.q1("SELECT * FROM findings WHERE study_id=? AND decided_by IS NOT NULL ORDER BY decided_at DESC LIMIT 1", (study,)) or \
            db.q1("SELECT * FROM findings WHERE study_id=? ORDER BY id DESC LIMIT 1", (study,))
        if f:
            a = db.q1("SELECT hash FROM audit WHERE object=? ORDER BY id DESC LIMIT 1", (f["id"],))
            out["trace"] = {"finding": f["id"], "source": f["cite_a"], "agent": f["trace_id"],
                            "decision": f"{f['decision'] or 'pending'}" + (f" by {f['decided_by']}" if f["decided_by"] else ""),
                            "audit": (a["hash"][:4] + "…" + a["hash"][-2:]) if a else "—"}
        out["superseded_refs"] = [r for r in version_refs(study) if not r["ok"]]
    return out


def dashboard(study: str, role: str, user: str) -> dict:
    return {"study": study, "phase": _phase(study), "kpis": kpis(study, role), "work": my_work(study, role, user),
            "scorecard": scorecard(study, role), "review_time": review_time(study, role), "panels": panels(study, role)}
