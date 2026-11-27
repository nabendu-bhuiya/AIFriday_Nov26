"""HIPAA gate: rule-based de-identification that runs before any text reaches the LLM or the vector store.

Labels are matched case-insensitively ("Patient name", "PATIENT NAME", "patient Name").
For labelled identity fields the whole value up to the end of the line is masked, so names in any
casing or format ("priya sharma", "SHARMA, Priya") are caught.
"""
import re
from collections import Counter

_SEP = r"\s*[:=#\-–]\s*"
_PERSON = r"(?:patient|subject|participant|volunteer|full|first|last|given|family|middle|guardian|parent|witness|next of kin|emergency contact|LAR|legally authori[sz]ed representative)"
_NAME = r"[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][A-Za-z'-]+){0,2}"
_ID_LABEL = (r"(?:PID|P\.I\.D\.?|patient[\s_-]*(?:id|identifier|no\.?|number|#)|MRN|medical[\s_-]*record[\s_-]*(?:no\.?|number|#)?"
             r"|UHID|hospital[\s_-]*(?:id|no\.?|number)|health[\s_-]*(?:card|insurance)[\s_-]*(?:no\.?|number)?|insurance[\s_-]*(?:id|no\.?|number)"
             r"|NHS[\s_-]*(?:no\.?|number)|aadhaa?r(?:[\s_-]*(?:no\.?|number))?|PAN(?:[\s_-]*(?:no\.?|number))|SSN|social[\s_-]*security[\s_-]*(?:no\.?|number)"
             r"|passport[\s_-]*(?:no\.?|number)?|driver'?s?[\s_-]*licen[cs]e[\s_-]*(?:no\.?|number)?)")

PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
    # labelled identifiers: PID, patient ID, MRN, UHID, insurance, Aadhaar, passport ...
    ("ID", re.compile(rf"\b{_ID_LABEL}(?:{_SEP}|\s+)(?=[A-Z0-9/-]*\d)[A-Z0-9][A-Z0-9/-]{{2,}}", re.I)),
    ("DOB", re.compile(rf"\b(?:DOB|D\.O\.B\.?|date[\s_-]*of[\s_-]*birth|birth[\s_-]*date)(?:{_SEP}|\s+)[^\n,;]{{4,30}}", re.I)),
    # labelled person names: "Patient name: ...", "Name of subject - ...", "Name: ..." at line start
    ("NAME", re.compile(rf"\b{_PERSON}(?:'s)?[\s_-]*name{_SEP}[^\n;|]{{2,60}}", re.I)),
    ("NAME", re.compile(rf"\bname[\s_-]*of[\s_-]*(?:the[\s_-]*)?{_PERSON}{_SEP}[^\n;|]{{2,60}}", re.I)),
    ("NAME", re.compile(r"(?im)^\s*name\s*[:=]\s*[^\n;|]{2,60}")),
    ("NAME", re.compile(rf"\b(?:Mr|Mrs|Ms|Miss)\.?\s+{_NAME}")),
    ("PHONE", re.compile(r"(?<![\w-])(?:\+?\d{1,3}[\s.-])?\(?\d{3,5}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w-])")),
    ("PHONE", re.compile(rf"\b(?:phone|mobile|cell|tel|telephone|contact[\s_-]*(?:no\.?|number)){_SEP}?\+?[\d\s().-]{{7,18}}\d", re.I)),
    ("ADDRESS", re.compile(rf"\b(?:home[\s_-]*|residential[\s_-]*|postal[\s_-]*)?address{_SEP}[^\n]{{6,100}}", re.I)),
]


def deidentify(text: str) -> tuple[str, Counter]:
    counts: Counter = Counter()
    for label, rx in PATTERNS:
        def _sub(m, label=label):
            counts[label] += 1
            return f"[REDACTED-{label}]"
        text = rx.sub(_sub, text)
    return text, counts
