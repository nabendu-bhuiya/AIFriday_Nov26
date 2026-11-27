"""Central configuration: paths, models, roles, document types."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("TRIALLENS_DATA_DIR") or ROOT / "data")
REPO_DIR = DATA_DIR / "repository"          # mock document-management system
DB_PATH = DATA_DIR / "triallens.db"
CHROMA_DIR = DATA_DIR / "chroma"
for _d in (DATA_DIR, REPO_DIR, CHROMA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---- LLM ------------------------------------------------------------------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
MODEL_FAST = os.getenv("LLM_MODEL_FAST", "azure/genailab-maas-gpt-4.1-mini").strip()
MODEL_JUDGE = os.getenv("LLM_MODEL_JUDGE", "azure/genailab-maas-gpt-4.1").strip()
# system = use Windows certificate store (corporate proxy), default = certifi, off = no verification
SSL_MODE = os.getenv("SSL_MODE", "system").strip().lower()

# USD per 1M tokens: (input, output, cached input) - indicative list prices
PRICES = {
    "gpt-4.1-mini": (0.40, 1.60, 0.10),
    "gpt-4.1-nano": (0.10, 0.40, 0.025),
    "gpt-4.1": (2.00, 8.00, 0.50),
}

PROMPT_VERSION = "p1"
TOP_K = 6
CANDIDATES = 20
TOKEN_BUDGET = 8000            # per request, context + output
ANSWER_CACHE_SIMILARITY = 0.92
DEFAULT_GROUNDING_THRESHOLD = 0.80
MANUAL_MIN_PER_PAGE = float(os.getenv("MANUAL_MIN_PER_PAGE", "4"))   # baseline manual review effort
ASSISTED_MIN_PER_PAGE = float(os.getenv("ASSISTED_MIN_PER_PAGE", "0.5"))

# ---- Domain ---------------------------------------------------------------
DOC_TYPES = {
    "PROTOCOL": "Clinical Protocol",
    "AMENDMENT": "Protocol Amendment",
    "ICF": "Informed Consent Form",
    "IB": "Investigator's Brochure",
    "SAP": "Statistical Analysis Plan",
    "REG_SUBMISSION": "Regulatory Submission",
    "DSMB_CHARTER": "DSMB Charter",
    "OTHER": "Other document",
}
DOC_CODES = {"PROTOCOL": "PROT", "AMENDMENT": "AMD", "ICF": "ICF", "IB": "IB", "SAP": "SAP",
             "REG_SUBMISSION": "REG", "DSMB_CHARTER": "DSMB", "OTHER": "DOC"}

EXPECTED_DOCS = {
    "Phase I": ["PROTOCOL", "ICF", "IB"],
    "Phase II": ["PROTOCOL", "ICF", "IB", "SAP", "REG_SUBMISSION"],
    "Phase III": ["PROTOCOL", "ICF", "IB", "SAP", "REG_SUBMISSION", "DSMB_CHARTER"],
}

ALL_DOCS = list(DOC_TYPES)
ROLES = {
    "com": {"name": "Clinical Operations Manager", "short": "Clin Ops",
            "docs": ["PROTOCOL", "AMENDMENT", "ICF", "SAP", "REG_SUBMISSION", "DSMB_CHARTER", "OTHER"],
            "lens": "Operations lens: visit schedule, enrollment targets, site execution, amendments, timelines and protocol requirements."},
    "cra": {"name": "Clinical Research Associate", "short": "CRA",
            "docs": ["PROTOCOL", "AMENDMENT", "ICF", "OTHER"],
            "lens": "Site monitoring lens: eligibility checks, consent and re-consent, site procedures per visit and site-level discrepancies."},
    "mr": {"name": "Medical Reviewer", "short": "Medical",
           "docs": ["PROTOCOL", "AMENDMENT", "ICF", "IB", "SAP", "DSMB_CHARTER", "OTHER"],
           "lens": "Medical lens: endpoints, dosing and titration, safety, adverse events of special interest and stopping rules."},
    "aud": {"name": "QA Auditor", "short": "Auditor", "docs": ALL_DOCS,
            "lens": "Quality lens: version control, cross-references between documents, GxP-relevant commitments and traceability."},
    "adm": {"name": "AI Platform Admin", "short": "Admin", "docs": ALL_DOCS,
            "lens": "Platform view: executive summary and key sections (read-only)."},
}
LENS_ROLES = ["com", "cra", "mr", "aud"]

USERS = {
    "priya.sharma@pharma-demo.com": {"name": "Priya Sharma", "role": "com"},
    "rahul.das@pharma-demo.com": {"name": "Rahul Das", "role": "cra"},
    "anita.rao@pharma-demo.com": {"name": "Dr. Anita Rao", "role": "mr"},
    "meera.iyer@pharma-demo.com": {"name": "Meera Iyer", "role": "aud"},
    "admin@pharma-demo.com": {"name": "Platform Admin", "role": "adm"},
}
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "")  # empty = any non-empty password accepted (POC)

FACT_TOPICS = [
    "visit_schedule", "screening_window", "treatment_duration", "dose_and_titration",
    "primary_endpoint", "secondary_endpoints", "sample_size", "key_inclusion", "key_exclusion",
    "risks_and_aesi", "stopping_rules", "procedures_by_visit", "contraception",
    "reconsent_requirement", "study_phase", "other_commitment",
]
