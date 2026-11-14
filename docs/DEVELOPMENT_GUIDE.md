# EASA — Development Guide

> How to set up, run, test and change EASA locally. Every command here has been run successfully on the development machine (Windows 11, PowerShell) unless it is marked otherwise.
> Checked against the M5 state (commit `3371ec3` plus M5 changes) on 2026-11-14.
> The engineering rules for contributors and coding agents are in [CLAUDE_DEVELOPMENT_GUIDE.txt](../CLAUDE_DEVELOPMENT_GUIDE.txt); this guide is the practical companion.

## 1. Prerequisites

| Tool | Verified version | Notes |
|---|---|---|
| Git | 2.55.0 | |
| Python | 3.14.7 (`py -3.14`) | System install; never modified |
| uv | 0.12.9 | Creates `apps/api/.venv` with the system Python; never downloads an interpreter (`python-preference = "only-system"`) |
| Node.js | 24.13.0 | `apps/web` requires Node ≥ 24.0 |
| npm | 11.6.2 | |

Not needed in Phase 1: PostgreSQL, Ollama, Docker. No administrator rights are required.

## 2. First-time setup

```powershell
# Backend
cd apps/api
uv sync                 # creates .venv and installs from uv.lock

# Frontend
cd ../web
npm ci                  # installs exactly what package-lock.json specifies (took ~7 minutes on the dev network)
```

Optional configuration templates (copy only if you need to change defaults):

- `apps/api/.env.example` → `apps/api/.env`
- `apps/web/.env.example` → `apps/web/.env.local`

Both targets are git-ignored. Never put real credentials in them.

Recommended: opt out of Next.js telemetry in your shell before running `npm` commands (the scripts in `scripts/` and CI already set it).

```powershell
$env:NEXT_TELEMETRY_DISABLED = "1"
```

## 3. Running locally

**One command** (from the repository root) starts both servers in one console; `Ctrl+C` stops both:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
scripts\dev.ps1 -SmokeTest    # start both, check they respond, stop, exit 0/1
```

The smoke test has been run successfully; the interactive `Ctrl+C` shutdown uses the same cleanup code but has not been exercised by automation. Run `uv run alembic upgrade head` in `apps/api` first when migrations change.

**Or use two terminals:**

**API** (from `apps/api`):

```powershell
uv run alembic upgrade head   # once, and after pulling new migrations
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log
```

`--reload` restarts the server when Python files change. Without `--reload` the same command runs a single process. Logs are JSON on stderr; with `--reload`, the reloader's own few lines are plain text.

**Web** (from `apps/web`):

```powershell
npm run dev        # development server on http://localhost:3000
```

The `dev` and `start` npm scripts pass `--hostname localhost`, so the web server is not exposed on the local network (Next.js itself defaults to all interfaces).

Open http://localhost:3000. The **API status** card should show **Ready**. If the API is stopped it shows "Cannot reach the API…".

Production-style web run:

```powershell
npm run build
npm run start      # serves the build on http://localhost:3000
```

Useful URLs: http://127.0.0.1:8000/api/v1/health, http://127.0.0.1:8000/api/v1/health/ready, http://127.0.0.1:8000/docs.

Uploading a document from PowerShell (uses the development identity; `curl.exe`, not the PowerShell `curl` alias):

```powershell
curl.exe -F "file=@C:\path\to\policy.txt" http://127.0.0.1:8000/api/v1/documents   # 201, or 200 if already uploaded
curl.exe "http://127.0.0.1:8000/api/v1/documents?limit=10"
```

Use synthetic documents only.

Stop servers with `Ctrl+C`. If you start them in the background from a script, stop the **whole process tree** (`taskkill /PID <pid> /T /F`); killing only the parent can leave the server running (see section 9).

## 4. Configuration

| Variable | App | Default | Notes |
|---|---|---|---|
| `EASA_ENVIRONMENT` | API | `development` | `development`, `test`, `production` (production disables `/docs`) |
| `EASA_LOG_LEVEL` | API | `INFO` | `DEBUG` … `CRITICAL` |
| `EASA_DATABASE_URL` | API | `sqlite:///…/apps/api/var/easa.db` | Drivers: `sqlite`, `sqlite+pysqlite`, `postgresql+psycopg` (driver not installed yet) |
| `EASA_CORS_ALLOWED_ORIGINS` | API | `["http://localhost:3000"]` | JSON list; no wildcards |
| `EASA_STORAGE_DIR` | API | `apps/api/var/uploads` | Uploaded file contents (content-addressed); git-ignored |
| `EASA_MAX_UPLOAD_BYTES` | API | `10485760` (10 MiB) | Largest accepted file (1 byte to 100 MiB); the request body limit is this plus 64 KiB |
| `EASA_DEV_TENANT_ID`, `EASA_DEV_USER_ID` | API | synthetic UUIDs (`…0001`, `…0002`) | Development-only identity used by document endpoints (ADR-014); ignored in production, where those endpoints are not mounted |
| `NEXT_PUBLIC_API_BASE_URL` | Web | `http://localhost:8000` | Embedded in the browser bundle; never secret; invalid values fail `npm run build` |

Invalid API settings stop the server at startup with a validation error that never shows the submitted value.

## 5. Checks

