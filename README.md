# EASA — Enterprise AI Support Agent

A learning and portfolio project. The goal is an enterprise-style AI support agent: authorized employees ask questions about company knowledge and get answers grounded in approved documents, with citations and server-side access control.

> **Status: complete (all eight phases, 2026-11-19).** Sign-in with roles; document upload with visibility levels; semantic, keyword and hybrid search; answers that cite and are checked against their sources; a support assistant whose actions wait for your confirmation; a web app; security hardening; evaluations with a local CPU model; browser tests; containers and a demo. The [final project report](docs/PROJECT_REPORT.md) summarises the results and the known limitations.
> This is not production software. All company documents and employee data used in this project are synthetic.

## Structure

```
easa/
  apps/api/   FastAPI backend (Python 3.14, uv)          [M1–M2]       
  apps/web/   Next.js frontend (TypeScript, Tailwind)    [M3: shell]
  docs/       Design, API, security and dev docs         [M4]
  scripts/    check.ps1 (all checks), dev.ps1 (run both) [M5], demo.ps1, load_test.py [P8-M5]
  .github/    GitHub Actions CI                          [M5]
```

## Try the demo (Docker)

```powershell
cd apps/api; uv sync; uv run python -m app.cli download-embedding-model; uv run python -m app.cli download-chat-model; cd ../..
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1   # builds and starts everything with synthetic demo data
```

Open http://localhost:3000 and sign in with a user from `var\demo\credentials.txt` (generated, git-ignored). Stop with `scripts\demo.ps1 -Down`. Without the model downloads the demo still runs, with a fake model that quotes sources. Details: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Quick start for development (Windows PowerShell)

```powershell
cd apps/api; uv sync; uv run alembic upgrade head; cd ../web; npm ci; cd ../..
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1     # API :8000 + web :3000, Ctrl+C stops both
powershell -ExecutionPolicy Bypass -File scripts\check.ps1   # every lint, type, test, migration and build check
```

CI runs the same checks on every push to `main` and on pull requests ([.github/workflows/ci.yml](.github/workflows/ci.yml)). Details: [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md).

## Prerequisites

Verified on the development machine (Windows 11):

| Tool    | Version verified |
|---------|------------------|
| Git     | 2.55.0           |
| Node.js | 24.13.0          |
| npm     | 11.6.2           |
| Python  | 3.14.7 (`py -3.14`) |
| uv      | 0.12.9           |

