# EASA Progress

The milestone tracker required by the commit workflow (sections 15–16 of `CLAUDE_DEVELOPMENT_GUIDE.txt`). A milestone's own commit hash can't be written into that same commit, so each milestone records the previous milestone's hash.

Status labels: **COMPLETE** (implemented and verified), **PARTIAL**, **BLOCKED**, **NOT STARTED**.

## Phase 1: Foundation and Architecture

| Milestone | Scope | Status | Commit |
|---|---|---|---|
| M0 | Repository hygiene: `.gitignore`, `.gitattributes`, `.editorconfig`, README draft | COMPLETE | `c3cc9d3` |
| M1 | Backend skeleton: strict config, correlation IDs, JSON logs, standard errors, liveness/readiness | COMPLETE | `344e424` |
| (guide) | Development guide: mandatory commit protocol/workflow (sections 15–16) | COMPLETE | `6ebf95f` |
| M2 | Database sessions, settings-driven Alembic, empty baseline migration | COMPLETE | `77f692f` |
| M3 | Frontend shell: Next.js, strict TS, Tailwind, Zod-validated API client, Vitest | COMPLETE | `753742c` |
| M4 | Documentation: HLD, LLD, DATABASE_DESIGN, API_SPECIFICATION, SECURITY, DEVELOPMENT_GUIDE, ARCHITECTURE_DECISIONS | COMPLETE | `3371ec3` |
| M5 | Dev/check scripts and GitHub Actions CI | PARTIAL (CI not yet run) | the commit that adds this row |

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

## M3: Frontend dashboard shell

**Scope:** Next.js app in `apps/web` with strict TypeScript, Tailwind, a Zod-validated API client and Vitest. There is no chat, document, authentication or backend work.

**Implemented**

- Scaffolded with `create-next-app@16.4.5` (App Router, `src/`, ESLint, Tailwind, npm). Install was skipped at first so the files could be reviewed.
  - Removed: Google-hosted fonts (no external fetch at build time), template SVGs, template README and demo page.
  - Changed: package renamed to `easa-web`, `poweredByHeader: false`, and `apps/web/.gitignore` now allows `.env.example`.
- TypeScript: `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `noFallthroughCasesInSwitch`.
- `src/lib/config.ts`: `NEXT_PUBLIC_API_BASE_URL` is validated with Zod. It must be http(s) with no path, query or fragment, and defaults to `http://localhost:8000`. An invalid value fails the build.
- `src/lib/api/`:
  - `schemas.ts`: Zod schemas for readiness and the standard error format.
  - `client.ts`: `apiGet` makes a GET without credentials and with a timeout, and checks every accepted body against its schema. Failures become typed `ApiError` kinds (`network`, `timeout`, `http`, `invalid_response`) carrying the status, code and correlation ID. Aborts by the caller are passed through unchanged.
  - `health.ts`: `getReadiness` treats a 503 `not_ready` body as a valid result.
- UI:
  - `AppHeader`, and `SideNav`: labelled navigation, Dashboard marked as the current page, future features shown as disabled text rather than links.
  - Skip link and landmarks.
  - `ApiStatusCard`: loading, ready, not ready and error states. Errors show the correlation ID, the card has a Retry button and a live status region, and the request is aborted when the card unmounts. The data loader is injected, so the UI never calls `fetch` directly.
- Tests (Vitest 5, jsdom 29, Testing Library) cover config, the client, the status card and navigation. Fake `fetch` functions and loaders are labelled as test doubles.

**Dependencies**

- Runtime: next 16.4.5, react/react-dom 19.3.0, zod ^4.6.7.
- Dev: typescript 5.9.3, eslint 9 with eslint-config-next 16.4.5, tailwindcss 4 with @tailwindcss/turbopack, @types/node ^24, vitest ^5.1, @vitejs/plugin-react ^6.2, jsdom ~29.1.1, @testing-library/react, dom, jest-dom and user-event.

**Compatibility decisions**

- `@types/node` raised from the template's `^20` to `^24`, which matches the Node runtime and is required by Vitest 5's peer range. npm refused the original combination (ERESOLVE). Nothing was forced.
- jsdom pinned to `~29.1.1`: jsdom 30 and 31 require Node `^24.15.0`, and this machine has 24.13.0. Upgrading Node is a system change, so it was not done.
- TypeScript stays on 5.x, as pinned by the template. TypeScript 7 was not adopted.
- ESLint stays on 9, as pinned by the template. npm reports 9.x as out of support.
- `RootLayout` uses an explicit props type instead of Next's generated global `LayoutProps`, so `tsc --noEmit` works without a prior build.

