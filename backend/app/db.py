"""SQLite storage: documents, chunks, findings, HITL outputs, traces, hash-chained audit trail."""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime

from .config import DB_PATH, DEFAULT_GROUNDING_THRESHOLD

_lock = threading.RLock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT, file_hash TEXT UNIQUE,
  study_id TEXT, phase TEXT, doc_type TEXT, title TEXT, version TEXT, effective_date TEXT,
  code TEXT, pages INTEGER, chars INTEGER, is_current INTEGER DEFAULT 1, redactions INTEGER DEFAULT 0,
  redaction_detail TEXT, references_json TEXT, digest_json TEXT, facts_json TEXT, prompt_version TEXT,
  claims_total INTEGER DEFAULT 0, claims_supported INTEGER DEFAULT 0,
  ingested_at TEXT, ingested_by TEXT, processing_ms INTEGER);
CREATE TABLE IF NOT EXISTS chunks(chunk_id TEXT PRIMARY KEY, doc_id INTEGER, page INTEGER, section TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, file_name TEXT, status TEXT, steps_json TEXT,
  doc_id INTEGER, error TEXT, created_at TEXT, user TEXT);
CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY, study_id TEXT, dedup_key TEXT UNIQUE, topic TEXT, item TEXT,
  doc_a TEXT, value_a TEXT, cite_a TEXT, doc_b TEXT, value_b TEXT, cite_b TEXT, severity TEXT, owner_role TEXT,
  rationale TEXT, source TEXT, status TEXT, trace_id TEXT, created_at TEXT,
  decided_by TEXT, decided_at TEXT, decision TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS outputs(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref TEXT, title TEXT, study_id TEXT,
  status TEXT, detail TEXT, created_at TEXT, reviewer TEXT, reviewed_at TEXT, qa_user TEXT, qa_at TEXT,
  sign_meaning TEXT, audit_hash TEXT);
CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY, ts TEXT, user TEXT, role TEXT, intent TEXT, question TEXT,
  tokens INTEGER, cost REAL, latency_ms INTEGER, grounded REAL, outcome TEXT, cached INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS spans(id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, seq INTEGER, name TEXT, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cached_tokens INTEGER, latency_ms INTEGER, cost REAL, detail TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS savings(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, trace_id TEXT, reason TEXT, tokens INTEGER);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, role TEXT, action TEXT,
  object TEXT, detail TEXT, prev_hash TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

with _lock:
    _conn.executescript(SCHEMA)
    _conn.commit()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def q(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def q1(sql: str, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def x(sql: str, args=()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def get_setting(key: str, default=None):
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def set_setting(key: str, value) -> None:
    x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, json.dumps(value)))


def grounding_threshold() -> float:
    return float(get_setting("grounding_threshold", DEFAULT_GROUNDING_THRESHOLD))


# ---- Hash-chained audit trail (tamper evident, 21 CFR Part 11 spirit) ------
def _entry_hash(prev: str, ts, user, role, action, obj, detail) -> str:
    payload = json.dumps([prev, ts, user, role, action, obj, detail], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def audit(user: str, role: str, action: str, obj: str = "", detail: str = "") -> str:
    with _lock:
        last = _conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else "GENESIS"
        ts = now()
        h = _entry_hash(prev, ts, user, role, action, obj, detail)
        _conn.execute("INSERT INTO audit(ts,user,role,action,object,detail,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?)",
                      (ts, user, role, action, obj, detail, prev, h))
        _conn.commit()
        return h


def verify_chain() -> dict:
    rows = q("SELECT * FROM audit ORDER BY id")
    prev = "GENESIS"
    for r in rows:
        if r["prev_hash"] != prev or _entry_hash(prev, r["ts"], r["user"], r["role"], r["action"],
                                                  r["object"], r["detail"]) != r["hash"]:
            return {"ok": False, "entries": len(rows), "broken_at": r["id"]}
        prev = r["hash"]
    return {"ok": True, "entries": len(rows), "broken_at": None}
