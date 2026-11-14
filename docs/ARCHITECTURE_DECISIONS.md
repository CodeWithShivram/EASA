# EASA — Architecture Decision Records

> Decisions made so far, in the format required by the project guide: context, options considered, decision, trade-offs, consequences.
> All records below are **Accepted**. Checked against commit `753742c` on 2026-11-14.

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
- **Consequences:** Business code never imports a driver. The switch requires installing `psycopg`, changing `EASA_DATABASE_URL` and running the migrations and tests against PostgreSQL.

<a id="adr-004"></a>
## ADR-004: Settings-driven Alembic with an empty baseline; no premature tables

- **Status:** Accepted (M2, 2026-11-07)
- **Context:** The guide requires migrations for schema changes but forbids creating tables before their requirements are understood.
- **Options considered:** (a) create all planned tables now; (b) no migrations until Phase 2; (c) configure Alembic now with an empty baseline.
- **Decision:** (c). `migrations/env.py` reads the URL from the validated application settings (none in `alembic.ini`); baseline revision `7b339cea85fb` is empty; generated files are formatted and lint-fixed by ruff through two post-write hooks.
- **Trade-offs:** Slight upfront setup with nothing to migrate yet. The hook's executable path (`.venv/Scripts/ruff`) is Windows-specific.
- **Consequences:** The app and migrations can never target different databases. `alembic check` detects drift from the first table onward. The hook path must be made portable before CI (M5).

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
- **Trade-offs:** The create-next-app template settings `cacheComponents: true` and `partialPrefetching: true` were kept without deep evaluation; `next dev` writes an `AGENTS.md` file unless disabled; `next dev`/`next start` listen on all interfaces unless `--hostname` is given.
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

---

## Open decisions (not yet made)

| Topic | Phase |
|---|---|
| Authentication approach (identity provider, session vs token) | 6 |
| Multi-tenancy model | 6 |
| Embedding model and vector store details (pgvector index type) | 3 |
| Model provider (Ollama or another free option) behind the model interface | 4 |
| Whether LangGraph is justified for agent workflows | 5 |
| Whether to keep or disable Next.js's generated `AGENTS.md` | M4 review |