**Verification (executed 2026-11-07)**

| Command | Result |
|---|---|
| `npm ci` (clean install from lockfile) | 442 packages added; all checks below repeated afterwards with the same results |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0; 17 files linted, 0 errors and 0 warnings |
| `npm test` | 4 files, 27 tests passed |
| `npm run build` | Compiled successfully; `/` prerendered as static |
| `next start` + `curl /` | Shell, skip link, navigation landmark and loading state present; no `X-Powered-By` header |
| CORS preflight from `http://localhost:3000` to the API | 200, with `Access-Control-Allow-Origin: http://localhost:3000` |
| Real `getReadiness` against the running API (throwaway script outside the repo) | `ready` with a correlation ID; real 404 mapped to `code: not_found`; closed port reported as a `network` error |

Fixed during the work:

- `LayoutProps` is only defined after a Next build, so it was replaced with an explicit type.
- The Zod `.refine` crashed on unparseable URLs. It now checks `URL.canParse` first.

**Known limitations**

- The Chrome extension was not connected, so there was no visual check in a real browser. In-browser behavior is covered by the jsdom component tests, the served-HTML check and the CORS preflight.
- `cacheComponents` and `partialPrefetching` are left on, as create-next-app's defaults.
- No Playwright end-to-end tests yet (planned for later).
- Two optional `sharp` binaries appear as "extraneous" in the local `node_modules`. This affects neither the lockfile nor the build.

**Exit criteria:** met. The shell builds and is accessible, and every API response is validated at runtime with all failure paths tested.

## M4: Documentation

**Scope:** the seven documents required for Phase 1, README links and this progress record. No code changes.

**Delivered**

- [HLD.md](HLD.md): purpose, goals, current and target architecture, flows, roadmap, constraints, quality attributes, risks.
- [LLD.md](LLD.md): module layout, application factory, configuration, middleware chain, errors, logging, health design, client algorithm, status-card states, test structure, sequence diagrams, extension points.
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md): current state, engine and session policy, migrations, a provisional logical model (clearly marked as not implemented), design rules, vector and PostgreSQL plans.
- [API_SPECIFICATION.md](API_SPECIFICATION.md): conventions, error envelope and codes, full contracts for both endpoints (purpose, authentication, authorization, request, response, errors, validation, audit), planned groups without invented contracts.
- [SECURITY.md](SECURITY.md): principles, attack surface, implemented controls with evidence, gaps by phase, threat notes, security tests.
- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md): setup, running, configuration, checks, migrations, dependency and Git rules, troubleshooting from real incidents.
- [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md): ADR-001 to ADR-012 (context, options, decision, trade-offs, consequences) and open decisions.

**Verification (executed 2026-11-08 to 2026-11-14)**

Commands newly verified so the documents could include them:

| Command / claim | Result |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL=ftp://bad.example npm run build` | Build fails (exit 1, "Invalid NEXT_PUBLIC_API_BASE_URL"); normal rebuild passes |
| `uv run alembic revision --autogenerate -m "…"` | Generates an empty migration and runs the ruff hooks; the test file was deleted afterwards |
| `uv run uvicorn … --reload` | Starts the WatchFiles reloader, serves readiness, reloads on a file change |
| `npm run dev` | Serves `GET / 200` on port 3000 (and writes `apps/web/AGENTS.md`, see limitations) |

Document checks:

| Check | Result |
|---|---|
| Relative links and anchors in `docs/*.md` and README | 102 checked, 0 broken |
| Personal data and secret patterns | None found |
| Independent fact-check of every document against the code | 14 inaccuracies found and corrected (for example: the web server binds to all interfaces, not localhost; FastAPI adds two framework middleware layers; Starlette always allows the CORS-safelisted headers) |
| Test counts quoted in the documents | Re-run: backend 45 passed (ruff clean, lockfile consistent); frontend 27 passed (typecheck and lint clean) |

**Correction to M3**

The M3 live-check cleanup did not stop the API server. In this automation shell `Get-NetTCPConnection` and `netstat` report no listeners, so the port-based stop found no process, and the "port not listening" check was a false pass. The server kept running until it was found during M4 and stopped with `taskkill /T`. Server cleanup now kills the process tree by PID and confirms with a TCP connection probe. M3's code and test results are unaffected.

**Known limitations and open items**

