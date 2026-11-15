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

- **Status:** Accepted (Phase 2 planning, 2026-11-14). Implemented in P2-M2 (`get_identity` dependency; document routes mounted only outside production).
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
## Open decisions (not yet made)

| Topic | Phase |
|---|---|
| Authentication approach (identity provider, session vs token) | 6 |
| Multi-tenancy model | 6 |
| Chunk size, judged with answer quality | 4 (P4-M5) |
| Whether LangGraph is justified for agent workflows | 5 |