**All checks** (from the repository root):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1   # backend + frontend, about 2 minutes
scripts\check.ps1 -Backend                                    # or -Frontend, -SkipBuild
```

It runs every check even after a failure, prints a PASS/FAIL table and exits with code 1 if anything failed. The Alembic step uses a temporary SQLite database that is deleted afterwards. Dependencies must already be installed.

**CI:** [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs the same checks on GitHub Actions (Ubuntu, Python 3.14, uv 0.12.9, Node 24.13.0) for pushes to `main` and for pull requests.

Individual commands:

**Backend** (from `apps/api`):

```powershell
uv sync --locked              # fails if uv.lock is out of date with pyproject.toml
uv run ruff format --check .  # formatting (use `uv run ruff format .` to fix)
uv run ruff check .           # lint, including security rules
uv run pytest                 # 144 tests; warnings are treated as errors
```

**Frontend** (from `apps/web`):

```powershell
npm run lint        # ESLint
npm run typecheck   # tsc --noEmit
npm test            # Vitest, 27 tests
npm run build       # production build
```

`npm run test:watch` exists for interactive use; it has not been run as part of verification.

Run `scripts\check.ps1` (or the relevant commands) before every commit.

## 6. Database migrations

From `apps/api`:

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic check                                   # fails if models and migrations differ
uv run alembic revision --autogenerate -m "add documents table"
uv run alembic downgrade base
uv run alembic upgrade head --sql                      # print SQL without connecting
```

Rules: models live in `app/db/` and are imported by `app/db/models.py`; review every autogenerated file; never edit a migration that has been pushed; keep migrations portable between SQLite and PostgreSQL. See [DATABASE_DESIGN.md](DATABASE_DESIGN.md).

## 7. Adding dependencies

1. Check that a compatible build exists for Python 3.14 or Node 24.13 before adding anything.
2. Add with the package manager so the lockfile updates: `uv add "<pkg>>=<ver>"` / `uv add --dev …` in `apps/api`; `npm install <pkg>` / `npm install -D <pkg>` in `apps/web`.
3. Add a comment (Python) or a note in the progress record explaining why the dependency is needed.
4. Never use `--force` or `--legacy-peer-deps` to get past a conflict; fix the cause and record the decision.

## 8. Git workflow

The full protocol is in sections 15–16 of [CLAUDE_DEVELOPMENT_GUIDE.txt](../CLAUDE_DEVELOPMENT_GUIDE.txt). Summary:

- One milestone or task per commit, with a Conventional Commit message (e.g. `feat(api): …`, `docs: …`).
- Before committing: review the full diff including untracked files, run all relevant checks, and confirm no `.env`, databases, virtual environments, `node_modules`, build output, logs or secrets are included.
- Stage explicit file paths, not the whole repository.
- Use a repository-local Git identity; never change global Git configuration for this project.
- Never amend, rebase, reset or rewrite existing history unless the maintainer explicitly authorizes it. Push only when the maintainer authorizes it.
- After each milestone, record status, verification results and the commit hash in [PROGRESS.md](PROGRESS.md), then stop for review.

## 9. Troubleshooting (issues actually encountered)

| Symptom | Cause | Fix |
|---|---|---|
| `npm ci` fails with `EPERM … unlink … next-swc.win32-x64-msvc.node` | A `next start` / `next dev` process still holds the native binary | Stop the whole Node process tree, then rerun |
| `uvicorn` fails with `[WinError 10013] … forbidden by its access permissions` | Another process (often a forgotten server) already uses the port | Stop that process tree, or use another `--port` |
| `npm install` reports `ERESOLVE` for `@types/node` | Template pinned `@types/node@^20`; Vitest 5 needs ^22 or ≥ 24 | Use `@types/node@^24` (matches the runtime) |
| `npm` warns `EBADENGINE` for jsdom 30/31 | They require Node ≥ 24.15; the machine has 24.13 | `jsdom` is pinned to `~29.1.1` |
| `npm` warns that ESLint 9 is unsupported | The Next.js template pins ESLint 9 | Known; revisit when `eslint-config-next` supports ESLint 10 |
| `pytest` fails on import with `StarletteDeprecationWarning` about `httpx` | Starlette 1.10 wants `httpx2` for its test client; warnings are errors | The dev dependency is `httpx2` |
| `npm run dev` created `apps/web/AGENTS.md` (before M5) | Next.js 16 dev server writes agent guidance unless `agentRules: false` is set | Fixed: `agentRules: false` in `next.config.ts`; delete any leftover copy |
| `scripts\*.ps1` "cannot be loaded because running scripts is disabled" | PowerShell execution policy | Run with `powershell -ExecutionPolicy Bypass -File scripts\<name>.ps1` |
| `git commit -F -` with a PowerShell here-string fails with "pathspec … did not match" | PowerShell does not pipe the here-string to stdin that way | Write the message to a file and use `git commit -F <file>` |
| `Get-NetTCPConnection` or `netstat` show no listener although a server answers | Seen in a sandboxed automation shell | Check with an HTTP request or TCP connect instead |

## 10. Project structure

See [LLD.md §1](LLD.md#1-repository-layout). Where things go: routes in `app/api/v1/routes/`, schemas in `app/schemas/`, business logic in `app/services/`, persistence in `app/db/`; on the web side, API access in `src/lib/api/` and UI in `src/components/`.
