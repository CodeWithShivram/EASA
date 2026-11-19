# EASA — Architecture Decision Records

> Decisions made so far, in the format required by the project guide: context, options considered, decision, trade-offs, consequences.
> All records below are **Accepted**. Checked against the M5 state (commit `3371ec3` plus M5 changes) on 2026-11-14.

| ADR | Decision | Milestone |
|---|---|---|
| [ADR-001](#adr-001) | Modular monolith in a monorepo | M0 |
| [ADR-002](#adr-002) | FastAPI on Python 3.14, managed with uv | M1 |
| [ADR-003](#adr-003) | SQLite first, behind SQLAlchemy 2; PostgreSQL later | M1–M2 |
| [ADR-004](#adr-004) | Settings-driven Alembic with an empty baseline; no premature tables | M2 |
| [ADR-005](#adr-005) | Strict, centralized configuration | M1 |
| [ADR-006](#adr-006) | Server-generated correlation IDs and JSON logging | M1 |
| [ADR-007](#adr-007) | Standard error envelope and safe failure handling | M1 |
| [ADR-008](#adr-008) | Separate liveness and readiness; dependency ports | M1 |
| [ADR-009](#adr-009) | Next.js App Router, strict TypeScript, Tailwind, npm | M3 |
| [ADR-010](#adr-010) | Runtime validation of all API responses with Zod | M3 |
| [ADR-011](#adr-011) | Testing stack: pytest/ruff and Vitest/Testing Library | M1–M3 |
| [ADR-012](#adr-012) | Version compatibility policy for a restricted machine | M1–M3 |
| [ADR-013](#adr-013) | PowerShell developer scripts and GitHub Actions CI | M5 |
| [ADR-014](#adr-014) | Development-only identity until authentication exists | Phase 2 |
| [ADR-015](#adr-015) | Content-addressed file storage and tenant-scoped document data | P2-M1 |
| [ADR-016](#adr-016) | In-request document processing with pypdf and python-docx | P2-M3 |
| [ADR-017](#adr-017) | Character-based, structure-aware chunking with exact offsets | P2-M4 |
| [ADR-018](#adr-018) | Local, pinned ONNX embeddings with versioned vectors | P3-M1 |
| [ADR-019](#adr-019) | Vector-index interface with exact brute-force search first | P3-M2 |
| [ADR-020](#adr-020) | SQLite FTS5 keyword search and reciprocal-rank-fusion hybrid | P3-M3 |
| [ADR-021](#adr-021) | PostgreSQL + pgvector as a second backend with exact search | P3-M4 |
| [ADR-022](#adr-022) | Keep exact vector search; criteria for adopting HNSW | P3-M5 |
| [ADR-023](#adr-023) | Provider-independent chat model interface; Ollama as the local provider | P4-M1 |
| [ADR-024](#adr-024) | Grounded answers: delimited sources, citation checks, explicit insufficient evidence | P4-M2 |
| [ADR-025](#adr-025) | llama.cpp server in Docker with a pinned Qwen2.5 1.5B GGUF as the local model | P4-M3 |
| [ADR-026](#adr-026) | Conversations: owner-scoped tables, history as context not evidence, no extra model call | P4-M4 |
| [ADR-027](#adr-027) | Answer settings after evaluation: 3 chunks, soft-refusal detection, support check off | P4-M5 |
| [ADR-028](#adr-028) | Tool framework: typed allowlist, server-side checks, confirmation, audit; no LangGraph | P5-M1 |
| [ADR-029](#adr-029) | Agent loop: schema-constrained steps, three tool calls, pending actions for consequential tools | P5-M3 |
| [ADR-034](#adr-034) | Web sign-in through a backend for frontend: HttpOnly session cookie, allowlisted proxy, no streaming | P7-M1 |
| [ADR-033](#adr-033) | Document visibility: a minimum role per document, filtered inside every query | P6-M3 |
| [ADR-032](#adr-032) | Role permissions, route checks with audited refusals, user administration | P6-M2 |
| [ADR-031](#adr-031) | Authentication: built-in sign-in with server-side sessions; one role per user; tenants table | P6-M1 |
| [ADR-030](#adr-030) | Agent safeguards after evaluation: claimed-action check and user-only fields; no prompt change | P5-M5 follow-up |

---

<a id="adr-001"></a>
## ADR-001: Modular monolith in a monorepo

- **Status:** Accepted (M0, 2026-11-07)
- **Context:** One developer; a portfolio project that must show clear architecture; features arrive phase by phase. The guide asks for a modular monolith and warns against premature microservices.
- **Options considered:** (a) separate repositories for web and API; (b) microservices per capability (ingestion, retrieval, chat); (c) one repository with `apps/api` and `apps/web`, each internally modular.
- **Decision:** (c). A monorepo with two applications; the API is a single deployable split into modules (core, api, services, db, and later ingestion, retrieval, agent).
- **Trade-offs:** Simple to run, review and version together; module boundaries rely on discipline rather than process isolation.
- **Consequences:** Commits can change API and UI atomically. Extracting a service later stays possible because modules talk through typed interfaces.

<a id="adr-002"></a>
## ADR-002: FastAPI on Python 3.14, managed with uv

- **Status:** Accepted (M1, 2026-11-07)
- **Context:** The machine has Python 3.14 only and forbids changes to the global installation. Typed request/response contracts and good test tooling are required.
- **Options considered:** Flask; Django + DRF; FastAPI. For environments: `venv` + pip; uv.
- **Decision:** FastAPI with Pydantic models. uv manages a project `.venv` using the system interpreter (`python-preference = "only-system"`) with a committed `uv.lock`. The app is started through a factory (`create_app`).
- **Trade-offs:** FastAPI is light and typed but leaves structure to us. uv is newer than pip but gives a lockfile and fast, reproducible installs without admin rights.
- **Consequences:** All dependencies were checked for Python 3.14 wheels first; every runtime and dev dependency has a pinned lock entry.

<a id="adr-003"></a>
## ADR-003: SQLite first, behind SQLAlchemy 2; PostgreSQL later

- **Status:** Accepted (M1–M2, 2026-11-07)
- **Context:** PostgreSQL is not available on the development machine; Phase 3 needs PostgreSQL with pgvector.
- **Options considered:** (a) wait for PostgreSQL; (b) SQLite with raw SQL; (c) SQLite through SQLAlchemy 2 with portable migrations.
- **Decision:** (c). A driver allowlist (`sqlite`, `sqlite+pysqlite`, `postgresql+psycopg`); SQLite foreign keys enabled per connection; constraint naming convention; Alembic batch mode on SQLite.
- **Trade-offs:** SQLite differs from PostgreSQL (types, concurrency, `ALTER` support), so some issues will appear only after the switch.
- **Consequences:** Business code never imports a driver. The switch requires installing `psycopg`, changing `EASA_DATABASE_URL` and running the migrations and tests against PostgreSQL. (Done in P3-M4; see [ADR-021](#adr-021).)

<a id="adr-004"></a>
## ADR-004: Settings-driven Alembic with an empty baseline; no premature tables

- **Status:** Accepted (M2, 2026-11-07)
- **Context:** The guide requires migrations for schema changes but forbids creating tables before their requirements are understood.
- **Options considered:** (a) create all planned tables now; (b) no migrations until Phase 2; (c) configure Alembic now with an empty baseline.
- **Decision:** (c). `migrations/env.py` reads the URL from the validated application settings (none in `alembic.ini`); baseline revision `7b339cea85fb` is empty; generated files are formatted and lint-fixed by ruff through two post-write hooks.
- **Trade-offs:** Slight upfront setup with nothing to migrate yet. The hooks originally pointed at a Windows-only path (`.venv/Scripts/ruff`); since M5 they use Alembic's `module` hook type (`python -m ruff`), which is portable.
- **Consequences:** The app and migrations can never target different databases. `alembic check` detects drift from the first table onward and runs in `scripts/check.ps1` and CI.

<a id="adr-005"></a>
## ADR-005: Strict, centralized configuration

- **Status:** Accepted (M1, 2026-11-07)
- **Context:** Misconfiguration should fail fast, and secrets must never leak through errors or logs.
- **Options considered:** `os.environ` lookups scattered in code; a permissive settings class; a strict Pydantic Settings class.
- **Decision:** One `Settings` class: `EASA_` prefix, `extra="forbid"` for `.env` keys, `frozen=True`, `hide_input_in_errors=True`, database URL as `SecretStr`, validated CORS origins and drivers.
- **Trade-offs:** Unknown `EASA_*` variables in the OS environment are ignored rather than rejected (pydantic-settings only rejects unknown `.env` keys). Lists must be JSON in environment variables.
- **Consequences:** Invalid configuration stops startup with a message that omits the submitted values. Tests construct `Settings` explicitly and isolate the environment.

<a id="adr-006"></a>
## ADR-006: Server-generated correlation IDs and JSON logging

- **Status:** Accepted (M1, 2026-11-07)
- **Context:** Requests must be traceable across logs, responses and error reports, without letting clients forge identifiers.
- **Options considered:** Accept a client-supplied request ID; generate one server-side; adopt full distributed tracing now.
- **Decision:** A pure ASGI middleware generates `uuid4().hex` for every HTTP request, ignores client values, stores it in a context variable, sets `X-Correlation-ID` and logs one `request completed` JSON line. A stdlib JSON formatter adds the ID to every log record; Uvicorn's handlers are routed through it.
- **Trade-offs:** No cross-service propagation (not needed in a monolith). Pure ASGI middleware is more code than `BaseHTTPMiddleware` but avoids its known pitfalls.
- **Consequences:** Every response, including CORS preflights and 500s, carries an ID that matches the logs. Query strings are not logged.

<a id="adr-007"></a>
## ADR-007: Standard error envelope and safe failure handling

- **Status:** Accepted (M1, 2026-11-07)
- **Context:** Clients need predictable errors; stack traces and internals must never reach them; browsers must still be able to read error responses.
- **Options considered:** FastAPI defaults (`{"detail": ...}`); exception handler for `Exception` (runs outside user middleware, so responses lose CORS and ID headers); an inner middleware that converts unexpected exceptions.
- **Decision:** `{"error": {code, message, correlation_id, details?}}` for all errors. Handlers for `AppError`, `HTTPException` and validation errors; an innermost `UnhandledErrorMiddleware` turns other exceptions into a generic 500.
- **Trade-offs:** A custom middleware to maintain; the CORS middleware's own rejected-preflight response stays plain text.
- **Consequences:** 500 responses keep CORS and correlation headers. Validation details omit submitted values.

<a id="adr-008"></a>
## ADR-008: Separate liveness and readiness; dependency ports

- **Status:** Accepted (M1, 2026-11-07)
- **Context:** A process can be alive while its database is unavailable; orchestrators need to tell these apart. Business logic must not depend on a specific database library.
- **Options considered:** One `/health` that checks everything; separate liveness and readiness.
- **Decision:** `/api/v1/health` never touches dependencies; `/api/v1/health/ready` runs `SELECT 1` and returns `503` with a `not_ready` body on failure. `HealthService` depends on a `DatabaseProbe` protocol implemented by `SqlAlchemyDatabaseProbe`.
- **Trade-offs:** Two endpoints instead of one; readiness checks connectivity only, not the migration version.
- **Consequences:** The pattern (Protocol in the service layer, adapter outside) is the template for future model, embedding and vector-store integrations.

<a id="adr-009"></a>
## ADR-009: Next.js App Router, strict TypeScript, Tailwind, npm

- **Status:** Accepted (M3, 2026-11-07)
- **Context:** The guide prescribes Next.js, React, TypeScript and Tailwind with accessible, responsive components.
- **Options considered:** Package managers npm or pnpm (both installed); Pages Router or App Router; scaffold manually or with `create-next-app`.
- **Decision:** `create-next-app@16.4.5` with App Router and `src/`; npm with a committed `package-lock.json`; TypeScript `strict` plus `noUncheckedIndexedAccess`, `noImplicitOverride`, `noFallthroughCasesInSwitch`; template fonts from Google removed in favour of the system font stack; `poweredByHeader: false`.
- **Trade-offs:** The create-next-app template settings `cacheComponents: true` and `partialPrefetching: true` were kept without deep evaluation. Two Next.js defaults were overridden in M5: `agentRules: false` stops `next dev` from writing `AGENTS.md`, and the npm scripts pass `--hostname localhost` because Next.js otherwise listens on all interfaces.
- **Consequences:** No external requests at build time; strict typing catches unchecked array access.

<a id="adr-010"></a>
## ADR-010: Runtime validation of all API responses with Zod

- **Status:** Accepted (M3, 2026-11-07)
- **Context:** TypeScript types do not exist at runtime; API responses are untrusted input to the UI.
- **Options considered:** Trust typed `fetch` results; hand-written type guards; Zod schemas.
- **Decision:** Every response passes a Zod schema in a single `apiGet` client. Failures become typed `ApiError` kinds (`network`, `timeout`, `http`, `invalid_response`) carrying status, code and correlation ID. Components receive injected loaders and never call `fetch`. Public configuration is validated with Zod too.
- **Trade-offs:** Schemas duplicate the backend models by hand; drift is caught by tests and at runtime, not at compile time. Generating types from OpenAPI may be considered later.
- **Consequences:** Malformed or unexpected responses produce a clear error state instead of a broken UI.

<a id="adr-011"></a>
## ADR-011: Testing stack: pytest/ruff and Vitest/Testing Library

- **Status:** Accepted (M1–M3, 2026-11-07)
- **Context:** Tests must be deterministic, fast and part of every milestone.
- **Options considered (frontend):** Jest; Vitest. **DOM environment:** jsdom; happy-dom.
- **Decision:** Backend: pytest with warnings as errors, strict markers/config, ruff (lint and format, including security rules); FastAPI `TestClient` (which uses `httpx2` with Starlette 1.10). Frontend: Vitest 5, Testing Library, jsdom 29, ESLint, `tsc --noEmit`.
- **Trade-offs:** Treating warnings as errors surfaces upstream deprecations immediately (e.g. the `httpx` → `httpx2` change) at the cost of occasional dependency work.
- **Consequences:** 72 automated tests at M3. Playwright end-to-end tests are deferred.

<a id="adr-012"></a>
## ADR-012: Version compatibility policy for a restricted machine

- **Status:** Accepted (M1–M3, 2026-11-07)
- **Context:** Company laptop, no admin rights, Python 3.14.7 and Node 24.13.0 as installed. Some current packages need newer runtimes.
- **Options considered:** Upgrade runtimes; force installs (`--force`, `--legacy-peer-deps`); pin the newest compatible versions.
- **Decision:** Never change system software or force installs. Pin compatible versions and record why: `jsdom ~29.1.1` (30+ needs Node ≥ 24.15), `@types/node ^24` (Vitest 5 peer range, matches runtime), TypeScript 5.x and ESLint 9 as pinned by the Next.js template, `httpx2` for Starlette's test client.
- **Trade-offs:** Some packages lag behind the latest release; ESLint 9 is reported as out of support.
- **Consequences:** Installs are reproducible from lockfiles. Upgrades are revisited when the runtime changes.

<a id="adr-013"></a>
## ADR-013: PowerShell developer scripts and GitHub Actions CI

- **Status:** Accepted (M5, 2026-11-14)
- **Context:** The checks span two toolchains (uv and npm) and should be one command locally and automatic on every push. The development machine is Windows without `make`; CI runs on Linux.
- **Options considered:** `make` (not installed); npm scripts at the repository root (would need a root `package.json`); Python task runners (new dependency); PowerShell scripts plus a GitHub Actions workflow.
- **Decision:** `scripts/check.ps1` runs all checks and reports PASS/FAIL per check; `scripts/dev.ps1` starts both servers, stops both process trees on exit, and has a `-SmokeTest` mode. `.github/workflows/ci.yml` runs the same checks in two jobs (API and web) with locked installs, the same uv and Node versions as the dev machine, and a read-only token.
- **Trade-offs:** The scripts are Windows PowerShell, so Linux/macOS developers run the individual commands (or CI). Actions are pinned to version tags (major tags, or an exact release where no major tag exists) rather than commit SHAs.
- **Consequences:** One command reproduces CI locally. Platform-specific settings (such as the Alembic hook path) must stay portable because CI runs on Linux.

<a id="adr-014"></a>
## ADR-014: Development-only identity until authentication exists

- **Status:** Superseded by [ADR-031](#adr-031) (P6-M1, 2026-11-16). Was accepted in Phase 2 planning and implemented in P2-M2.
- **Context:** The roadmap puts authentication and RBAC in Phase 6, but Phase 2 stores documents that must carry an owner and a tenant. The guide forbids trusting identity supplied by the browser.
- **Options considered:** (a) a fixed development identity from server configuration; (b) bring minimal authentication forward; (c) no HTTP upload in Phase 2, only a command-line ingestion tool.
- **Decision:** (a). The server reads a development tenant and user ID from its own configuration (`EASA_DEV_TENANT_ID`, `EASA_DEV_USER_ID`). It never takes identity from requests. Document endpoints are disabled when `EASA_ENVIRONMENT=production`. Tables carry real `tenant_id` and `owner_id` columns now; foreign keys are added in Phase 6.
- **Trade-offs:** Everyone using a development server acts as the same user, so per-user authorization cannot be tested until Phase 6.
- **Consequences:** Phase 6 replaces one dependency (the identity provider) without changing tables, repositories or services, which already take `tenant_id` explicitly.

<a id="adr-015"></a>
## ADR-015: Content-addressed file storage and tenant-scoped document data

- **Status:** Accepted (P2-M1, 2026-11-14)
- **Context:** Uploaded files are untrusted. Their names can contain path traversal or reserved characters, and the same file may be uploaded repeatedly. Document data must never leak across tenants.
- **Options considered (storage):** store bytes in the database; store files under their original or a sanitized name; store files by content hash. **(Data access):** filter by tenant in each service; require the tenant in every repository method.
- **Decision:** Bytes are stored on disk by SHA-256 (`<root>/ab/cd/<sha256>`, atomic writes) behind a `BlobStore` protocol; only validated hex digests become paths. `documents` is unique per `(tenant_id, sha256)`, which makes uploads idempotent. `DocumentRepository` takes `tenant_id` in every method, and `document_chunks` carries `tenant_id` for later retrieval filters. Allowed-value columns use explicit, convention-named check constraints, and timestamps use a UTC-enforcing column type.
- **Trade-offs:** Blobs are shared across tenants with identical content, so deleting a document cannot simply delete its blob (reference counting is not implemented). Local disk only; object storage would be another `BlobStore` implementation.
- **Consequences:** Filenames are display metadata only. Cross-tenant reads by guessed IDs return nothing at the repository level, which tests verify.

<a id="adr-016"></a>
## ADR-016: In-request document processing with pypdf and python-docx

- **Status:** Accepted (P2-M3, 2026-11-14; processing model and UTF-8-only TXT approved in Phase 2 planning)
- **Context:** Uploaded documents must become normalized text with page and section metadata. The machine is CPU-only, files are limited to 10 MiB by default, and there is no queue infrastructure.
- **Options considered:** Processing: within the upload request; FastAPI background tasks; a job queue. PDF: `pypdf` (pure Python); `pdfplumber` (pulls in six more packages including `cryptography` and `pypdfium2`); PyMuPDF (AGPL licence). DOCX: `python-docx`; hand-parsing the XML. TXT: UTF-8 only; encoding detection with `charset-normalizer`.
- **Decision:** Process within the request after the row is inserted, recording `processing` → `processed`/`failed` on the document. Use `pypdf` (page-level text, encrypted PDFs rejected, page limit) and `python-docx` (headings as sections, tables as text). Accept TXT only as UTF-8. Normalize every block deterministically.
- **Trade-offs:** Upload latency includes parsing, and a slow or hostile file occupies a worker thread; parsing runs in the API process without separate CPU/memory limits. `pypdf`'s layout handling is basic (no OCR, simple text order). Treating every exception from opening a DOCX package as `corrupt_file` is broad, but it is limited to that one call on untrusted input.
- **Consequences:** Simple to test and reason about; no background infrastructure. Moving to background processing later only changes where `_process` is called, because the status field already models it. The P2-M5 security review showed that in-process parsing needs explicit work budgets (characters, blocks, chunks, decoded PDF bytes, time) and linear algorithms; these were added, but a slow PDF can still occupy a worker for up to about 30 seconds, so isolating parsers in a separate process with hard limits remains a security follow-up.

<a id="adr-017"></a>
## ADR-017: Character-based, structure-aware chunking with exact offsets

- **Status:** Accepted (P2-M4, 2026-11-14)
- **Context:** Retrieval (Phase 3) needs chunks that fit model context, keep citations (page, section) and can be traced back to the source text. Phase 3 must also compare chunk sizes and overlap, so chunking has to be configurable and reproducible.
- **Options considered:** Size unit: characters; tokens (needs a tokenizer tied to an embedding model not chosen yet). Strategy: fixed windows only; structure-aware merging only; both, selectable. Offsets: none; offsets into the raw file; offsets into the normalized canonical text.
- **Decision:** Character-based limits with two strategies selected by configuration: `structured` (default: whole blocks, never across pages or sections, headings start chunks, oversized blocks split into windows) and `fixed` (overlapping windows that break at whitespace). Offsets refer to the canonical normalized text, and every chunk's text equals that slice exactly. The configuration used is stored on each document (`chunking_config`).
- **Trade-offs:** Character counts only approximate token counts, so `max_chars` must leave headroom once the embedding model is known. A chunk spanning blocks reports the page and section where it starts. The canonical text is not stored, so the offsets are reproducible only by re-extracting with the same code.
- **Consequences:** Chunking is deterministic and fully unit-testable through the slice invariant. Phase 3 can re-chunk with other settings and compare retrieval quality per configuration. Token-based limits can be added as another strategy without changing storage.

<a id="adr-018"></a>
## ADR-018: Local, pinned ONNX embeddings with versioned vectors

- **Status:** Accepted (P3-M1, 2026-11-14; runtime and model download approved in Phase 3 planning)
- **Context:** Retrieval needs embeddings on a CPU-only Windows laptop, with no paid services, Python 3.14 and limited bandwidth. Tests must be deterministic and must not need the network. The guide requires recording the embedding model, its dimensions and version, and never mixing incompatible vectors.
- **Options considered:** Runtime: `fastembed` + ONNX Runtime (~16 MB runtime, 64 MB quantized model); `sentence-transformers` + PyTorch (~121 MB for `torch` alone, same model); Ollama (not installed). Model: `BAAI/bge-small-en-v1.5` (384 dimensions, MIT). Tests: mock the embedder; use a deterministic stand-in.
- **Decision:**
  - An `Embedder` protocol with two implementations: `OnnxEmbedder` (fastembed, `bge-small-en-v1.5` quantized ONNX, pinned to revision `aa8f8b06…`, loaded only from local files) and `HashingEmbedder` (deterministic, explicitly non-semantic) for tests and CI.
  - The model is downloaded by an explicit command, never at runtime.
  - Vectors are stored per `(chunk_id, model_id)`, with `model_id = name@revision`.
  - Chunks are embedded after processing as a separate unit of work; failures leave the document `processed`, and a backfill command fills the gaps.
  - Readiness reports whether the model is available.
- **Trade-offs:** The hashing embedder only approximates word overlap, so semantic quality can be tested only in the separate real-model path (`tests/model`, skipped in CI). Embedding adds latency to uploads (about 2.7 s for the first upload including the model load, then under 1 s for small documents). Pinning the revision means upstream fixes need a deliberate update and re-embedding.
- **Consequences:** No vendor lock-in: other providers implement the same protocol. Switching models creates new vectors under a new `model_id` instead of silently mixing spaces. Searchability is visible in the database (chunks lacking vectors) and in readiness.

<a id="adr-019"></a>
## ADR-019: Vector-index interface with exact brute-force search first

- **Status:** Accepted (P3-M2, 2026-11-14; SQLite-first and NumPy brute force approved in Phase 3 planning)
- **Context:** Semantic search must be correct, tenant-isolated and testable now. PostgreSQL with pgvector is planned (P3-M4) but needs Docker. The corpus is small and synthetic.
- **Options considered:** NumPy brute force over vectors stored in SQL; the `sqlite-vec` extension (fast, but a 0.1.x release and a native extension); an external vector database (new infrastructure); pgvector immediately.
- **Decision:**
  - A `VectorIndex` protocol whose contract requires tenant, status and model filtering **before** scoring.
  - First implementation: `BruteForceVectorIndex`, which streams the tenant's vectors for one model in batches from any SQL backend, scores them with NumPy and keeps a deterministic top-k.
  - Search results are enriched with a second tenant-scoped query.
- **Trade-offs:** The cost is linear in the tenant's chunk count for every query (about 30 ms server-side on the demo corpus). Fine for thousands of chunks, not for millions. Exact results, so there are no recall losses to tune.
- **Consequences:** Retrieval correctness and isolation are tested independently of any index technology. pgvector (P3-M4) becomes a second implementation of the same protocol, and results can be compared against the exact baseline in the evaluation (P3-M5).

---

<a id="adr-020"></a>
## ADR-020: SQLite FTS5 keyword search and reciprocal-rank-fusion hybrid

- **Status:** Accepted (P3-M3, 2026-11-14)
- **Context:** Semantic search misses exact terms such as codes, names and rare words, while keyword search misses paraphrases ("vacation" vs "annual leave"). The roadmap asks for keyword and hybrid retrieval. The database is SQLite today and PostgreSQL in P3-M4.
- **Options considered:**
  - Keyword: SQLite FTS5 (built into Python's `sqlite3`, BM25 ranking, stemming); a Python BM25 library over all chunks in memory (new dependency, index rebuilt per process); `LIKE` queries (no ranking).
  - Hybrid: weighted sum of normalized scores (needs per-query score normalization and a tuned weight); reciprocal rank fusion (rank-based, no tuning).
- **Decision:**
  - An external-content FTS5 table over `document_chunks.text`, kept in sync by triggers and created by a hand-written migration (excluded from autogenerate). Porter stemming with Unicode folding.
  - Tenant and status filters are applied in the same SQL query as the `MATCH`, by joining back to the chunk and document tables.
  - User text is never passed as FTS5 syntax: it is reduced to quoted word tokens joined with `OR`.
  - `KeywordIndex` is a protocol, like `VectorIndex`; a PostgreSQL implementation follows in P3-M4. On other databases the SQLite implementation returns `503 keyword_search_unavailable` instead of failing.
  - Hybrid mode fuses the top `max(4 × top_k, 20)` candidates of each ranking with reciprocal rank fusion (`k = 60`, the value from the original RRF paper). The request's `mode` defaults to `semantic`, so existing clients are unaffected.
- **Trade-offs:**
  - FTS5's BM25 statistics span all tenants, so scores are slightly influenced by other tenants' text (rows are still filtered); accepted for the development build and documented in [SECURITY.md](SECURITY.md).
  - The index is keyed on SQLite's implicit `rowid`, which `VACUUM` may renumber, hence the `rebuild-keyword-index` command.
  - `OR` matching favours recall over precision; BM25 ranking puts chunks matching more terms first.
  - RRF ignores score magnitudes, so a near-perfect match counts no more than a weak first place; in exchange it needs no score normalization or weight tuning. Hybrid scores are not comparable with the other modes.
- **Consequences:** The search API offers three modes behind one endpoint, and keyword search keeps working when the embedding model is missing. The evaluation (P3-M5) can compare the modes on the same dataset.

---

<a id="adr-021"></a>
## ADR-021: PostgreSQL + pgvector as a second backend with exact search

- **Status:** Accepted (P3-M4, 2026-11-14; Docker image pull, `psycopg` and `pgvector` approved in the P3-M4 plan)
- **Context:** The roadmap targets PostgreSQL with pgvector. SQLite must stay the zero-setup default. PostgreSQL is not installed on the machine, but Docker Desktop is. Another local project already uses port 5432.
- **Options considered:**
  - Server: Docker Compose with `pgvector/pgvector` (pinned tag); a native PostgreSQL install (system-level software, not approved); a hosted database (paid, external).
  - Vector storage: a portable column type (blob on SQLite, `vector` on PostgreSQL); a separate PostgreSQL-only table (duplicated model and repository code); a fixed-dimension `vector(384)` column (ties the table to one model).
  - Vector search: exact `<=>` ordering; an HNSW index now.
  - Keyword search: an expression GIN index on `to_tsvector('english', text)`; a stored generated `tsvector` column (an ORM schema difference between backends).
- **Decision:**
  - `compose.yaml` runs `pgvector/pgvector:0.8.7-pg18` on `127.0.0.1:5433` with the password from a git-ignored `.env`.
  - `EmbeddingVector` keeps vectors as bytes in Python on both backends and maps to an undimensioned pgvector `vector` on PostgreSQL. One hand-written migration (no-op on SQLite) enables the extension, converts the column (deleting derived vectors) and adds the GIN index.
  - `PgvectorIndex` and `PostgresKeywordIndex` implement the existing protocols; `build_indexes` chooses implementations from the session's dialect, so the service and API are unchanged.
  - Exact search first; no HNSW index in P3-M4.
  - `tests/postgres` runs against throwaway databases when `EASA_TEST_POSTGRES_URL` is set, and CI always runs it against a service container.
- **Trade-offs:**
  - Exact search scans all of a tenant's vectors for one model on every query: fine for the demo corpus, linear in size. With per-tenant filters an HNSW index can silently return fewer results unless tuned (`hnsw.iterative_scan`), so it is deferred to P3-M5, where recall is measured.
  - An undimensioned column cannot carry an ANN index directly; a future HNSW index will be a partial expression index per model (`(vector::vector(384)) WHERE model_id = …`).
  - The column conversion deletes existing vectors on PostgreSQL, accepted because they are derived data recreated by `embed-missing`.
  - Keyword scores differ between backends (BM25 vs `ts_rank_cd`). `ts_rank_cd` ignores corpus-wide statistics, which also removes SQLite's cross-tenant scoring influence.
  - Two backends to test; CI covers both.
- **Consequences:** The same code, API and migration chain run on SQLite and PostgreSQL; results agree up to float rounding (tested). P3-M5 can evaluate exact search against HNSW on PostgreSQL.

---

<a id="adr-022"></a>
## ADR-022: Keep exact vector search; criteria for adopting HNSW

- **Status:** Accepted (P3-M5, 2026-11-14), based on [EVALUATION.md](EVALUATION.md) section 6
- **Context:** pgvector offers approximate HNSW indexes. EASA's searches are always filtered by tenant, model and document status, and the corpus is about 100 chunks today.
- **Options considered:** keep exact search; add a partial HNSW expression index per model now; HNSW with iterative scans.
- **Measurements** (50,000 synthetic vectors with intrinsic dimension 32, laptop + Docker):
  - Without a filter, HNSW recall@10 was 0.89 (`ef_search = 40`) and 0.97 (100).
  - Filtered to one of 10 tenants, recall@10 was 0.41 at the defaults, 0.83 with `ef_search = 100`, and 0.91–0.94 with `hnsw.iterative_scan = relaxed_order`.
  - HNSW median latency was about 7–11 ms versus 62–77 ms for exact search; the index took 84–94 s to build.
- **Decision:** keep exact search. Adopt HNSW only when a tenant reaches roughly 100,000 chunks or exact search exceeds the latency budget, and then: a partial index on `(vector::vector(<dims>))` per model, `hnsw.iterative_scan = relaxed_order`, `ef_search` of at least 100, and a recall check on real embeddings with `python -m app.cli evaluate-hnsw` and `evaluate`.
- **Trade-offs:** exact search costs grow linearly with a tenant's chunks, but results are always correct and need no tuning, build time or extra memory. HNSW's default settings would silently drop more than half of the correct results for filtered queries.
- **Consequences:** no schema change. The benchmark stays in the code base so the decision can be re-checked with new data.

---

<a id="adr-023"></a>
## ADR-023: Provider-independent chat model interface; Ollama as the local provider

- **Status:** Accepted (P4-M1, 2026-11-14; Ollama in Docker approved in the Phase 4 plan, the model itself still to be chosen in P4-M3)
- **Context:** Phase 4 needs a language model for grounded answers. The project must stay free and local, the laptop has no usable GPU (4 CPU cores, 16 GB RAM), and Ollama is not installed. Most of the grounding logic (context construction, citation checks, refusals) must be testable without any model.
- **Options considered:** a provider-specific SDK called from the answer service; the `ollama` Python package; a small `ChatModel` protocol with adapters over plain HTTP; hosted APIs (paid, external, not allowed for this project).
- **Decision:**
  - A `ChatModel` protocol (`model_id`, `is_available`, `generate`) with two typed errors; business code depends only on it.
  - `FakeChatModel`: deterministic and scriptable, for tests and offline development; rejected in production.
  - `OllamaChatModel`: plain `httpx` against Ollama's documented `/api/chat` and `/api/tags`, no extra SDK. Proxies ignored, redirects off, strict timeouts and output caps.
  - Off by default (`model_provider = "none"`). When configured, readiness requires the model; when disabled, readiness reports `disabled` and is unaffected.
- **Trade-offs:** plain HTTP means maintaining a small adapter instead of using an SDK, but avoids a dependency and keeps the request fully visible and testable. Non-streaming calls are simpler but show nothing until the reply is complete (acceptable at first; streaming can be added behind the same interface). Making readiness depend on a configured model means a stopped Ollama marks the whole API not ready, even though search still works; this is consistent with the embedding check and keeps the signal honest.
- **Consequences:** answer generation (P4-M2) is built and tested against the fake model; a real model is plugged in by configuration (P4-M3). Other providers can be added as further adapters.

---

<a id="adr-024"></a>
## ADR-024: Grounded answers: delimited sources, citation checks, explicit insufficient evidence

- **Status:** Accepted (P4-M2, 2026-11-15; hybrid default approved in the Phase 4 plan)
- **Context:** Answers must come only from the caller's documents, cite them, and admit when the documents are silent. Retrieved documents are untrusted: any user who can upload can try to inject instructions. The future local model is small and runs on a CPU, so the context must be short.
- **Options considered:**
  - Prompt shape: free text with sources pasted in; JSON output with structured citations (small models break JSON often); delimited `<source>` elements with `[S#]` markers in plain text.
  - Unsupported answers: return them with a warning; withhold them.
  - Orchestration: a framework such as LangChain; plain code (about 250 lines).
- **Decision:**
  - Plain code in `AnswerService`; hybrid retrieval (5 chunks by default, 6,000-character budget).
  - Rules only in the system message; sources as `<source id="S#" ...>` elements in the user message, with tag-like text escaped so a document cannot leave its element; the model replies in plain text with `[S#]` markers or an exact `INSUFFICIENT_EVIDENCE` marker.
  - Check the reply: unknown citations removed; marker, empty or uncited replies withheld as `insufficient_evidence` with a reason. No retrieved evidence → the model is not called.
  - Return only the cited sources, with the exact text the model saw.
  - Make `hybrid` the default search mode for the search API as well (EVALUATION.md recommendation 1).
- **Trade-offs:**
  - Delimiters and rules reduce prompt injection but cannot prevent it; the citation check proves that a provided source is cited, not that it supports the claim. Both are measured with a real model in P4-M5.
  - Withholding uncited replies may hide correct answers from a model that forgets to cite; that is preferred to showing unsupported text.
  - The hybrid default changes the search API's scores (RRF, at most about 0.033) and can rank paraphrase matches slightly lower than semantic search (EVALUATION.md section 4.3); clients can still request `semantic`.
- **Consequences:** answer quality now depends on retrieval quality and on the model following the format; P4-M3 adds a real model and P4-M5 evaluates citation validity, refusals and injection resistance.

---

<a id="adr-025"></a>
## ADR-025: llama.cpp server in Docker with a pinned Qwen2.5 1.5B GGUF as the local model

- **Status:** Accepted (P4-M3, 2026-11-15). Replaces the plan's "Ollama in Docker" runtime, approved after comparing both; ADR-023's interface is unchanged and the Ollama adapter stays available.
- **Context:** The laptop has 4 CPU cores, 16 GB RAM and no usable GPU; Docker has 8 GB. The model must be free, permissively licensed and small. The official `ollama/ollama` image is 3.2 GB compressed because it bundles NVIDIA libraries that cannot be used here, and there is no CPU-only tag.
- **Options considered:**
  - Runtime: Ollama in Docker (3.2 GB image, adapter ready); llama.cpp server in Docker (`ghcr.io/ggml-org/llama.cpp:server-b12407`, 282 MB, CPU-only, OpenAI-compatible API); native installs (system-level software, not approved).
  - Model (registry sizes and licence files checked): qwen2.5 1.5B Instruct (Apache-2.0, about 1 GB); granite3.3 2B (Apache-2.0, 1.55 GB); qwen3 1.7B (Apache-2.0, but emits reasoning text by default); phi3.5 / phi4-mini (MIT, 2.2–2.5 GB, slower). Rejected: qwen2.5 3B (research-only licence), llama3.2 and gemma3 (custom licences).
- **Decision:**
  - llama.cpp server, pinned by version tag, under the Compose profile `llm`, on `127.0.0.1:8082`, 4 threads, 4,096-token context, one request at a time.
  - Qwen2.5 1.5B Instruct, Q4_K_M GGUF from the official Qwen repository, pinned to a revision and verified by SHA-256; downloaded by `download-chat-model`, mounted read-only.
  - A `LlamaCppChatModel` adapter for the OpenAI-compatible API, sharing HTTP rules with the Ollama adapter.
- **Trade-offs:**
  - About 1.4 GB in total instead of about 4.2 GB, and the model file is pinned and hash-checked like the embedding model; but llama.cpp has no model library, so changing models means adding a registry entry.
  - A 1.5B model is fast enough on a CPU but follows instructions less reliably than larger models; P4-M5 measures how well it cites and refuses.
  - The image is pinned by tag, not digest.
- **Consequences:** `EASA_MODEL_PROVIDER=llamacpp` with `EASA_MODEL_NAME=qwen2.5-1.5b-instruct-q4_k_m` gives real answers locally. Larger or different models can be added as further registry entries without code changes elsewhere.

---

<a id="adr-026"></a>
## ADR-026: Conversations: owner-scoped tables, history as context not evidence, no extra model call

- **Status:** Accepted (P4-M4, 2026-11-15; design approved before implementation)
- **Context:** Follow-up questions ("Can unused ones be carried over?") need earlier turns. History is user data, and earlier answers may be wrong; the model is slow on the CPU (6–17 s per call in P4-M3).
- **Options considered:**
  - Follow-ups: ask the model to rewrite each follow-up into a standalone question first (more robust for vague references, one extra model call per question); search with the previous question plus the new one and give the model a short history (no extra call).
  - Stored citations: full source text (a second copy of document content); citation metadata only.
  - Storage: one JSON document per conversation; one row per message.
- **Decision:**
  - Tables `conversations` (tenant, owner) and `conversation_messages` (one row per message, unique position, cascade delete); every query filters by tenant and owner, and others' conversations are `404`.
  - Retrieval query = previous question + new question (within 1,000 characters); prompt history = last 2 turns, at most 1,500 characters, old citation markers removed, in a `<history>` element escaped like sources; system rule: history explains references, it is not evidence. Citations are checked against the current sources only.
  - Store citation metadata only; store a turn only after a successful answer; 50 turns per conversation; permanent deletion by the owner.
- **Trade-offs:**
  - No extra model call keeps latency down, but vague follow-ups depend on the previous question's words being enough for retrieval. In the live probe, history improved one follow-up and did not rescue another that the model also missed without history.
  - Stored citations may point to documents that are later deleted or reprocessed.
  - Chat history is stored without a retention limit (synthetic data only); a retention policy is needed before real use.
- **Consequences:** `POST /api/v1/answers` stays stateless; conversations reuse the same answer pipeline. P4-M5 can evaluate follow-up questions alongside single questions.

---

<a id="adr-027"></a>
## ADR-027: Answer settings after evaluation: 3 chunks, soft-refusal detection, support check off

- **Status:** Accepted (P4-M5, 2026-11-15). The support check stays off; the default of 3 chunks and soft-refusal detection were approved after the owner saw the numbers, implemented, and confirmed by a second evaluation run ([EVALUATION.md section 10.7](EVALUATION.md#107-confirmation-run-after-adr-027): correctness 0.72 → 0.79, unanswerable questions declined 4 → 7 of 8, answerable unchanged).
- **Context:** The answer evaluation ([EVALUATION.md section 10](EVALUATION.md#10-answer-evaluation-phase-4-p4-m5)) compared 5 and 3 chunks of 1,200 characters and 3 chunks of 800 characters with the local Qwen2.5 1.5B model, and scored an optional per-sentence support check offline.
- **Findings:** 3 chunks of 1,200 characters gave higher correctness (0.72 versus 0.67) at a third of the latency (median 10 s versus 34 s; the slowest 5-chunk answer, 129 s, exceeded the 120 s timeout). 800-character chunks scored higher on single questions but much lower on follow-ups. Citation precision was already 0.92–1.00, and the support check changed one or two outcomes per setting. Several "answered" unanswerable questions were refusals phrased in words.
- **Decision:**
  - Keep the support check off: no measurable benefit with this model and data, and an extra heuristic that can withhold answers.
  - Propose: answers retrieve 3 chunks by default (keep 1,200-character chunks), and replies stating that the sources do not provide the information become `insufficient_evidence`.
- **Trade-offs:** 3 chunks give the model less context, which could miss answers spread over several chunks (not observed in this evaluation). Phrase-based refusal detection is language- and model-specific and could, rarely, withhold an answer that mentions missing information in passing.
- **Consequences:** `DEFAULT_TOP_K` for answers and conversations is 3; `is_soft_refusal` marks such replies `model_declined`. A reply that answers but also says a detail is missing is withheld too; none of the evaluated correct answers were.

---

<a id="adr-028"></a>
## ADR-028: Tool framework: typed allowlist, server-side checks, confirmation, audit; no LangGraph

- **Status:** Accepted (P5-M1, 2026-11-15; approved in the Phase 5 plan)
- **Context:** Phase 5 lets a model propose tool calls. The answer evaluation showed that the local model does not follow instructions reliably, so safety cannot depend on it. The guide asks for typed contracts, an allowlist, permission checks, confirmation for consequential actions, timeout handling and audit records, and allows LangGraph only when justified.
- **Options considered:** LangGraph (graph orchestration, checkpointing; a large dependency for a loop of at most three steps); a model vendor's native tool-calling format (ties the design to one provider and still needs server checks); a small in-house executor with typed tools.
- **Decision:**
  - No LangGraph: the agent loop (P5-M3) stays plain code; revisit if workflows grow branches, long-running state or human-in-the-loop steps beyond one confirmation.
  - Tools are classes with Pydantic `Input` (unknown fields forbidden) and `Output` models, a required permission, a timeout, a `consequential` flag and a retry count (zero for consequential tools); a registry is the allowlist and refuses badly specified tools at startup.
  - `ToolExecutor` checks allowlist, permission (before arguments), argument size and schema, then confirmation, then runs the tool in a thread pool with a timeout; tool problems become structured results, never exceptions or stack traces.
  - Identities carry explicit permissions, deny by default; the development identity's set was configured (`EASA_DEV_PERMISSIONS`) until roles replaced it (ADR-031).
  - An `audit_logs` table records every attempt in its own transaction, with a SHA-256 digest of the arguments instead of their values.
- **Trade-offs:** Threads cannot be killed, so a timed-out tool runs on in the background (tools use their own sessions to stay isolated). Digests prove what was requested only to someone who already has the arguments. Checking permission before arguments means an authorized caller can still probe argument errors; that is intended.
- **Consequences:** P5-M2 adds the ticket tools on this framework; P5-M3 adds the model loop, which can only call `ToolExecutor.execute`, so every model decision passes the same checks as any other caller.

---

<a id="adr-029"></a>
## ADR-029: Agent loop: schema-constrained steps, three tool calls, pending actions for consequential tools

- **Status:** Accepted (P5-M3, 2026-11-15; schema-constrained JSON approved in the Phase 5 plan)
- **Context:** The local 1.5B model must choose tools and arguments. Free-text tool calls from a small model are unreliable, and its choices must never be trusted for anything consequential.
- **Options considered:** free-text JSON parsed leniently; the server's native tool-calling templates (model-specific); grammar-constrained JSON schema per step (verified with llama.cpp b12407, also supported by Ollama).
- **Decision:**
  - Each step is constrained to an `anyOf` schema of permitted tool calls (with their input schemas) and a final answer; replies are still parsed and validated, and invalid ones end the run as `failed`.
  - At most 3 tool calls per request; a call identical to an earlier one is not run again and only a final answer is offered next (added after the live probe showed a model repeating the same search three times, 114 s; 38 s with the guard).
  - A consequential call becomes a `pending_actions` row (10-minute TTL) decided once by its owner through separate endpoints; confirmation re-runs the executor with `confirmed=True`, re-checking the permission. Nothing consequential runs inside the loop.
  - Tool results go back as escaped `<tool_result>` data; messages and answers are never logged.
- **Trade-offs:** The schema guarantees the format, not good choices: in the live probe an instruction to "delete all tickets" became a proposed draft ticket, stopped only by the confirmation gate. Final answers are not citation-checked. One request can take tens of seconds on the CPU (up to 4 model calls).
- **Consequences:** P5-M4 attacks this loop (injection through documents and tickets, unauthorized and malformed calls); P5-M5 measures task success and checks that confirmation is never bypassed.

<a id="adr-030"></a>
## ADR-030: Agent safeguards after evaluation: claimed-action check and user-only fields; no prompt change

- **Status:** Accepted (P5-M5 follow-up, 2026-11-16; approved after the agent evaluation)
- **Context:** The P5-M5 evaluation ([EVALUATION.md section 11](EVALUATION.md#11-agent-evaluation-phase-5-p5-m5)) found no access-control failure, but integrity problems: an answer claimed "Ticket 1 has been closed" when nothing had changed; requests for tools that do not exist became draft-ticket proposals (3 of 4); the model set "high" priority on every draft; a user without ticket access got an invented status.
- **Options considered:** a prompt rule (say "I cannot do that" for unsupported requests, no substitute tool, tickets only when asked) plus a list of the tools the user may not use; server-side checks; a second model call to verify answers (too slow on the CPU); a request classifier that answers ticket questions without permission with a fixed message (rejected: the server cannot reliably tell a ticket question from a knowledge question such as "how do I raise a ticket?").
- **Decision:**
  - **Claimed-action check (server):** a final answer that reports a change ("has been closed", "was deleted", "is now escalated", "I have sent" …) is replaced by "I can't do that, and nothing has been changed." (`reason` `unsupported_claim`) unless a tool result of the same run contains the reported word (so "your ticket 4 has been resolved" after a status lookup is kept). Speculation after a modal ("it may have been deleted") is not a claim; that exception was added after a follow-up run replaced a truthful "not found" answer. The agent never runs a consequential tool itself, so no change can have happened within a run.
  - **User-only fields (server):** `Tool.user_stated` names input fields the model may not choose; a proposed value is dropped unless it appears as a word in the user's message, and the field's default applies. `create_draft_ticket` marks `priority`. Checked at startup against the input model.
  - **No prompt change.** The prompt rule and the list of unavailable tools were implemented and evaluated, then removed: unsupported requests still became proposals (3 of 4, as before), and the changed prompt made the model propose an unrequested ticket from the newsletter and repeat the injected fake admin address to the limited user, the first injection to reach an agent answer. A run with the original prompt and the server-side checks reproduced neither ([EVALUATION.md section 11.6](EVALUATION.md#116-follow-up-adr-030)).
- **Trade-offs:** The claim check is lexical: it can miss claims phrased differently and can replace a truthful sentence whose reported word is not in any tool result. Unsupported requests still become draft proposals; the server-written confirmation prompt and the user's decision remain the safeguard. Small prompt changes alter a small model's behaviour in unrelated tasks, so prompt edits need a full evaluation run.
- **Consequences:** the agent evaluation keeps the same 26 tasks and scorer, so runs stay comparable.

<a id="adr-031"></a>
## ADR-031: Authentication: built-in sign-in with server-side sessions; one role per user; tenants table

- **Status:** Accepted (P6-M1, 2026-11-16; options approved in the Phase 6 plan)
- **Context:** Until Phase 6 every request acted as one configured development identity (ADR-014), and the protected routes were switched off in production. The guide requires identity from a verified authentication context, deny by default, and never trusting identity supplied by the client.
- **Options considered:** built-in username and password with server-side session tokens; self-signed JWTs (stateless, hard to revoke before expiry); an external OpenID Connect provider such as Keycloak in Docker (most realistic, much more setup and a new container). For roles: one role per user with permissions in code, or roles and permissions tables.
- **Decision:**
  - Users and tenants are stored in the database; a user belongs to one tenant and has one role (`employee`, `manager`, `administrator`). Usernames are unique across the installation. Users are created by an administrator (`create-user` command; an admin API follows in P6-M2); there is no self-registration.
  - Passwords: scrypt from the standard library (n=2^15, r=8, p=3, about 32 MiB per hash, at most four at once), parameters stored with each hash; 12–128 characters, not containing the username. No new dependency.
  - Sessions: 256-bit random tokens sent as `Authorization: Bearer`; only their SHA-256 is stored. Idle limit 8 hours, absolute 24 hours, revoked at logout or when the user is disabled. Whether the browser keeps the token in an HttpOnly cookie is decided with the frontend (Phase 7).
  - Sign-in failures all look the same, unknown users still cost a password check, and five consecutive failures lock an account for 15 minutes.
  - Permissions are derived from the role on every request, never stored in the session, so role changes and revocations apply immediately (including when a pending agent action is confirmed).
  - The development identity is removed. Every route except health and sign-in requires a session, in every environment; the protected routes are therefore no longer switched off in production (the tool endpoints stay development-only).
- **Trade-offs:** An account lockout lets anyone who knows a username block that user's sign-in for 15 minutes; IP-based rate limiting is still missing (needed before any shared deployment). One database lookup per request (and at most one write per minute per session). No single sign-on; an OIDC provider can be added later behind the same `Identity`.
- **Consequences:** Existing tables keep `tenant_id` without a foreign key to `tenants` (rows from before Phase 6 have no tenant row). Tests sign in through a helper that creates users and sessions directly. P6-M2 differentiates the roles and adds user management and audit records for sign-ins.

<a id="adr-032"></a>
## ADR-032: Role permissions, route checks with audited refusals, user administration

- **Status:** Accepted (P6-M2, 2026-11-16; role table approved in the Phase 6 plan)
- **Context:** P6-M1 gave every role the same permissions. The guide asks for employee, manager and administrator roles enforced on the server, audit records for protected operations, and tests of privilege escalation.
- **Decision:**
  - Permissions per role (code, `app/core/roles.py`): employees search, read documents, read their own tickets and propose drafts; managers also upload documents and read every ticket in the tenant (support view); administrators also manage users. Each role's set contains the previous one.
  - Every route declares one permission with a `require(...)` dependency; a refusal is `403 forbidden` and an `access.denied` audit record. A test fails if a new route has neither a permission nor an explicit "session only" decision.
  - Ticket tools return any ticket of the tenant to callers with `tickets:read_all`; other callers still get the same "not found" for colleagues' tickets as for missing ones.
  - User administration lives in the administrator's own tenant (`/api/v1/users`): list, create, change role, disable or enable, reset password. Administrators cannot change their own role or disable themselves (a tenant cannot lock itself out by one mistake). Disabling and password resets end the user's sessions.
  - Audit actions: `auth.login`, `auth.logout`, `user.create`, `user.update`, `user.password_reset`, `access.denied`, in the existing `audit_logs` table (no schema change).
- **Trade-offs:** One role per user and a fixed table; finer grants (per department, per document) need P6-M3 or later. Two administrators can still demote each other. Failed sign-ins for unknown usernames are not attributable to a tenant, so tenant administrators will not see them.
- **Consequences:** Tests sign in with the least role that fits (employee by default, manager where documents are uploaded). P6-M3 adds a minimum role per document; P6-M4 the audit query endpoint (`audit:read`, administrators only; reads are audited).

<a id="adr-033"></a>
## ADR-033: Document visibility: a minimum role per document, filtered inside every query

- **Status:** Accepted (P6-M3, 2026-11-16; option approved in the Phase 6 plan)
- **Context:** Until P6-M3 every user could read every document of their tenant. The guide asks for document-level permissions, checked before retrieval and before returning content, and for retrieval to respect the same policy.
- **Options considered:** a minimum role per document; access lists per user or group (`document_permissions`); filtering results after ranking.
- **Decision:**
  - `documents.min_role` (`employee` default, `manager`, `administrator`; existing documents became `employee`). A user sees documents whose minimum role is at or below their own (`visible_levels`); a caller without a role (internal jobs, evaluations) sees employee documents only.
  - The filter is part of the database query in all four search paths (brute-force vectors, pgvector, SQLite FTS5, PostgreSQL full-text) and in the document repository (list, get, chunks, chunk lookup after ranking), so hidden chunks are never scored, ranked, sent to the model or cited. Index `levels` arguments default to employee only: a forgotten argument shows less, never more.
  - Uploaders choose the level, at most their own role, and can change it later on documents they can see (`PATCH /documents/{id}`); both are audited.
  - Re-uploading content that already exists above the uploader's role returns `409 document_exists` without any details of that document.
- **Trade-offs:** Three levels only; sharing with named people or groups is not possible. The duplicate-content answer reveals that a hidden copy of content the uploader already holds exists. Conversations keep earlier citation metadata (file name, page) even if a document is later restricted. Filtering before ranking with an extra predicate was not re-measured with the HNSW benchmark (exact search is used, ADR-022).
- **Consequences:** P6-M4 attacks this filter in the security suite; P6-M5 measures leakage with role-restricted documents.

<a id="adr-034"></a>
## ADR-034: Web sign-in through a backend for frontend: HttpOnly session cookie, allowlisted proxy, no streaming

- **Status:** Accepted (P7-M1, 2026-11-18; options approved in the Phase 7 plan)
- **Context:** The API issues bearer tokens (ADR-031). A browser must keep the token somewhere, and every place JavaScript can read is exposed to cross-site scripting. Until Phase 7 the browser called the API directly (health only, CORS `GET`).
- **Options considered:** a backend for frontend in the Next.js server with an HttpOnly cookie; the API setting a cookie itself (CORS with credentials and CSRF tokens in the API); the token in browser memory or storage.
- **Decision:**
  - Next.js route handlers under `/bff` sign in (`POST /bff/session` calls the API's login and puts the token into an `easa_session` cookie: HttpOnly, SameSite=Strict, Path=/, Secure in production and on https, expiring with the API session), return the current user (`GET`) and sign out (`DELETE`, which also ends the API session). The token never appears in a response body or page.
  - `/bff/api/v1/...` forwards only an allowlist of method and path pairs (UUID-shaped IDs, no development-only tool routes, no direct API sign-in) with the cookie's token as `Authorization: Bearer`; the browser's own `Authorization` and cookies are never forwarded; bodies are limited to the upload limit; slow model routes get a longer timeout; a `401` from the API clears the cookie.
  - Requests that change something (sign-in, sign-out and every non-`GET` proxy call) must carry an `Origin` header equal to the app's own origin, in addition to SameSite=Strict.
  - The browser never contacts the API; its configuration (`EASA_API_URL`) is server-side only. The API and its CORS settings are unchanged.
  - Next.js `proxy.ts` redirects pages without a session cookie to `/login`; this is an optimistic convenience, every decision stays with the API. Navigation entries the user's role cannot use are hidden, also only as a convenience.
  - No token streaming: answers may only be shown after the server has checked their citations.
  - No new dependency; browser end-to-end tests (Playwright) are deferred to Phase 8.
- **Trade-offs:** One more hop per request. The proxy must be kept in step with the API (an allowlist test and the API's own checks catch drift). Secure cookies need https outside `localhost`.
- **Consequences:** Later Phase 7 milestones call only `/bff/...`; the proxy allowlist already covers the routes they need.

<a id="adr-035"></a>
## ADR-035: Security hardening: response headers, in-process rate limits, dependency audits, pinned actions

- **Status:** Accepted (P8-M1, 2026-11-19; options approved in the Phase 8 plan)
- **Context:** Until Phase 8 neither the API nor the web app sent security response headers. Nothing limited how often a client could try passwords (beyond the per-account lockout of ADR-031) or call the CPU-bound model. Dependencies were checked by hand, and CI referenced Actions by tags that their owners can move.
- **Options considered:** rate limits in the API process, in a shared store (Redis) or in a reverse proxy; a Content Security Policy with per-request nonces or without; Dependabot or audits that run in CI.
- **Decision:**
  - API headers on every response: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy: same-site`. Every response except the development-only interactive docs also gets `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` and `Cache-Control: no-store` (unless the route set its own). `Strict-Transport-Security` is added in production.
  - Web headers on every page and route: the Next.js CSP variant without nonces (`'self'` plus inline scripts and styles, `'unsafe-eval'` only in development, `connect-src 'self'`, `object-src 'none'`, `base-uri`, `form-action` and `frame-ancestors` restricted), `nosniff`, `strict-origin-when-cross-origin`, `DENY`, a `Permissions-Policy` that turns off camera, microphone, location, payment and USB, and HSTS when `NODE_ENV=production`. There is no `upgrade-insecure-requests`: `next start` runs in production mode on plain http://localhost too, and every resource is same-origin anyway. Browsers ignore HSTS received over plain http (RFC 6797).
  - Rate limits in the API process, a sliding window per key. Sign-in attempts: `EASA_RATE_LIMIT_LOGIN_PER_MINUTE` (20) per client address. Model calls (answers, conversation questions, the agent): `EASA_RATE_LIMIT_MODEL_PER_MINUTE` (10) per signed-in user, not per address, because behind the backend for frontend every browser request comes from the web server. Over the limit: `429 rate_limited` with `Retry-After`. `0` turns a limit off. Reads are never limited. At most 10,000 keys are kept.
  - The client address is the TCP peer. `X-Forwarded-For` is read only when the peer is listed in `EASA_TRUSTED_PROXIES` (IP addresses, empty by default), and then from the right: the first address that is not itself a trusted proxy. Uvicorn must run with `--no-proxy-headers`. By default it trusts `X-Forwarded-For` from 127.0.0.1 and rewrites the peer before the API sees it, so any client could choose its address. The live check showed this: four sign-ins with forged addresses got `401` four times; with the flag they got `401, 401, 429, 429`. The web server forwards the `X-Forwarded-For` it received, but Next.js keeps a header that the browser supplied. So `EASA_TRUSTED_PROXIES` may list the web server only behind a reverse proxy that overwrites the header.
  - Dependency audits: `pip-audit --strict` on the locked Python dependencies and `npm audit --omit=dev --audit-level=high` on what the web app ships, in CI and `scripts/check.ps1`. GitHub's dependency review on pull requests fails on new high-severity advisories.
  - Every Action is pinned to a full commit SHA, with the release in a comment.
  - Secret scanning and push protection are GitHub repository settings. The owner enables them ([SECURITY.md](SECURITY.md#secret-scanning)); the manual pre-commit secret check stays.
- **Trade-offs:** The limits hold for one API process only; a restart clears them, and several instances would need a shared store. Without a trusted proxy, every sign-in through the web app shares the web server's bucket, so a flood of wrong passwords can block sign-ins for everyone for up to a minute (the per-account lockout already limits guessing). A per-user model limit does not stop one person with several accounts; accounts are created by administrators. A CSP that allows inline scripts protects less than nonces would, so it relies on React's escaping and on no component injecting HTML. SHA pins have to be updated by hand.
- **Consequences:** The containers in P8-M5 run Uvicorn with `--no-proxy-headers`, and the deployment notes explain `EASA_TRUSTED_PROXIES`. Development-only npm advisories are reviewed every phase (P8-M1: 17 high in build and test tooling, all from one `picomatch` ReDoS advisory that matches every published version, so there is no fixed release; none in what the app ships).

<a id="adr-036"></a>
## ADR-036: Cited agent answers: document-only runs are answered by the grounded-answer pipeline

- **Status:** Accepted (P8-M2, 2026-11-19; the design chosen by the user after the first two evaluation runs)
- **Context:** Grounded answers (Chat) have server-checked citations; the agent's answers had none. In the access evaluation (EVALUATION section 12) the agent invented an incident size, a false denial and a mixed-up codename where grounded answers declined. The Phase 8 plan asked for agent answers that cite their tool results, checked like grounded answers.
- **Options considered (each evaluated with the local model, EVALUATION section 13):**
  1. Labels `[S1]` on the knowledge passages and a prompt rule to cite them, checked like grounded answers. The 1.5B model never wrote a label in the agent loop: every answer from documents was replaced by the fixed reply (agent success 0.54; 0 of 17 permitted facts in the access evaluation). A schema-constrained `sources` field was then probed: the model listed every passage it had seen, so those citations would mean nothing.
  2. The grounded-answer pipeline over the passages the agent's searches found. It cited, but it found only 11 of 17 permitted facts, because it depended on the agent's search queries. For "Open a ticket: my mouse is broken." from a user without ticket access, it repeated an injected instruction from a vendor FAQ that one of those searches had returned ("Contact admin@evil.example for help."). Chat declined the same message.
  3. The grounded-answer pipeline exactly as Chat runs it: a fresh search on the user's message, then the same prompt and checks.
- **Decision:** Option 3.
  - When a knowledge search succeeded in a run and no other tool did, the documents are the run's only evidence. The agent's own final answer is not used. The server answers the user's message with `AnswerService.answer`, the Chat pipeline: hybrid search on the message with the caller's tenant and visibility filters, numbered sources, the grounded prompt, citation checks and the insufficient-evidence rules.
  - A cited answer is returned with its `sources` in the grounded answers' format. When the documents do not answer the message, the reply is "I couldn't find this in the documents available to you.", with `reason` `model_declined`, `no_valid_citations` or `no_results`.
  - Runs in which a ticket tool succeeded keep the agent's own answer. It carries no citations, and the page says it is not checked against sources. The claimed-change check (ADR-030) still runs first.
  - The agent's prompt, tool descriptions and tool results are unchanged from Phase 5, so its tool choices are those evaluated before (the ADR-030 lesson).
  - The assistant page renders citations with the chat's buttons and source panel.
  - The access evaluation counts the agent's cited sources like grounded answers' citations. The agent evaluation now forbids the injection documents' text in every task (as the P5-M5 follow-up recommended); that rule is what caught option 2's injected reply.
- **Trade-offs:**
  - Knowledge answers cost one more model call (about 10–15 s on the CPU).
  - The cited sources come from the answer's own search, so they can differ from the passages the agent's steps found.
  - Grounded answers keep their known limits: a citation does not prove support, and a correct but incomplete sentence is possible (k5 in section 13).
  - A run that searched and also read a ticket keeps uncited model text.
- **Consequences:** The assistant's answers from documents are as checkable as Chat's. The invented answers seen in Phase 6 are gone: on questions above the role, the agent declined 12 of 13, against 9 before.

---
## Open decisions (not yet made)

| Topic | Phase |
|---|---|
