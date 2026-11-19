# EASA — Final Project Report

> **Status:** All eight phases complete (2026-11-19). EASA is a learning and portfolio project; all data in it is synthetic. Milestone details and verification are in [PROGRESS.md](PROGRESS.md).

## 1. Summary

EASA (Enterprise AI Support Agent) is a support assistant for a fictional company, built in eight phases between 2026-11-07 and 2026-11-19. Employees sign in, ask questions about company documents and get answers that cite their sources. They can also ask an assistant about their support tickets, or for a new ticket, which is created only after they confirm it. Managers upload documents and decide who may see them, and administrators manage users and read the audit log. Everything runs locally: a CPU language model (Qwen2.5 1.5B on llama.cpp), local embeddings and PostgreSQL with pgvector, started by one demo command.

The project was built for security and verifiability rather than features:
- every decision is made on the server;
- answers are checked against their sources;
- the assistant cannot act without confirmation;
- every claim in the documentation comes from a command that was actually run.

The repository has about 11,200 lines of Python in the API and 3,800 lines of TypeScript in the web app (tests not counted), 38 architecture decision records and 47 commits.

## 2. What was built

| Phase | Theme | Result |
|---|---|---|
| 1 | Foundation | Strict configuration, correlation IDs and JSON logs, a standard error format, liveness and readiness, Alembic, a Next.js shell, CI |
| 2 | Document intelligence | PDF, DOCX and TXT upload with validation (signatures, zip limits, macro detection), extraction, structure-aware chunking with exact offsets, a security review with 11 findings fixed |
| 3 | Embeddings and retrieval | Pinned local ONNX embeddings; semantic, keyword (BM25) and hybrid search on SQLite and PostgreSQL + pgvector; a retrieval evaluation |
| 4 | Grounded answering | Answers only from retrieved sources, with checked citations and an explicit "insufficient evidence"; a local CPU model; conversations; an answer evaluation |
| 5 | Agent and tools | A typed tool allowlist with permission checks and an audit trail; an agent whose consequential actions wait for confirmation; adversarial tests; an agent evaluation |
| 6 | Authentication and RBAC | Sign-in with server-side sessions; employee, manager and administrator permissions; a minimum role per document, enforced inside every query; an audit endpoint; a leakage evaluation |
| 7 | Frontend | A backend for frontend that keeps the session token in an HttpOnly cookie; chat with citations; document management; the assistant with Confirm and Cancel; administration; an accessibility pass |
| 8 | Evaluation, reliability and delivery | Security headers, rate limits and dependency audits; cited assistant answers; browser end-to-end tests; versioned evaluation data with run metadata and token figures; containers, a demo command, load and failure tests, an operations runbook |

## 3. Architecture

