"""Lightweight AI observability: one trace per request, one span per agent step.

Spans capture model, tokens (incl. provider-side cached tokens), latency, cost and a detail line.
Everything is written to SQLite so the Admin console can roll it up.
"""
import contextvars
import time
import uuid
from contextlib import contextmanager

from . import db
from .config import PRICES

_current = contextvars.ContextVar("trace", default=None)


def price(model: str, tin: int, tout: int, cached: int) -> float:
    m = model.lower()
    for key in sorted(PRICES, key=len, reverse=True):
        if key in m:
            pin, pout, pcache = PRICES[key]
            return ((tin - cached) * pin + cached * pcache + tout * pout) / 1_000_000
    return 0.0


class Trace:
    def __init__(self, user: str, role: str, intent: str = "", question: str = ""):
        self.id = "tr_" + uuid.uuid4().hex[:6]
        self.user, self.role, self.intent, self.question = user, role, intent, question
        self.spans: list[dict] = []
        self.stack: list[dict] = []
        self.t0 = time.perf_counter()
        self.savings: list[tuple[str, int]] = []


def start_trace(user: str, role: str, intent: str = "", question: str = "") -> Trace:
    t = Trace(user, role, intent, question)
    _current.set(t)
    return t


def current() -> Trace | None:
    return _current.get()


@contextmanager
def span(name: str, model: str = "", detail: str = ""):
    t = current()
    s = {"name": name, "model": model, "tokens_in": 0, "tokens_out": 0, "cached_tokens": 0,
         "latency_ms": 0, "cost": 0.0, "detail": detail, "status": "ok"}
    t0 = time.perf_counter()
    if t:
        t.stack.append(s)
    try:
        yield s
    except Exception as e:
        s["status"] = "error"
        s["detail"] = (s["detail"] + " | " if s["detail"] else "") + f"error: {e}"[:300]
        raise
    finally:
        s["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        if t:
            t.stack.pop()
            t.spans.append(s)


def record_llm(model: str, tin: int, tout: int, cached: int) -> None:
    """Attach LLM usage to the innermost open span."""
    t = current()
    if not t or not t.stack:
        return
    s = t.stack[-1]
    s["model"] = s["model"] or model
    s["tokens_in"] += tin
    s["tokens_out"] += tout
    s["cached_tokens"] += cached
    s["cost"] += price(model, tin, tout, cached)


def add_saving(reason: str, tokens: int) -> None:
    t = current()
    if t and tokens > 0:
        t.savings.append((reason, int(tokens)))


def finish(t: Trace, outcome: str, grounded: float | None = None, cached: bool = False) -> dict:
    tokens = sum(s["tokens_in"] + s["tokens_out"] for s in t.spans)
    cost = sum(s["cost"] for s in t.spans)
    latency = int((time.perf_counter() - t.t0) * 1000)
    db.x("INSERT INTO traces(id,ts,user,role,intent,question,tokens,cost,latency_ms,grounded,outcome,cached) "
         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
         (t.id, db.now(), t.user, t.role, t.intent, t.question[:300], tokens, cost, latency, grounded, outcome,
          1 if cached else 0))
    for i, s in enumerate(t.spans):
        db.x("INSERT INTO spans(trace_id,seq,name,model,tokens_in,tokens_out,cached_tokens,latency_ms,cost,detail,status) "
             "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
             (t.id, i, s["name"], s["model"], s["tokens_in"], s["tokens_out"], s["cached_tokens"], s["latency_ms"],
              s["cost"], s["detail"][:500], s["status"]))
    for reason, tok in t.savings:
        db.x("INSERT INTO savings(ts,trace_id,reason,tokens) VALUES(?,?,?,?)", (db.now(), t.id, reason, tok))
    return {"trace_id": t.id, "tokens": tokens, "cost": round(cost, 5), "latency_ms": latency}
