# EASA Progress

The milestone tracker required by the commit workflow (sections 15–16 of `CLAUDE_DEVELOPMENT_GUIDE.txt`). A milestone's own commit hash can't be written into that same commit, so each milestone records the previous milestone's hash.

Status labels: **COMPLETE** (implemented and verified), **PARTIAL**, **BLOCKED**, **NOT STARTED**.

## Phase 1: Foundation and Architecture

| Milestone | Scope | Status | Commit |
|---|---|---|---|
| M0 | Repository hygiene: `.gitignore`, `.gitattributes`, `.editorconfig`, README draft | COMPLETE | `c3cc9d3` |
| M1 | Backend skeleton: strict config, correlation IDs, JSON logs, standard errors, liveness/readiness | COMPLETE | `344e424` |
| (guide) | Development guide: mandatory commit protocol/workflow (sections 15–16) | COMPLETE | `6ebf95f` |
| M2 | Database sessions, settings-driven Alembic, empty baseline migration | COMPLETE | the commit that adds this row |
| M3 | Frontend shell: Next.js, strict TS, Tailwind, Zod-validated API client, Vitest | NOT STARTED | |
| M4 | Documentation: HLD, LLD, DATABASE_DESIGN, API_SPECIFICATION, SECURITY, DEVELOPMENT_GUIDE, ARCHITECTURE_DECISIONS | NOT STARTED | |
| M5 | Dev/check scripts and GitHub Actions CI | NOT STARTED | |

## M2: Database foundation

**Scope:** SQLAlchemy session management, database configuration integration, Alembic configuration and an empty baseline migration. There are no domain tables and no business functionality.

**Implemented**

- `app/db/session.py`:
  - `create_session_factory` (no autoflush, no expire-on-commit).
  - `session_scope`: commits on success and rolls back on any exception.
  - `iter_session`: request-scoped and never commits on its own. It rolls back on error and always closes.
- `app/api/dependencies.py`: `get_db_session` FastAPI dependency backed by `app.state.session_factory`.
- `app/db/base.py`: `Base` declarative class with a constraint naming convention, so constraint names match on SQLite and PostgreSQL.
- `app/db/models.py`: model registry for autogenerate. It is intentionally empty.
- `app/db/engine.py`: SQLite connections enable `PRAGMA foreign_keys=ON`.
- Alembic setup:
  - `migrations/env.py` reads the URL from the validated `Settings` and uses JSON logging. It uses batch mode on SQLite and compares column types.
  - `alembic.ini` has no URL.
  - A ruff post-write hook formats generated migrations.
- Baseline revision `7b339cea85fb` has empty `upgrade()` and `downgrade()` functions.

**Verification (executed 2026-11-07)**

| Command | Result |
|---|---|
| `uv run ruff format --check .` | 38 files already formatted |
| `uv run ruff check .` | All checks passed |
| `uv run pytest` | 45 passed |
| `uv run alembic upgrade head` / `current` | `7b339cea85fb (head)`; the only table is `alembic_version` |
| `uv run alembic check` | No new upgrade operations detected |
| `uv run alembic downgrade base` then `upgrade head` | Round-trip OK |
| `uv run alembic upgrade head --sql` | Offline SQL emitted (only `alembic_version`) |
| `EASA_DATABASE_URL=mysql://… alembic current` | Rejected by settings validation; the password was not printed |
| Live uvicorn: `/api/v1/health`, `/api/v1/health/ready` | 200 ok and 200 ready |

**Known limitations**

- `postgresql+psycopg` is an allowed driver, but `psycopg` is not installed. It will be added when PostgreSQL is introduced (Phase 3), along with tests against a real PostgreSQL database.
- Readiness checks connectivity only. It does not check that migrations are at head.
- Migrations are run by hand. The app does not migrate on startup, by design.

**Exit criteria:** met. Sessions and migrations work against SQLite, the migration history has a single head, models and migrations are in sync, and no domain tables exist.