A modular monolith in one repository ([ADR-001](ARCHITECTURE_DECISIONS.md#adr-001)):
- `apps/api`: FastAPI on Python 3.14 with SQLAlchemy and Alembic. Layers: routes, services, repositories, then the database and model adapters.
- `apps/web`: Next.js 16 with React 19, strict TypeScript and Tailwind. The browser talks only to the web server, which forwards an allowlist of API routes with the session token from an HttpOnly cookie ([ADR-034](ARCHITECTURE_DECISIONS.md#adr-034)).
- Retrieval: hybrid search (vector plus BM25, combined by reciprocal rank fusion) over chunks that keep page, section and character offsets. Every query applies the tenant and the user's visibility level inside SQL ([ADR-020](ARCHITECTURE_DECISIONS.md#adr-020), [ADR-033](ARCHITECTURE_DECISIONS.md#adr-033)).
- Grounded answers: numbered sources in delimited elements, a prompt that requires citations, and server checks. Unknown citations are removed; uncited replies and refusals become "insufficient evidence" ([ADR-024](ARCHITECTURE_DECISIONS.md#adr-024), [ADR-027](ARCHITECTURE_DECISIONS.md#adr-027)).
- Agent: each step is constrained to a JSON schema of the tools the user may use. Each call goes through the tool executor (allowlist, permission, arguments, timeout, audit). A consequential tool becomes a pending action that only its owner can confirm. When documents are a run's only evidence, the answer comes from the grounded pipeline ([ADR-028](ARCHITECTURE_DECISIONS.md#adr-028) to [ADR-030](ARCHITECTURE_DECISIONS.md#adr-030), [ADR-036](ARCHITECTURE_DECISIONS.md#adr-036)).
- Delivery: Docker images for the API and web app, pinned base images, a Compose profile for the whole stack and a demo script ([ADR-039](ARCHITECTURE_DECISIONS.md#adr-039)).

The design documents are [HLD.md](HLD.md), [LLD.md](LLD.md), [DATABASE_DESIGN.md](DATABASE_DESIGN.md) and [API_SPECIFICATION.md](API_SPECIFICATION.md).

## 4. Quality

**Automated tests** (all run in CI on every push):

| Suite | Tests |
|---|---|
| Backend (unit, integration, security suite, PostgreSQL, live model) | 895 |
| Web components and route handlers (Vitest) | 136 |
| Browser end to end (Playwright, real API, fake model) | 16 |

CI also checks formatting and lint, types, migrations against the models on SQLite and PostgreSQL, known vulnerabilities (pip-audit, npm audit, dependency review on pull requests) and the container builds. Every Action is pinned to a commit SHA.

**Evaluations with the local model** ([EVALUATION.md](EVALUATION.md); latest run, one command, data version 1):

| Evaluation | Result |
|---|---|
| Retrieval (60 queries, 12 documents) | Hybrid finds the right chunk first for 83% of queries, within 3 for 97% and within 10 for all |
| Grounded answers (43 cases) | 84% handled correctly; 7 of 8 unanswerable questions declined; no prompt injection succeeded |
| Agent (26 tasks, nothing confirmed) | 21 succeeded; nothing leaked; no ticket created without confirmation; 3 unsupported requests became proposals, which the confirmation gate stopped |
| Access leakage (90 checks per run, 3 roles) | No leak in any run: no restricted canary in an output or in the model's input, and no citation of a document above the user's role |

**Security** ([SECURITY.md](SECURITY.md)):
- Deny by default, with every permission checked on the server.
- scrypt passwords and hashed session tokens.
- A login lockout and rate limits.
- Document visibility enforced in SQL.
- Prompt-injection defences, and confirmation for consequential actions.
- Security headers and a Content Security Policy.
- No secrets or prompts in logs.
- A security suite of attacks on sessions, roles, tenants and the audit endpoint.

## 5. Delivery and operations

`scripts\demo.ps1` builds and starts PostgreSQL, the API, the web app and the model in Docker, and loads synthetic demo data: three users with generated passwords, 16 documents at three visibility levels and 7 tickets. The stack uses its own database, so development data is untouched. The [operations runbook](OPERATIONS.md) covers starting and stopping, health, logs, users, backup and restore (both run and checked), upgrades and incidents.

Load and failure test on the demo stack (2026-11-19, `scripts/load_test.py --failures`, laptop CPU, the model running):

| Scenario | Result |
|---|---|
| 200 searches, 10 at a time | All `200`; median 0.4 s, 95th percentile 2.3 s; 18 per second |
| 3 grounded answers at once | All `200`; 86–110 s each, because one CPU model answers one request at a time |
| 50 page loads | All `200`; median 0.07 s |
| PostgreSQL stopped | `503 database_unavailable` with `Retry-After` (P8-M5 changed this from `500`); serving again as soon as PostgreSQL was back |
| Chat model stopped | Answers `503 model_unavailable`, search unaffected; ready 34 s after restart |
| API stopped | The web app answers `502 api_unreachable` and still serves its pages; back 9 s after restart |
| 30 sign-ins through the web app | 20 accepted, then `429 rate_limited`, as designed (ADR-035) |

## 6. What the evaluations changed

Measurements changed the design several times. Each change is recorded with its numbers:
- **Three chunks, not five** (ADR-027): better answers at a third of the latency. Refusals phrased in words now count as "insufficient evidence", which raised unanswerable questions from 4 to 7 of 8 declined.
- **Server checks, not prompt rules** (ADR-030): a claimed change that no tool result shows is replaced, and only the user may set a ticket's priority. A prompt edit tried at the same time made the model leak injected text in an unrelated task, so prompt changes always get a full evaluation run.
- **Cited assistant answers** (ADR-036): asking the 1.5B model to cite inside the agent loop failed (success 0.54). Answering from the agent's own search passages let an injected instruction through. Answering exactly as Chat does was adopted: on questions above the user's role, the assistant now declines 12 of 13, against 9 before.
- **Run-to-run variation**: the local model was not deterministic between runs at temperature 0, so differences of one or two tasks are noise.

## 7. Known limitations

**Scope and data**
- Synthetic data only, and one tenant in the demo (tenant isolation is tested, not demonstrated).
- A small model on a CPU: answers take 10–60 s, and one request is answered at a time.
- English only. Documents are PDF, DOCX and TXT up to 10 MB, without OCR; scanned PDFs have no text.
- The evaluation datasets are small (60 queries, 43 answer cases, 26 agent tasks, 10 access questions) and were written by the same author as the system.

**Answer quality**
- A citation shows where a statement comes from, but it cannot prove that the source supports it. Lexical support checking exists but is off by default (ADR-027).
- The agent still proposes draft tickets for requests it cannot fulfil (delete, change priority, send email). The confirmation gate stops them, but the proposal can be misleading.
- Answers that combine a ticket and documents are uncited.

**Security and operations**
- No TLS: everything is bound to localhost. A real deployment needs a reverse proxy with https; then `EASA_TRUSTED_PROXIES` and Secure cookies apply.
- Rate limits live in one API process. Without a trusted proxy, all sign-ins through the web app share one limit of 20 a minute.
- The Content Security Policy allows inline scripts (no nonces), so protection against injected markup relies on React's escaping.
- Parsing runs inside the API process (with time and size budgets), not in a sandbox.
- Single sign-on, multi-factor authentication, password reset by email and tenant administration are not implemented.
- GitHub secret scanning and push protection are repository settings that the owner has to enable.
- Containers:
  - one machine, no orchestration, migrations run at API start, backups are manual;
  - the web image is 1.08 GB because it keeps the full production `node_modules`; Next.js standalone output would shrink it.

**Frontend**
- Browser tests cover the main flows with a fake model. Visibility changes, password resets and conversation deletion are tested only at component level, and dark mode not at all.
- An automated accessibility checker and a screen-reader test have not been run.

## 8. Lessons

- Server-side checks gave predictable improvements; prompt changes to a small model did not, and could break unrelated behaviour. Every prompt change therefore gets a full evaluation.
- Scorers need adversarial thinking too. Forbidding injected text in every task, not only in the injection tasks, caught a regression that the per-task scorer would have missed.
- Running the real thing finds what unit tests do not. Live checks found four defects, and each is now covered by a test or a launch flag:
  - Uvicorn trusted forwarded addresses by default (P8-M1 live check);
  - the web app's origin check failed inside a container (P8-M5 demo);
  - a byte order mark was added to piped passwords (P8-M5 demo);
  - a stopped database gave `500` instead of `503` (P8-M5 failure test).
- Writing down only what was executed kept the documentation honest. Several statements found to be stale during Phase 8 were corrected.

## 9. Recommended next steps

1. A reverse proxy with TLS in front of the web app, with `EASA_TRUSTED_PROXIES` and a shared rate-limit store, before anyone else uses it.
2. Sandboxed document parsing, and OCR for scanned PDFs.
3. A larger, independently written evaluation set, and repeated runs to measure variance.
4. Single sign-on (OIDC) and multi-factor authentication instead of local passwords.
5. Next.js standalone output for a smaller web image, and nonces for the Content Security Policy.

## 10. Trying it

```powershell
# once, from apps/api: the pinned models (64 MB and 1.1 GB)
uv run python -m app.cli download-embedding-model
uv run python -m app.cli download-chat-model
# from the repository root
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
```

Open http://localhost:3000 and sign in with a user from `var\demo\credentials.txt`. Try a policy question in Chat as the employee, then the same question about a manager document; ask the assistant to open a ticket and confirm it; upload a document as the manager; read the audit log as the administrator. Stop with `scripts\demo.ps1 -Down`.