- `next dev` writes `apps/web/AGENTS.md` (guidance for coding agents) unless `agentRules: false` is set. The file was deleted; whether to commit it or disable generation needs a decision.
- `next dev` / `next start` listen on `0.0.0.0` by default. Changing the npm scripts to bind to localhost is proposed.
- The Alembic post-write hook path (`.venv/Scripts/ruff`) is Windows-specific; it must be made portable before CI (M5).
- Mermaid diagrams (6) were written with simple syntax but not rendered locally; the Chrome extension was unavailable. Check them on GitHub after pushing.
- Documents state the commit they were checked against; they must be updated as later phases change the system.

**Exit criteria:** met. All seven required documents exist, describe only implemented behaviour as implemented, label planned work, and every command they list has been run on this machine.

## M5: Developer scripts and CI

**Scope:** one-command local checks and startup, GitHub Actions CI, and the follow-ups approved after M4 (portable Alembic hooks, no generated `AGENTS.md`, web server bound to localhost).

**Implemented**

- [scripts/check.ps1](../scripts/check.ps1):
  - Backend: `uv sync --locked`, ruff format and lint, pytest, and `alembic upgrade head` + `alembic check` on a temporary SQLite database that is deleted afterwards.
  - Frontend: lint, typecheck, tests and build.
  - Every check runs even after a failure; prints a PASS/FAIL table; exits 1 if any check failed. Options: `-Backend`, `-Frontend`, `-SkipBuild`.
- [scripts/dev.ps1](../scripts/dev.ps1):
  - Refuses to start if port 8000 or 3000 is in use (IPv4 and IPv6 probe).
  - Starts the API (`--reload`, `127.0.0.1:8000`) and the web dev server (`localhost:3000`) in one console.
  - Stops both process trees with `taskkill /T` on exit or `Ctrl+C`. `-SmokeTest` starts both, checks liveness, readiness and the page, then shuts down through the same path.
- [.github/workflows/ci.yml](../.github/workflows/ci.yml):
  - Triggers on pushes to `main` and on pull requests; read-only token; concurrency cancels superseded runs.
  - `api` job: Python 3.14, uv 0.12.9, locked install, ruff, pytest, migrations + drift check.
  - `web` job: Node 24.13.0 with npm cache, `npm ci`, lint, typecheck, tests, build.
- `apps/api/alembic.ini`: post-write hooks switched to Alembic's `module` type (`python -m ruff`), replacing the Windows-only `.venv/Scripts/ruff` path.
- `apps/web/next.config.ts`: `agentRules: false`, so `next dev` no longer writes `AGENTS.md`.
- `apps/web/package.json`: `dev` and `start` pass `--hostname localhost`.
- Documentation updated: README quick start, DEVELOPMENT_GUIDE, SECURITY, DATABASE_DESIGN, HLD, LLD, and ADR-013 for the scripts and CI.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1` | 9/9 PASS (backend 45 tests, frontend 27 tests, build), exit 0, ~2 min; no temporary database left behind |
| `scripts\check.ps1 -Backend` with `EASA_LOG_LEVEL=verbose` | Alembic step FAIL, other checks PASS, exit 1 (failure path works) |
| `scripts\dev.ps1 -SmokeTest` | API live and ready, web up, both stopped, exit 0 (28 s); no leftover processes; neither port answers afterwards |
| `next dev` after `agentRules: false` | No `AGENTS.md` created |
| `alembic revision --autogenerate` with the portable hooks | Both hooks ran; generated file formatted and lint-clean (test file deleted) |
| `ci.yml` parsed with PyYAML | Valid: 2 jobs, expected triggers, steps and permissions |
| `package-lock.json` | Contains the Linux native packages CI needs (`@next/swc-linux-x64-gnu`, Tailwind oxide, lightningcss, rolldown) |
| GitHub Actions run | **Not yet run.** Requires a push; the repository is public, so the result can be read from the GitHub API |

**Known limitations**

- CI has never run; status stays PARTIAL until the first run passes.
- The `Ctrl+C` path of `dev.ps1` shares its cleanup with `-SmokeTest`, but interactive `Ctrl+C` was not exercised by automation.
- The scripts target Windows PowerShell 5.1; on Linux/macOS run the individual commands from the development guide.
- Actions are pinned to major version tags, not commit SHAs (planned for Phase 8 hardening).
- Mermaid diagrams still need a visual check on GitHub.

**Exit criteria:** local checks and smoke test pass; CI configured. The milestone is complete once the first CI run passes.