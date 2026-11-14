# EASA — Enterprise AI Support Agent

A learning and portfolio project. The goal is an enterprise-style AI support agent: authorized employees ask questions about company knowledge and get answers grounded in approved documents, with citations and server-side access control.

> **Status: Phase 2 (Document Intelligence) complete; Phase 3 (embeddings and retrieval) next.**
> The backend skeleton exists: configuration, logging, error handling, health endpoints, database sessions and Alembic migrations. Phase 2 added document upload with validation, PDF/DOCX/TXT text extraction and normalization, configurable chunking and a tenant-scoped chunks endpoint, security-reviewed in P2-M5. The frontend is a dashboard shell with an API status card. Architecture, API, database, security and development documentation is in [docs/](docs/).
> This is not production software. All company documents and employee data used in this project are synthetic.

## Structure

```
easa/
  apps/api/   FastAPI backend (Python 3.14, uv)          [M1–M2]       
  apps/web/   Next.js frontend (TypeScript, Tailwind)    [M3: shell]
  docs/       Design, API, security and dev docs         [M4]
  scripts/    check.ps1 (all checks), dev.ps1 (run both) [M5]
  .github/    GitHub Actions CI                          [M5]
```

## Quick start (Windows PowerShell)

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

Not required for Phase 1: PostgreSQL (SQLite is used initially), Ollama and Docker.

## Backend (apps/api)

All commands run from `apps/api`. uv creates `apps/api/.venv` with the system Python 3.14 and never downloads its own interpreter.

```powershell
cd apps/api
uv sync                      # install runtime and dev dependencies from uv.lock
uv run ruff format --check . # formatting
uv run ruff check .          # lint (includes security rules)
uv run pytest                # unit and integration tests
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Liveness. Always `200 {"status":"ok"}` while the process is up; never touches the database |
| `GET /api/v1/health/ready` | Readiness. Runs `SELECT 1`; `200 ready` or `503 not_ready` with `checks.database = "unavailable"` |
| `POST /api/v1/documents` | Upload a PDF, DOCX or UTF-8 TXT file (validated; identical content returns the existing document). Development only |
| `GET /api/v1/documents`, `GET /api/v1/documents/{id}` | List and get the current tenant's documents. Development only |
| `GET /api/v1/documents/{id}/chunks` | The document's chunks with page, section and text offsets. Development only |
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
npm run build      # production build
npm run start      # serve the build on http://localhost:3000
```

With the API running on port 8000, the dashboard's **API status** card calls `GET /api/v1/health/ready` from the browser and shows a ready, not ready or error state, including the correlation ID when there is an error. Every API response is validated at runtime with Zod before the UI uses it.

The API base URL is set by `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`); see [apps/web/.env.example](apps/web/.env.example). The value is embedded in the browser bundle, so it must never be a secret. An invalid URL fails the build.

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
| [Architecture decisions](docs/ARCHITECTURE_DECISIONS.md) | ADR-001 to ADR-012 |

## Progress

Milestone status, verification results and commit hashes are tracked in [docs/PROGRESS.md](docs/PROGRESS.md).

## Project guide

See [CLAUDE_DEVELOPMENT_GUIDE.txt](CLAUDE_DEVELOPMENT_GUIDE.txt) for engineering standards and the phased roadmap.