Optional: Docker Desktop (verified 29.9.3 with Compose v5.7.0) to run PostgreSQL 18 + pgvector (`docker compose up -d postgres`; see the [Development guide](docs/DEVELOPMENT_GUIDE.md#6c-postgresql--pgvector-optional)) and the local chat model (`docker compose --profile llm up -d llm`; see [section 6e](docs/DEVELOPMENT_GUIDE.md#6e-local-chat-model-llamacpp)). SQLite stays the default and needs nothing extra.

## Backend (apps/api)

All commands run from `apps/api`. uv creates `apps/api/.venv` with the system Python 3.14 and never downloads its own interpreter.

```powershell
cd apps/api
uv sync                      # install runtime and dev dependencies from uv.lock
uv run ruff format --check . # formatting
uv run ruff check .          # lint (includes security rules)
uv run pytest                # unit and integration tests (PostgreSQL tests skip unless EASA_TEST_POSTGRES_URL is set)
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Liveness. Always `200 {"status":"ok"}` while the process is up; never touches the database |
| `GET /api/v1/health/ready` | Readiness: database (`SELECT 1`), embedding model files and the chat model; `200 ready` or `503 not_ready` with the failing check |
| `POST /api/v1/documents` | Upload a PDF, DOCX or UTF-8 TXT file (validated; identical content returns the existing document). Managers and administrators |
| `GET /api/v1/documents`, `GET /api/v1/documents/{id}` | List and get the documents of your tenant that your role may see |
| `GET /api/v1/documents/{id}/chunks` | The document's chunks with page, section and text offsets |
| `POST /api/v1/search` | Hybrid (default), semantic or keyword (BM25) search over the documents you may see, with citations |
| `POST /api/v1/answers` | An answer from the current tenant's documents only, with cited sources, or `insufficient_evidence`. Needs a configured chat model |
| `/api/v1/conversations` | Create, list, read and delete your conversations; ask follow-up questions that use the last turns |
| `/api/v1/agent` | Ask the agent; it uses your permitted tools and proposes consequential actions for you to confirm or cancel |
| `/api/v1/tools` | List your permitted tools and invoke one (knowledge search, ticket lookup, draft tickets that need confirmation); every call audited. Development only |
| `GET /docs` | OpenAPI UI (disabled when `EASA_ENVIRONMENT=production`) |

Every response carries a server-generated `X-Correlation-ID` header. That ID also appears in the JSON logs and in error bodies (`{"error": {"code", "message", "correlation_id"}}`).

### Database migrations

The database URL comes from the same validated settings as the app (`EASA_DATABASE_URL`, defaulting to the git-ignored `apps/api/var/easa.db`). `alembic.ini` contains no URL.

```powershell
uv run alembic upgrade head      # apply migrations (baseline + documents tables)
uv run alembic current           # show the applied revision
uv run alembic check             # fail if ORM models and migrations have drifted
uv run alembic downgrade base    # revert all migrations
uv run alembic upgrade head --sql  # print SQL without connecting
```

Configuration uses `EASA_*` environment variables or `apps/api/.env`; see [apps/api/.env.example](apps/api/.env.example). Invalid values and unknown keys in `.env` stop the app at startup.

## Frontend (apps/web)

All commands run from `apps/web`. Requires Node.js 24 (verified on 24.13.0).

```powershell
cd apps/web
npm ci             # install exactly what package-lock.json specifies
npm run lint       # ESLint (Next.js core-web-vitals and TypeScript rules)
npm run typecheck  # tsc --noEmit (strict, noUncheckedIndexedAccess)
npm test           # Vitest + Testing Library (jsdom)
npm run test:e2e   # browser tests (Playwright) against the real API; build first, see the development guide
npm run build      # production build
npm run start      # serve the build on http://localhost:3000
```

With the API running on port 8000 and a user created (`uv run python -m app.cli create-user ...`, see the development guide), open http://localhost:3000 and sign in. The browser talks only to the web app; its server keeps the API session token in an HttpOnly cookie and forwards allowed requests to the API ([ADR-034](docs/ARCHITECTURE_DECISIONS.md#adr-034)). The dashboard's **API status** card shows readiness through the same path. Every response is validated at runtime with Zod before the UI uses it.

The API location is set by `EASA_API_URL` (server side only; default `http://localhost:8000`); see [apps/web/.env.example](apps/web/.env.example).

## Local data

Runtime data, including the SQLite database, is stored in `var/` directories. Git ignores these directories, as well as `*.db` files (and their journal/WAL/SHM files), `*.sqlite`, `*.sqlite3` and `.env` files.

## Documentation

| Document | Contents |
|---|---|
| [HLD](docs/HLD.md) | System context, current and target architecture, roadmap |
| [LLD](docs/LLD.md) | Modules, middleware chain, client design, sequence diagrams |
| [Database design](docs/DATABASE_DESIGN.md) | Engine, sessions, migrations, provisional data model |
| [API specification](docs/API_SPECIFICATION.md) | Conventions, error envelope, endpoint contracts |
| [Security](docs/SECURITY.md) | Implemented controls, gaps, threat notes, tests |
| [Development guide](docs/DEVELOPMENT_GUIDE.md) | Setup, running, checks, migrations, troubleshooting |
| [Evaluation](docs/EVALUATION.md) | Retrieval (search modes, chunk sizes, PostgreSQL vs SQLite, exact vs HNSW) and answers (correctness, refusals, prompt injection, latency) |
| [Architecture decisions](docs/ARCHITECTURE_DECISIONS.md) | ADR-001 to ADR-039 |
| [Operations](docs/OPERATIONS.md) | Running the container stack: start, stop, health, users, backup and restore, incidents, load test |
| [Project report](docs/PROJECT_REPORT.md) | What was built, results, known limitations, lessons |

## Progress

Milestone status, verification results and commit hashes are tracked in [docs/PROGRESS.md](docs/PROGRESS.md).

## Project guide

See [CLAUDE_DEVELOPMENT_GUIDE.txt](CLAUDE_DEVELOPMENT_GUIDE.txt) for engineering standards and the phased roadmap.
