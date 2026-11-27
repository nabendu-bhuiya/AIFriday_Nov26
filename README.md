# TrialLens: Agentic Clinical Trial Document Assistant (POC)

*Every answer cited. Every inconsistency caught.*

A proof of concept for the "AI Assistant for Life Sciences Clinical Trial Document Summarization" problem statement.
It runs entirely on one laptop: React UI, FastAPI backend, LangGraph agents, local ChromaDB, local SQLite.
It uses pretrained LLM APIs only, with no training or fine-tuning.

## Run it

1. Copy `.env.example` to `.env`, then set `LLM_BASE_URL` and `LLM_API_KEY` (the TCS GenAI lab endpoint).
2. Put the trial documents (PDF, DOCX, TXT or MD) in `data/repository/`.
3. Run `./run.ps1`, or start the two parts by hand:
   - `cd backend; python -m uvicorn app.main:app --port 8000`
   - `cd frontend; npm install; npm run dev`, then open http://localhost:5173
4. Sign in as `priya.sharma@pharma-demo.com` (any password). Open **Ingestion**, click **Sync repository**, and watch the agent steps.

To check the LLM connection, sign in as `admin@pharma-demo.com` and open **Admin console**, then **Test LLM connection**.

### Demo accounts (any password)

| Email | Role |
|---|---|
| priya.sharma@pharma-demo.com | Clinical Operations Manager (can also ingest documents) |
| rahul.das@pharma-demo.com | Clinical Research Associate |
| anita.rao@pharma-demo.com | Medical Reviewer |
| meera.iyer@pharma-demo.com | QA Auditor (GxP sign-off, audit trail) |
| admin@pharma-demo.com | AI Platform Admin (observability, guardrails; read-only executive summaries) |

## Architecture

```
React (Vite) ── /api ──> FastAPI
                          ├─ Ingestion agent (LangGraph)
                          │    parse → detect metadata (mini) → HIPAA de-identification (rules)
                          │    → section chunking + ChromaDB index → digest (1 mini call: executive summary,
                          │    4 role lenses, facts) → verifier (mini) → consistency judge (gpt-4.1)
                          ├─ Ask agent (LangGraph)
                          │    input guard (rules) → router (rules; mini only to rewrite follow-up questions)
                          │    → semantic answer cache → hybrid retrieval (BM25 + Chroma, role-filtered)
                          │    → specialist (mini) → verifier (mini) → output guard (PHI scan, grounding threshold)
                          ├─ Consistency agent (LangGraph): facts → version-reference rules → judge → findings
                          ├─ SQLite: documents, findings, HITL outputs, traces/spans, hash-chained audit trail
                          └─ ChromaDB (local MiniLM embeddings): chunks + answer cache
```

## How each theme is covered

- **Token optimisation:** rules run before any LLM call. Each document version gets one digest call that serves every role. Summary questions are answered from that digest at 0 tokens. The semantic answer cache is keyed by role, study, document versions and prompt version, so a new document version invalidates old answers automatically. Only the top 6 chunks go into a prompt, each request has a token budget, outputs are JSON with capped length, and chat memory keeps only the last 2 turns. Savings are measured and shown in the Admin console.
- **Guardrails:** PHI redaction and patient-identity requests are blocked, prompt injection is detected, the topic is kept to trial documents, role scope is enforced at retrieval, every claim needs a citation, answers below the grounding threshold are withheld, the output gets a second PHI scan, and each request has a token budget. Every guardrail can be switched on or off, and each change is audited.
- **AI observability:** each request produces one trace, with one span per agent step (model, tokens in, out and cached, latency, cost). The Admin console shows the pipeline averages, tokens by model, token savings, cache levels, recent traces and the step-by-step Agent trace.
- **Responsible AI and GxP:** every answer carries citations and an "AI-generated" label. A verifier pass checks each claim. Agents only suggest and never close a discrepancy. Dismissing a finding needs a reason. An AI output only becomes a record after reviewer approval, then QA e-signature with password re-entry and the meaning of the signature. The audit trail is hash-chained (SHA-256) and can be re-verified and exported.
- **Success metrics:** each dashboard shows estimated review effort, manual vs assisted (minutes per page set in `.env`), evidence coverage (verified claims) and a confidence scorecard.

## Notes
- The embedding cache (caching level 4) is deferred and listed as "deferred" in the Admin console.
- On a corporate network, `SSL_MODE=system` makes Python trust the Windows certificate store.
- To reset all data, stop the backend and delete `data/triallens.db` and `data/chroma/`.
