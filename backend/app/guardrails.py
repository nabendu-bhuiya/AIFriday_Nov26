"""Guardrails at four points: input, retrieval scope, output, and per-request token budget.

All checks here are rules (zero tokens). Each can be switched off by the Admin (audited).
"""
import re

from . import db
from .config import ROLES
from .deid import deidentify

RESTRICTED = "This information cannot be shared."

GUARDS = [
    ("phi", "PHI / PII redaction", "Input", "Masks names, dates of birth, MRNs and contacts before any LLM call or indexing (HIPAA)."),
    ("phi_req", "Patient-identity request block", "Input", "Blocks questions asking who a patient or subject is."),
    ("inj", "Prompt-injection detection", "Input", "Blocks instructions hidden in questions (ignore previous instructions, reveal prompt...)."),
    ("topic", "Topic boundary", "Input", "Declines personal medical advice and requests unrelated to the trial documents."),
    ("scope", "Role scope enforcement", "Retrieval", "Questions and retrieval are limited to document types allowed for the user's role."),
    ("ground", "Grounding threshold", "Output", "Answers whose verified-claim ratio is below the threshold are withheld and sent to QA."),
    ("cite", "Citation required", "Output", "Every claim must cite a retrieved chunk; uncited or unsupported claims are dropped."),
    ("leak", "Output PHI scan", "Output", "Second de-identification pass on the answer before it reaches the user."),
    ("budget", "Token budget per request", "Cost", "Caps context size and output tokens per request."),
]

PHI_REQ = [
    r"\b(names?|identit(?:y|ies)|address(?:es)?|phone( numbers?)?|contact details|dates? of birth|dob|mrn|medical record|ssn|social security)\b.{0,40}\b(patients?|subjects?|participants?)\b",
    r"\b(patients?|subjects?|participants?)\b.{0,40}\b(names?|address(?:es)?|phone( numbers?)?|dates? of birth|dob|mrn)\b",
    r"\bwho (?:is|are|was|were) (?:the )?(?:patients?|subjects?|participants?)\b",
    r"\bidentify (?:the |this |that )?(?:patients?|subjects?|participants?)\b",
    r"\b(?:patients?|subjects?|participants?)['’]?s?\s+(?:ids?|pids?|identifiers?|details|records?|contact|personal)\b",
    r"\b(?:pids?|uhid|mrns?|aadhaa?r|personal (?:details|information|data)|contact details)\b",
]
INJECTION = [
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)",
    r"disregard (?:the |all |your )?(?:system|previous|prior) ",
    r"(?:reveal|show|print|repeat) (?:me )?(?:your |the )?(?:system prompt|hidden instructions|instructions)",
    r"\byou are now\b", r"\bjailbreak\b", r"\bdeveloper mode\b", r"\bDAN\b",
    r"bypass (?:the )?(?:guardrails?|filters?|safety|restrictions)",
]
TOPIC = [
    r"\bshould i (?:take|stop|start|increase|reduce)\b", r"\b(?:my|me) (?:dose|medication|symptoms?|treatment)\b",
    r"\b(?:diagnose|prescribe) me\b", r"\b(?:weather|stock price|cricket|football|movie|recipe|joke)\b",
]
SCOPE_KEYWORDS = {
    "IB": r"investigator'?s brochure|\bIB\b",
    "SAP": r"statistical analysis plan|\bSAP\b",
    "REG_SUBMISSION": r"regulatory submission|\bIND\b|\bCTA\b|\bsubmission\b",
    "DSMB_CHARTER": r"\bDSMB\b|data safety monitoring",
}


def enabled(gid: str) -> bool:
    return not db.get_setting("guard_off", {}).get(gid, False)


def set_enabled(gid: str, on: bool) -> None:
    off = db.get_setting("guard_off", {})
    off[gid] = not on
    db.set_setting("guard_off", off)


def _any(patterns, text) -> str | None:
    for p in patterns:
        if re.search(p, text, re.I if p != r"\bDAN\b" else 0):
            return p
    return None


def check_input(question: str, role: str) -> dict | None:
    """Return a block dict or None if the question may proceed."""
    if enabled("inj") and _any(INJECTION, question):
        return {"guard": "inj", "code": "INJECTION",
                "message": "Blocked by guardrail (prompt injection). Ask a question about the trial documents."}
    if enabled("phi_req") and _any(PHI_REQ, question):
        return {"guard": "phi_req", "code": "PHI",
                "message": RESTRICTED}
    if enabled("topic") and _any(TOPIC, question):
        return {"guard": "topic", "code": "TOPIC",
                "message": "Outside scope. TrialLens answers questions about the trial documents only, not personal medical advice."}
    if enabled("scope") and role != "adm":
        allowed = ROLES[role]["docs"]
        for dtype, rx in SCOPE_KEYWORDS.items():
            if dtype not in allowed and re.search(rx, question, re.I):
                return {"guard": "scope", "code": "SCOPE",
                        "message": RESTRICTED}
    return None


def scan_output(text: str) -> tuple[str, int]:
    if not enabled("leak"):
        return text, 0
    clean, counts = deidentify(text)
    return clean, sum(counts.values())
