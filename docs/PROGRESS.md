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
| M5 | Dev/check scripts and GitHub Actions CI | COMPLETE | `76582bd`, CI fix `808dfb4` |

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
| GitHub Actions run 43579416940 (commit `76582bd`) | **Failed.** Web job passed every step on Ubuntu. API job failed at "Set up job": `astral-sh/setup-uv@v10` does not exist (setup-uv publishes only exact release tags). Fixed in the follow-up commit `fix(ci): pin setup-uv to an existing release tag` by pinning `v10.3.3`; see the next row |
| GitHub Actions run 43580363504 (commit `808dfb4`) | **Passed.** API job (18 s): locked install, ruff format and lint, 45 tests, migrations + `alembic check`. Web job (38 s): `npm ci`, lint, typecheck, 27 tests, build |

**Known limitations**

- The `Ctrl+C` path of `dev.ps1` shares its cleanup with `-SmokeTest`, but interactive `Ctrl+C` was not exercised by automation.
- The scripts target Windows PowerShell 5.1; on Linux/macOS run the individual commands from the development guide.
- Actions are pinned to major version tags (setup-uv to an exact release tag, since it has no major tag), not commit SHAs (planned for Phase 8 hardening).
- Mermaid diagrams still need a visual check on GitHub.

**Exit criteria:** met. Local checks and the smoke test pass, and CI passes on GitHub Actions (run 43580363504). GitHub notes that `ubuntu-latest` moves to Ubuntu 26 from 2026-10-19; no change is needed now.

## Phase 2: Document Intelligence

Decisions approved 2026-11-14: development-only identity from server configuration ([ADR-014](ARCHITECTURE_DECISIONS.md#adr-014)), processing within the request under strict limits, TXT accepted only as UTF-8.

| Milestone | Scope | Status | Commit |
|---|---|---|---|
| P2-M1 | Data model (`documents`, `document_chunks`), tenant-scoped repository, content-addressed file store | COMPLETE | `1d549ee` |
| P2-M2 | Upload endpoint, validation, idempotency, status, list/get endpoints, development identity, request body limit | COMPLETE | `6704107` |
| P2-M3 | Text extraction (PDF, DOCX, TXT) and normalization, in-request processing with status | COMPLETE | `02117b6` |
| P2-M4 | Chunking strategies, chunk persistence, chunks endpoint, recorded chunking config | COMPLETE | `9bd5df7` |
| P2-M5 | Security review and hardening, documentation, Phase 2 report | COMPLETE | `bd41942` |

## P2-M1: Data model and storage

**Scope:** tables, migration, repository and file store only. No endpoints, parsing or chunking yet. No new dependencies.

**Implemented**

- [app/db/documents.py](../apps/api/app/db/documents.py): `Document` and `DocumentChunk` models; `DocumentMediaType` and `DocumentStatus` enums with explicit, convention-named check constraints.
- [app/db/types.py](../apps/api/app/db/types.py): `UtcDateTime` (rejects naive datetimes; returns UTC on SQLite) and `utc_now()`.
- Migration `eb5cd7e86396` (revises the baseline): both tables with primary keys, a foreign key with `ON DELETE CASCADE`, unique `(tenant_id, sha256)` and `(document_id, chunk_index)`, and check constraints. It was autogenerated, then reviewed and corrected:
  - The first draft imported application code for the timestamp type. A `render_item` hook in `migrations/env.py` now renders it as `sa.DateTime(timezone=True)`.
  - Enum check constraints were named outside the convention. They are now explicit `CheckConstraint`s.
- Naming convention for unique constraints changed to include all columns (`column_0_N_name`). This was safe because no unique constraints existed yet.
- [app/repositories/documents.py](../apps/api/app/repositories/documents.py): `DocumentRepository`. Every method requires `tenant_id`; list is newest-first with `limit` 1–200; `replace_chunks` supports reprocessing.
- [app/storage/blob_store.py](../apps/api/app/storage/blob_store.py): `BlobStore` protocol and `LocalBlobStore` (SHA-256 paths, atomic writes, deduplication, rejects invalid hashes). Wired as `app.state.blob_store`.
- Configuration: `EASA_STORAGE_DIR` (default `apps/api/var/uploads`, git-ignored).
- Docs: DATABASE_DESIGN (schema tables), LLD, HLD, SECURITY, DEVELOPMENT_GUIDE, README; ADR-014 and ADR-015.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1 -Backend` | 5/5 PASS: locked sync, ruff format, ruff lint, 77 tests (43 unit, 34 integration), migrations + `alembic check` |
| Constraint names in a migrated SQLite database | All follow the naming convention (e.g. `uq_documents_tenant_id_sha256`, `fk_document_chunks_document_id_documents`) |
| `uv run alembic upgrade head` on the development database | At `eb5cd7e86396 (head)`; `alembic check` reports no drift |
| Tenant isolation | Tests: another tenant gets `None` for a known document ID and no chunks; the same content is allowed in two tenants and rejected twice in one |
| File store safety | Tests: path-traversal strings, uppercase or short hashes and empty content are rejected; no temporary files remain |

**Known limitations**

- No endpoint uses the repository or file store yet (P2-M2).
- Blob deletion and cross-tenant reference counting are not implemented.
- The frontend is unchanged, so frontend checks were not rerun for this milestone. CI runs them after the push.

**Exit criteria:** met. Tables exist through a reviewed migration, data access is tenant-scoped and tested, and file storage cannot be steered by user input.

## P2-M2: Upload and validation

**Scope:** document upload, list and get endpoints; upload validation; idempotency; development identity; a global request body limit. Parsing, normalization and chunking are not included (P2-M3/M4). Encrypted-PDF detection moved to P2-M3 because it needs a PDF parser.

**Dependency added:** `python-multipart` 0.0.33 (pure Python), which FastAPI requires to parse `multipart/form-data` uploads.

**Implemented**

- `POST /api/v1/documents`: 201 for new content, 200 with the existing document for identical content in the same tenant; `Location` header. `GET /api/v1/documents` (`limit` 1–200, `offset`) and `GET /api/v1/documents/{id}`. Contracts are in [API_SPECIFICATION.md §3.4](API_SPECIFICATION.md#34-documents-phase-2-development-only).
- [app/services/uploads.py](../apps/api/app/services/uploads.py):
  - Filename sanitizing.
  - Extension allowlist plus a content signature check.
  - Size limit.
  - DOCX checks from the zip directory only (entries, total uncompressed size, compression ratio, encrypted entries, required parts).
  - Strict UTF-8 TXT without NUL bytes.
  - Each rejection has its own error code and HTTP status.
- [app/services/documents.py](../apps/api/app/services/documents.py): `DocumentService`. Stores the blob before inserting the row, resolves concurrent identical uploads, and returns the same 404 for missing and foreign documents.
- [app/core/middleware.py](../apps/api/app/core/middleware.py) `BodySizeLimitMiddleware`: limit is `EASA_MAX_UPLOAD_BYTES` + 64 KiB; checks the declared length up front and counts streamed bytes; returns 413 `request_too_large`.
- [app/core/identity.py](../apps/api/app/core/identity.py) and `get_identity`: the development identity comes from settings (`EASA_DEV_TENANT_ID`, `EASA_DEV_USER_ID`). Document routes are mounted only outside production.
- Settings: `EASA_MAX_UPLOAD_BYTES` (default 10 MiB, range 1 B–100 MiB), the development identity fields; `.env.example` updated.
- Docs: API spec (full document contracts and error codes), SECURITY (upload controls; request size limit now implemented), LLD, HLD, DEVELOPMENT_GUIDE (settings, verified `curl.exe` upload example), README endpoints, ADR-014 marked implemented.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `uv run ruff format --check .` / `uv run ruff check .` | Clean |
| `uv run pytest` | 144 passed (86 unit, 58 integration); 67 new tests |
| Live server (scratch database and storage, 1 MiB limit): `curl.exe -F file=@policy.txt …/documents` | 201 with the document; repeat as `copy.txt` → 200, same ID |
| Live: list and get | 200 with the stored document; timestamps in UTC (`…Z`) |
| Live: executable bytes named `evil.pdf` | 415 `file_content_mismatch` with correlation ID |
| Live: 2 MiB body | 413 `request_too_large` |
| Live: stored blobs | 1 file under the scratch storage directory; server tree stopped, port closed, no leftover processes |

Fixed during the work:

- Tabs and newlines in filenames were deleted instead of becoming spaces.
- Names starting with a dot (`.txt`, `.hidden.txt`) were silently changed instead of rejected.
- A test fixture could not create an "encrypted" zip entry, because `zipfile` resets the flag; the flag is now set in the archive bytes.

**Known limitations**

- Processing does not run yet; uploaded documents stay `uploaded` (P2-M3).
- Encrypted or malformed PDFs are only detected once parsing exists (P2-M3).
- CORS still allows only `GET`, so browsers cannot upload yet (Phase 7).
- No rate limiting. The development identity means every caller of a development server is the same user (ADR-014).
- Blob deletion is not implemented.

**Exit criteria:** met. Uploads are validated, idempotent and tenant-scoped, oversized requests are rejected early, and all behaviour is tested automatically and confirmed against a live server.

## P2-M3: Extraction and normalization

**Scope:** text extraction for PDF, DOCX and TXT; normalization; processing within the upload request with status and error codes. Chunking and chunk persistence are P2-M4.

**Dependencies added:**
- `pypdf` 7.1.0 (pure Python): PDF text per page. It has built-in decompression limits (75 MB per stream).
- `python-docx` 1.2.0, with `lxml` 6.1.3 (native wheel for Python 3.14): DOCX paragraphs, headings and tables. Its XML parser uses `resolve_entities=False`, which I confirmed in the installed source.

**Implemented**

- [app/services/extraction.py](../apps/api/app/services/extraction.py): `extract_document` returns ordered `TextBlock`s with page and section metadata plus `page_count`.
  - PDF: page blocks; encrypted files and files over `EASA_MAX_PDF_PAGES` are rejected.
  - DOCX: headings set sections; paragraphs and tables keep document order.
  - TXT: paragraphs separated by blank lines.
  - Failure codes: `encrypted_file`, `corrupt_file`, `too_many_pages`, `no_extractable_text`.
- [app/services/normalization.py](../apps/api/app/services/normalization.py): deterministic, idempotent `normalize_text` (NFC, line endings, invisible and control characters, whitespace, hyphenated line breaks, blank-line runs).
- `DocumentService._process`: `uploaded` → `processing` (committed) → `processed` (with `page_count`) or `failed` (with `error_code`). An unexpected parser exception becomes `processing_error`, is logged with its traceback, never reaches the client, and never leaves a document in `processing`. The `document processed` log line carries metadata only.
- Setting `EASA_MAX_PDF_PAGES` (default 500; range 1–5000).
- Test fixtures are now real synthetic documents: a handwritten generator for multi-page text PDFs with computed cross-references, a `python-docx`-built handbook with headings and a table, and an encrypted PDF with a random runtime password.
- Docs: API spec (processing outcome and codes), SECURITY (parsing controls; parser isolation as a follow-up), LLD (processing design and state diagram), DATABASE_DESIGN (status lifecycle), HLD, DEVELOPMENT_GUIDE, `.env.example`, and ADR-016.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `uv run ruff format --check .` / `uv run ruff check .` | Clean |
| `uv run pytest` | 174 passed (112 unit, 62 integration); 30 new tests |
| Live server (scratch database): `curl.exe -F file=@travel.pdf` | 201, `processed`, `page_count` 2 (2 text blocks) |
| Live: `handbook.docx` | 201, `processed` (7 blocks: headings, paragraphs, table) |
| Live: encrypted `locked.pdf` | 201, `failed`, `encrypted_file` |
| Live: server log | One `document processed` line per upload with metadata only; a search for document phrases found none. Server tree stopped, port closed |

Fixed during the work:

- `python-docx` raised an undocumented `AttributeError` for a malformed package. Any exception from opening a DOCX package now maps to `corrupt_file`; this is confined to that one call.
- My file-writing tool had turned `\u…` escapes into literal invisible characters in one test and in the normalization regex. Both now use escape sequences; a scan confirms all Python sources are ASCII.
- Encryption test fixtures no longer hardcode a password (ruff S106); a random one is generated at runtime.

**Known limitations**

- No OCR: scanned PDFs fail with `no_extractable_text`.
- Parsing runs in the API process without separate CPU, memory or time limits. Isolating it is recorded in SECURITY.md.
- PDF text order and layout depend on `pypdf`'s extraction; tables in PDFs are not structured.
- Extracted text is not stored yet. Chunks (P2-M4) will hold it.
- There is no endpoint to reprocess a `failed` document; re-uploading identical content returns the existing record.

**Exit criteria:** met. All three formats extract to normalized, page- and section-aware blocks; every outcome is recorded on the document; failures are safe and tested.

## P2-M4: Chunking

**Scope:** configurable chunking, chunk persistence, a chunks endpoint, and recording the chunking settings on each document. No embeddings or retrieval (Phase 3). No new dependencies.

**Implemented**

- [app/services/chunking.py](../apps/api/app/services/chunking.py): `chunk_document` with two deterministic strategies (rules in [ADR-017](ARCHITECTURE_DECISIONS.md#adr-017)):
  - `structured` (default): whole blocks; never crosses pages or sections; headings start chunks; oversized blocks are split into windows.
  - `fixed`: overlapping windows that break at whitespace.
  - Invariant for both: chunk text equals `canonical_text[char_start:char_end]`.
- Processing now chunks every successfully extracted document and stores the chunks in the same transaction as the `processed` status (partial chunks are rolled back on failure). `documents.chunking_config` records the settings used.
- Migration `e57f12a3d5ed` adds `documents.chunking_config` (JSON). It was autogenerated with SQLite batch mode and reviewed; upgrade, downgrade and drift checks are clean.
- Settings: `EASA_CHUNK_STRATEGY`, `EASA_CHUNK_MAX_CHARS` (100–20000) and `EASA_CHUNK_OVERLAP_CHARS`. The overlap must be less than half of the maximum, which is validated at startup.
- `GET /api/v1/documents/{id}/chunks`: tenant-scoped, paginated (`limit` 1–500), returns `total`. `DocumentResponse` now includes `chunking_config`.
- Repository: paginated `list_chunks` and `count_chunks`.
- Docs: API spec (chunks endpoint, `chunking_config`), DATABASE_DESIGN, LLD (chunking algorithm), SECURITY, HLD, DEVELOPMENT_GUIDE, README, `.env.example`, ADR-017.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `uv run ruff format --check .` / `uv run ruff check .` | Clean; all Python sources ASCII |
| `uv run pytest` | 205 passed (138 unit, 67 integration); 31 new tests |
| Migration on a scratch database: autogenerate, `upgrade head`, `check`, `downgrade -1`, `upgrade head` | Clean; head `e57f12a3d5ed` |
| Live server (scratch database): PDF upload + `GET …/chunks` | `processed`, recorded config `structured/1200/150`; 2 chunks on pages 1 and 2 with offsets 0–68 and 70–120 |
| Live: DOCX upload + chunks | 3 chunks with sections "EASA Employee Handbook", "Leave" (including the table), "Remote Work" |
| Live: chunks of an unknown ID | 404 `document_not_found` with correlation ID |
| Live: processing log | `blocks=2 chunks=2` and `blocks=7 chunks=3`; metadata only. Server tree stopped; no EASA server processes left |
| Development database | Upgraded to `e57f12a3d5ed (head)` |

**Known limitations**

- Limits are in characters, not tokens. They will need to be tuned once the embedding model is chosen (Phase 3).
- A chunk spanning several blocks reports the page and section where it starts.
- The canonical text is not stored; offsets are reproducible by re-extracting with the same code.
- Documents processed before P2-M4 (development databases only) have no chunks. There is no reprocess endpoint yet.

**Exit criteria:** met. Every processed document has ordered, located chunks under a recorded configuration; both strategies are deterministic and covered by invariant tests; chunks are tenant-scoped.

## P2-M5: Hardening and Phase 2 report

**Scope:** security review of the upload, processing and chunk path; fixes with regression tests; documentation corrections; Phase 2 report. Delete and reprocess endpoints were offered as optional and not requested, so they are not included. No new dependencies and no migrations.

**Method:** two independent angles.
1. My own probes against the real libraries: XML entity bombs, external entities (XXE), a PDF decompression bomb.
2. An independent read-only review agent, which used code reading, timing experiments and 20,000 zip-structure mutations (fuzzing).

Every finding was reproduced (or, where marked, reasoned through) before it was fixed.

**Findings and outcome**

| # | Finding (severity) | Verified | Fix |
|---|---|---|---|
| 1 | Quadratic chunking: block lookup scanned all blocks per chunk; a 10 MiB TXT of `a\n\n` would take ~20 min of CPU; 20k DOCX headings took 16.8 s (high) | Yes: 64→256 KiB took 0.16 s → 1.83 s | Binary search over block ends; 50,000-block and 20,000-chunk caps (`document_too_complex`) |
| 2 | DOCX `gridSpan` amplification: `row.cells` repeats a cell per spanned column; a 35 KB file could expand into billions of copies (high) | Yes: span 1,000 → 0.37 s, 5,000 → 1.22 s | Read each physical `<w:tc>` once; per-cell text budget |
| 3 | PDF parsing cost not bounded: pypdf limits only decompression (75 MB per stream, no total, no time) (medium) | My probe: `extract_text()` silently returns "" at the limit | Stream limits lowered to 20 MB, 50 MB decoded total, 30-second budget per PDF, explicit content decoding → `resource_limit_exceeded`. Residual risk documented (process isolation) |
| 4 | A document could stay in `processing` forever after a crash; re-upload returned it unchanged (medium) | Reasoning | Identical re-upload reprocesses documents stuck for more than 10 minutes; tested |
| 5 | Text cap applied only after extraction and ignored block count (low) | Reasoning | Budget enforced while extracting, separators included; block cap |
| 6 | Malformed zips (`NotImplementedError`, `UnicodeDecodeError`) caused 500s (low) | Yes (reviewer's fuzzing; my test for unsupported version) | All zipfile errors → `corrupt_file` |
| 7 | Invisible bidi and tag characters kept in chunk text (low; relevant to prompt injection in Phase 4) | Yes | All Unicode `Cf` characters removed in normalization |
| 8 | Filename gaps: tag characters, U+061C, soft hyphen (low) | Yes | Remove Unicode `Cc`/`Cf` by category |
| 9 | Macro check matched only the part name (low) | Reasoning | Also check `[Content_Types].xml` (`vbaProject`, `macroEnabled`), read with a 1 MB cap and an encryption check first |
| 10 | Logs could carry file fragments (tracebacks, pypdf warnings) (low) | Reasoning | ERROR logs carry the exception type only (traceback at DEBUG); pypdf logger at ERROR |
| 11 | `"²".isdigit()` in `Content-Length` check caused a 500 (info; uvicorn blocks it first) | Yes | `isascii() and isdigit()` |
| — | SECURITY.md inaccuracies and stale statements (e.g. "cannot be left in processing", "never written to disk", Phase 1 header) | — | SECURITY.md rewritten |

The DOCX external-entity and entity-expansion probes confirmed the existing protections: the secret file was never read, and the "billion laughs" file failed in milliseconds. My first XXE test had assumed rejection; the real mechanism is that entities are not resolved, and the test was corrected to assert that.

**Before / after (same attack inputs)**

| Input | Before | After |
|---|---|---|
| TXT `a\n\n` × 10 MiB | ~20 min (extrapolated from timings) | Rejected (`document_too_complex`) in 2.8 s |
| DOCX, one cell with `gridSpan` 2³¹−1 | Memory exhaustion (16 GB tuple) | Extracted in 0.02 s |
| DOCX, 20,000 headings | 16.8 s | 2.2 s (style names also resolved once per document instead of an XPath search per paragraph) |
| PDF inflating to 80 MB | `no_extractable_text` (misleading) | `resource_limit_exceeded` in 0.5 s |

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1 -Backend` | 5/5 PASS; 239 tests (169 unit, 70 integration); 34 new tests |
| Python sources | All ASCII (escape sequences only) |
| Live server (scratch database): PDF, DOCX, PDF bomb | `processed` with 2 and 3 chunks; bomb `failed` with `resource_limit_exceeded` in 0.5 s; logs show metadata only, with no document text or filenames; server tree stopped |

**Known limitations (residual risk, documented in SECURITY.md)**

- Parsing runs in the API process. A slow PDF can occupy a worker for up to about 30 seconds, and memory is bounded only by input size and the budgets. Hard isolation (subprocess with CPU, memory and time limits) is required before untrusted uploads from real users.
- Homoglyphs are not normalized. Polyglot files that are valid as an allowed type are stored, but never executed or served.
- No delete or reprocess endpoints. Blob deletion will need reference counting.

**Exit criteria:** met. Every review finding is fixed or documented as residual risk, with regression tests for each fix, and SECURITY.md matches the code.

## Phase 2 completion report

**Status: COMPLETE.** Phase 2 delivered document upload, validation, text extraction, normalization and chunking with tenant isolation and bounded resource use. CI passed on every pushed milestone.

**Phase 2 goals (CLAUDE_DEVELOPMENT_GUIDE.txt §7) against what was delivered**

| Goal | Delivered | Milestone |
|---|---|---|
| Upload PDF, DOCX and TXT files | `POST /api/v1/documents` (development identity; not in production) | P2-M2 |
| Validate file type and size | Allowlist plus content signature, size and body limits, zip, macro and encryption checks | P2-M2, P2-M5 |
| Extract text and page-level metadata | PDF pages, DOCX headings as sections and tables, TXT paragraphs | P2-M3 |
| Normalize extracted content | Deterministic, idempotent normalization; invisible format characters removed | P2-M3, P2-M5 |
| Configurable chunking strategies | `structured` and `fixed`, settings validated, configuration recorded per document | P2-M4 |
| Preserve document ID, page, section, tenant and access metadata | Every chunk carries document ID, tenant ID, page, section and offsets. Document permissions arrive with RBAC (Phase 6); access today is tenant-scoped | P2-M1, P2-M4 |
| Track processing status and failures | `uploaded` → `processing` → `processed`/`failed` with 8 processing error codes; interrupted documents recoverable | P2-M3, P2-M5 |
| Make ingestion idempotent | Unique (tenant, SHA-256); identical re-upload returns the existing document; concurrent duplicates resolved | P2-M1, P2-M2 |
| Tests with synthetic sample documents | Generated multi-page PDFs, `python-docx` documents, hostile variants (encrypted, bombs, XXE, `gridSpan`) | P2-M2 to P2-M5 |

**Commits:** P2-M1 `1d549ee`, P2-M2 `6704107`, P2-M3 `02117b6`, P2-M4 `9bd5df7`, P2-M5 `bd41942`.

**Dependencies added in Phase 2:** `python-multipart` (uploads), `pypdf` (PDF text), `python-docx` and `lxml` (DOCX text). All are prebuilt wheels for Python 3.14.

**Architecture decisions:** ADR-014 (development identity), ADR-015 (content-addressed storage, tenant-scoped data), ADR-016 (in-request processing), ADR-017 (chunking).

**Tests:** 239 backend (169 unit, 70 integration) plus 27 frontend = 266, up from 72 at the end of Phase 1.

**Security considerations:** see [SECURITY.md](SECURITY.md); the P2-M5 review is summarized above.

**Manual verification steps** (from `apps/api`, with the API running):

1. `curl.exe -F "file=@<synthetic.pdf>" http://127.0.0.1:8000/api/v1/documents` → `201`, `status: processed`.
2. `curl.exe http://127.0.0.1:8000/api/v1/documents/<id>/chunks` → chunks with page numbers.
3. Upload the same file again → `200` with the same `id`.

**Recommended next phase:** Phase 3, embeddings and retrieval. It starts with an environment check (PostgreSQL and pgvector availability, a CPU-friendly local embedding model compatible with Python 3.14) and an embedding interface independent of any provider, plus a plan for your approval.

## Phase 3: Embeddings and Retrieval

Decisions approved 2026-11-14:
1. SQLite first behind interfaces; PostgreSQL + pgvector via Docker in P3-M4.
2. `fastembed` + ONNX Runtime.
3. One-time download of the pinned 64 MB model.
4. NumPy brute-force vector search on SQLite.

| Milestone | Scope | Status | Commit |
|---|---|---|---|
| P3-M1 | Embedding interface, pinned ONNX and hashing embedders, `chunk_embeddings`, embedding during processing, backfill CLI, readiness check | COMPLETE | `2691620` |
| P3-M2 | Vector index interface, exact brute-force semantic search, `POST /api/v1/search` with citations | COMPLETE | `d6e8781` |
| P3-M3 | FTS5 keyword search, hybrid (Reciprocal Rank Fusion), search modes | COMPLETE | `97a2b93` |
| P3-M4 | PostgreSQL + pgvector implementation (Docker Compose, CI service) | COMPLETE | `2b28388` |
| P3-M5 | Evaluation dataset, recall@k/MRR, chunk-size and top-k comparison, report | COMPLETE | `ce2117f` |

## P3-M1: Embeddings

**Scope:** embedding interface and implementations, vector storage, embedding during processing, backfill and download commands, readiness. No search yet.

**Dependency added:** `fastembed` 0.9.1 (ONNX Runtime embeddings). It pulls in 22 packages, including `onnxruntime` 1.32.0, `numpy` 2.5.4, `tokenizers`, `huggingface-hub` (used only by the download command) and `httpx`. All are prebuilt wheels for Python 3.14. The test suite still uses `httpx2`, and no deprecation warnings returned.

**Implemented**

- `app/embeddings/`:
  - The `Embedder` protocol.
  - A pinned model registry (`bge-small-en-v1.5` at revision `aa8f8b06…`, 384 dimensions, MIT).
  - `OnnxEmbedder`: lazy, thread-safe, local files only.
  - `HashingEmbedder`: deterministic and **non-semantic**, for tests.
  - The provider factory and `download_model`.
- `chunk_embeddings` table (migration `29b0c28209aa`, reviewed): primary key `(chunk_id, model_id)`, cascade from chunks, `tenant_id`, `dimensions`, float32 vector, index `(model_id, tenant_id)`.
- `EmbeddingRepository` and `EmbeddingService`.
- Processing embeds chunks after the `processed` commit as a separate unit of work. On failure it rolls back, logs `document embedding skipped`, and keeps the document `processed`.
- CLI: `python -m app.cli download-embedding-model`, `python -m app.cli embed-missing`.
- Readiness adds `checks.embeddings` (model files present).
- Settings: `EASA_EMBEDDING_PROVIDER`, `EASA_EMBEDDING_MODEL_DIR`, `EASA_EMBEDDING_BATCH_SIZE`. Tests default to `hashing`.
- Docs: API spec (readiness), DATABASE_DESIGN (vector table and rules), LLD, SECURITY, DEVELOPMENT_GUIDE (commands and settings), HLD, README, `.env.example`, ADR-018.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `uv run ruff format --check .` / `uv run ruff check .` | Clean |
| `uv run pytest` (before the model download) | 256 passed, 2 skipped (real-model tests) |
| Migration on a scratch database: autogenerate, `upgrade`, `check`, `downgrade -1`, `upgrade` | Clean; head `29b0c28209aa` |
| `uv run python -m app.cli download-embedding-model` | Downloaded in 19 s to `var/models/bge-small-en-v1.5/aa8f8b06…`: 6 files, `model_optimized.onnx` 66.5 MB; the files are git-ignored (`var/`, confirmed with `git check-ignore`) |
| `uv run pytest tests/model` | 2 passed: normalized 384-dimension vectors; "How much vacation time do staff get?" scores closer to the annual-leave sentence than to the travel sentence, without shared words |
| Live server with the real model (scratch database) | Readiness `ready` with `embeddings: ok`; PDF and DOCX `processed` (2.7 s for the first upload including the model load, 0.8 s for the second); 5 vectors stored under `bge-small-en-v1.5@aa8f8b060edb`, 384 dimensions, 1,536 bytes each; server tree stopped |

Fixed during the work:

- Two new tests queried the database after the test client had closed the app, which reopened pooled connections and caused a `ResourceWarning`. The fixtures now dispose the engine.
- A test passed a string where a UUID was required.
- `.env.example` got a literal `` `n`` from a PowerShell escaping slip.

**Known limitations**

- No search yet (P3-M2).
- Real-model tests are skipped in CI, which never downloads the model.
- Embedding happens during the upload request, which adds latency.
- `embed-missing` operates across tenants and is a server-side command only.

**Exit criteria:** met. Processed documents get versioned vectors from a pinned local model, failures are recoverable, there is no network access at runtime, and both the deterministic and the real-model paths are tested.

## P3-M2: Semantic search

**Scope:** vector-index interface, exact brute-force implementation, search service and endpoint with citations. No keyword or hybrid search (P3-M3), no PostgreSQL (P3-M4). No new dependencies, no migrations.

**Implemented**

- `app/retrieval/`:
  - The `VectorIndex` protocol; its contract requires tenant, status and model filtering before scoring.
  - `BruteForceVectorIndex`: a single filtered SQL query, rows streamed in batches of 5,000, NumPy scoring, a running top-k, ties broken by chunk ID.
- `Embedder.embed_query`: the ONNX implementation uses fastembed's query handling; the hashing embedder treats the query like a passage.
- `SearchService`:
  - Normalizes the query; rejects empty queries (`empty_query`); returns `503 embeddings_unavailable` when the model is missing.
  - Enriches hits through a tenant-scoped `DocumentRepository.chunks_with_documents`.
  - Logs metadata only; the query text is never logged.
- `POST /api/v1/search`: `{query (1–1000), top_k (1–50, default 5)}`, unknown fields rejected. Returns `{model_id, results: [{score, text, citation}]}`. Mounted only outside production.
- Docs: API spec section 3.5, LLD, SECURITY, HLD, README, DEVELOPMENT_GUIDE (search example), ADR-019.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `uv run ruff format --check .` / `uv run ruff check .` | Clean |
| `uv run pytest` (model downloaded locally) | 283 passed (179 unit, 101 integration, 3 real-model); 25 new tests |
| Real-model test through the API | "How much vacation time do staff get?" ranks the handbook's "Leave" section first, without shared words |
| Live server with the real model (scratch database), 4 natural-language queries | All top hits correct: vacation → Leave (0.684); work from home → Remote Work (0.618); expense receipts deadline → travel.pdf page 2 (0.832); seat class → travel.pdf page 1 (0.707). Server-side search took ~30 ms; no query text in the log; server tree stopped |

**Known limitations**

- Search cost is linear in the tenant's chunk count; fine for the demo corpus, not for large ones (pgvector in P3-M4).
- Semantic search only. Exact terms such as codes or names may rank poorly until keyword and hybrid search arrive (P3-M3).
- Browsers cannot call search yet (CORS allows `GET` only). There is no authentication (development identity).
- Scores are cosine similarities, not calibrated relevance probabilities.

**Exit criteria:** met. Tenant-isolated, exact semantic search with citations works end to end with the real model, and isolation and filtering are covered by tests.

## P3-M3: Keyword and hybrid search

**Scope:** SQLite FTS5 keyword index and BM25 search, Reciprocal Rank Fusion hybrid, and a `mode` parameter on `POST /api/v1/search`. No PostgreSQL keyword search (P3-M4), no evaluation dataset (P3-M5). No new dependencies.

**Implemented**

- `app/db/fts.py` and migration `6d544dac46b3` (hand-written; SQLite only, a no-op elsewhere):
  - The external-content FTS5 table `chunk_fts` over `document_chunks.text`, tokenizer `porter unicode61 remove_diacritics 2`.
  - Insert, delete and update triggers; existing chunks indexed with `rebuild`.
  - `migrations/env.py` excludes the FTS tables from autogenerate (`include_name`), so `alembic check` stays clean.
- `app/retrieval/keyword.py`:
  - `build_match_query`: at most 32 distinct word tokens, each quoted, joined with `OR`, so user text is never parsed as FTS5 syntax.
  - `SqliteKeywordIndex`: BM25 search with tenant and processed-status filters in the same query; `503 keyword_search_unavailable` on other databases.
- `app/retrieval/hybrid.py`: `reciprocal_rank_fusion` (`k = 60`, ties broken by chunk ID).
- `SearchService`: modes `semantic` (default), `keyword` (needs no embedder; `model_id` is `null`) and `hybrid` (fuses `max(4 × top_k, 20)` candidates from each ranking). The log line now includes the mode.
- `POST /api/v1/search`: optional `mode`; the response includes `mode`.
- CLI: `python -m app.cli rebuild-keyword-index` (for use after `VACUUM`).
- Tests: `create_schema` helper (tables plus keyword index, like migrations); keyword index tests (stemming, ranking, hostile FTS syntax, tenant and status isolation, trigger synchronization, rebuild command); RRF and query-building unit tests; search API tests for all modes; migration tests for the FTS index (parity with the app module, downgrade).
- Docs: API spec section 3.5, DATABASE_DESIGN section 8.1 (and the migration chain, missing `29b0c28209aa` since P3-M1), LLD section 2.6e and test counts, SECURITY (search controls, now under their own heading, and the BM25 cross-tenant statistics note), DEVELOPMENT_GUIDE (mode example, keyword index section), HLD, README, ADR-020.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1 -Backend` | All checks passed: `uv sync --locked`, ruff format, ruff check, pytest, Alembic upgrade + `alembic check` on a temporary database ("No new upgrade operations detected") |
| `uv run pytest` (model downloaded locally) | 323 passed (191 unit, 129 integration, 3 real-model); 40 new tests |
| FTS5 behaviour probes (scratch database) | Triggers fire on foreign-key cascade deletes; Porter stemming matches "leaves" for "leave" |
| `uv run alembic upgrade head` (development database) | Upgraded to `6d544dac46b3` |
| `uv run python -m app.cli rebuild-keyword-index` (development database) | Exit code 0, `keyword index rebuilt` |
| Live server with the real model, same queries in all three modes | "How much vacation time do staff get?": keyword returns nothing (no shared words), semantic and hybrid return the "Leave" section. "receipts deadline": all three modes return travel.pdf page 2. Server tree stopped |

**Known limitations**

- BM25 term statistics span all tenants, so keyword scores are slightly influenced by other tenants' text (rows are still filtered). Documented in SECURITY.md; to be revisited before real multi-tenant use.
- Keyword search exists only on SQLite until P3-M4.
- The exact-term comparison in the live test was not discriminative: the document with a code ("HR-217") became a single chunk, so every mode found it. P3-M5 needs evaluation cases where exact terms actually separate the modes.
- `OR` matching favours recall; hybrid scores are rank-based and not comparable with the other modes.

**Exit criteria:** met. Keyword and hybrid search work end to end with tenant isolation, injection-safe queries and an index that follows chunk changes, all covered by tests.

## P3-M4: PostgreSQL + pgvector

**Scope:** PostgreSQL 18 + pgvector as a second database backend (Docker Compose), vector and keyword search implementations for it, PostgreSQL tests and a CI service container. SQLite stays the default. No approximate (HNSW) index (P3-M5), no frontend changes.

**Environment and approvals:** Docker Desktop 29.9.3 (Compose v5.7.0, WSL 2) was already installed. Pulled `pgvector/pgvector:0.8.7-pg18` (158 MB compressed, digest `sha256:38681dc6…`). New Python dependencies: `psycopg[binary]` 3.3.9 (with `psycopg-binary` and, on Windows, `tzdata`) and `pgvector` 0.5.1. Port 5432 is used by another local project's container, which was not touched; EASA uses 5433.

**Implemented**

- `compose.yaml` (`postgres` service on `127.0.0.1:5433`, named volume, `pg_isready` healthcheck; password from the git-ignored root `.env`) and a root `.env.example`.
- `EmbeddingVector` column type: bytes in Python; a blob on SQLite, an undimensioned pgvector `vector` on PostgreSQL.
- Migration `e4353f12b34f` (hand-written, PostgreSQL only): `vector` extension, `bytea` → `vector` conversion (derived vectors deleted), GIN index on `to_tsvector('english', text)`; reversible. `env.py` renders the new type portably and ignores the GIN index in autogenerate.
- `PgvectorIndex`: exact cosine search in the database with tenant, status, model and dimension filters.
- `PostgresKeywordIndex`: `to_tsquery` from quoted word tokens joined with `|`, ranked with `ts_rank_cd`; the SQL is a module constant, so a test can `EXPLAIN` it.
- `build_indexes(session)` chooses implementations from the dialect; `KeywordIndex` protocol moved to `app/retrieval/base.py`.
- `tests/postgres` (44 tests, throwaway databases, skipped without `EASA_TEST_POSTGRES_URL`); 6 new SQLite-side tests (tsquery building, factory, cross-backend 503s).
- CI: `pgvector/pgvector:0.8.7-pg18` service container; tests run with `EASA_TEST_POSTGRES_URL`; `alembic upgrade head` + `alembic check` also run on PostgreSQL.
- Docs: DATABASE_DESIGN (section 9 rewritten, 8 and 8.1), DEVELOPMENT_GUIDE section 6c, LLD section 2.6f and test table, API spec (score meaning, 503 text), SECURITY (PostgreSQL controls, local database, supply chain), HLD, README, `apps/api/.env.example`, ADR-021.

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `docker compose up -d postgres` | Healthy; PostgreSQL 18.7, pgvector 0.8.7 available; bound to `127.0.0.1:5433` |
| `alembic upgrade head`, `alembic check`, `downgrade base`, `upgrade head` on PostgreSQL | All succeeded; "No new upgrade operations detected"; `vector` column type `vector`; GIN index `to_tsvector('english'::regconfig, text)` |
| `scripts\check.ps1 -Backend` with `EASA_TEST_POSTGRES_URL` set | All checks passed (pytest including the PostgreSQL suite) |
| `uv run pytest` with PostgreSQL | 373 passed (195 unit, 131 integration, 3 real-model, 44 PostgreSQL); the PostgreSQL suite passed three times in a row; no throwaway databases left behind |
| `uv run pytest` without PostgreSQL | 329 passed, 44 skipped |
| First parity run | Two test-design failures, fixed: (1) the hashing embedder produces exactly tied scores and float32 rounding (about 2e-8) ordered ties differently at the top-k cut, so the test now compares complete rankings as groups of tied scores; (2) on empty tables the planner reasonably used the documents tenant index, so the GIN test now uses 2,000 chunks, `ANALYZE` and a rare term |
| Live API on PostgreSQL with the real model (synthetic handbook and travel fixtures) | Readiness `ready`. Vacation query: semantic and hybrid return "Leave" (semantic 0.6843, same as SQLite in P3-M2), keyword returns nothing. "receipts deadline": all modes return travel.pdf page 2. "seat class on flights": all modes return travel.pdf page 1 |
| `python -m app.cli embed-missing` on PostgreSQL | After deleting all 5 vectors, restored 5 vectors of 384 dimensions; search worked again |
| Server log | 10 `search completed` lines with metadata only; none of the query texts appear. Server tree stopped |

**Known limitations**

- Exact vector search only: linear in a tenant's chunk count. HNSW (with iterative scans for filtered queries) is evaluated in P3-M5.
- Keyword scores are backend-specific (BM25 vs `ts_rank_cd`) and not comparable across backends; rankings can differ slightly.
- The container image is pinned by tag, not digest. Database connections are unencrypted (localhost only).
- Converting an existing PostgreSQL database deletes its vectors; run `embed-missing` afterwards.

**Exit criteria:** met. The full application runs on PostgreSQL + pgvector with the same API and migrations, results match the SQLite implementation up to float rounding, and CI tests both backends.

**Post-push note:** CI passed for `2b28388`, but GitHub job logs need authentication, so whether the 44 PostgreSQL tests ran or were skipped could not be confirmed. P3-M5 adds a guard that makes CI fail if they are skipped.

## P3-M5: Retrieval evaluation and Phase 3 report

**Scope:** a synthetic labelled dataset, retrieval metrics, an evaluation runner and CLI, a comparison of search modes and chunk settings on SQLite and PostgreSQL, an exact-versus-HNSW benchmark, `docs/EVALUATION.md`, a CI guard for the PostgreSQL tests, and the Phase 3 report. No application behaviour changes, no new dependencies, no downloads.

**Implemented**

- CI guard: with `EASA_REQUIRE_POSTGRES_TESTS=1` (set in CI) a missing `EASA_TEST_POSTGRES_URL` fails the PostgreSQL tests instead of skipping them (verified locally: 46 failures/errors without the URL).
- Dataset in `apps/api/eval/`: 12 synthetic "Larkspur Analytics" policy documents (24 KB) and 60 labelled queries (24 paraphrase, 15 exact, 21 keyword), each with an evidence phrase; validated by a unit test.
- `app/evaluation/`: `dataset.py`, `metrics.py` (recall@k, reciprocal rank), `runner.py` (fresh migrated database per chunk setting, upload through `DocumentService`, search through `SearchService`, vector-completeness check), `report.py` (JSON and Markdown), `hnsw.py` (synthetic-vector benchmark).
- `app/db/migrate.py` `upgrade_to_head(url)`; `migrations/env.py` accepts a URL in `config.attributes` and then leaves logging to the caller.
- CLI: `evaluate [--backend] [--configs]` and `evaluate-hnsw [--vectors] [--tenants] [--queries] [--noise]`; PostgreSQL URL from `EASA_EVAL_POSTGRES_URL`.
- Tests: 17 unit (metrics, dataset validation), 5 integration (runner, reports, missing-vector refusal, CLI), 2 PostgreSQL (semantic parity with SQLite, small HNSW benchmark).
- Docs: `docs/EVALUATION.md` (new), ADR-022, LLD section 2.6g, DEVELOPMENT_GUIDE section 6d, SECURITY, DATABASE_DESIGN section 9, HLD, README.

**Results:** see [EVALUATION.md](EVALUATION.md). In short: hybrid is the most robust mode (default chunking: R@1 0.817, R@3 0.967, MRR 0.887 on SQLite); keyword fails on paraphrases and semantic misses codes; smaller chunks help semantic and hurt keyword; semantic results are identical on PostgreSQL, whose keyword ranking is weaker on exact terms; HNSW is not adopted (ADR-022).

**Verification (executed 2026-11-14)**

| Command / check | Result |
|---|---|
| `uv run ruff format --check .` / `uv run ruff check .` | Clean |
| `uv run pytest` with `EASA_TEST_POSTGRES_URL` | 397 passed (212 unit, 136 integration, 3 real-model, 46 PostgreSQL); no throwaway databases left |
| `uv run pytest` without PostgreSQL | 351 passed, 46 skipped |
| `uv run pytest tests/postgres` with `EASA_REQUIRE_POSTGRES_TESTS=1` and no URL | Fails (2 failed, 44 errors), as intended |
| `python -m app.cli evaluate --configs all` (real model) | Exit 0 in 56 s; results in EVALUATION.md section 4 |
| `python -m app.cli evaluate --backend postgres --configs all` | Exit 0 in 69 s; semantic metrics identical to SQLite for all 6 settings |
| `python -m app.cli evaluate-hnsw --tenants 10` and `--tenants 1` | Exit 0; results in EVALUATION.md section 6 |
| First HNSW benchmark design | Rejected after two runs: tightly clustered vectors with queries copied from stored points produced near-tied exact top-10 lists, so recall (0.16–0.67, lower with less noise) measured tie-breaking. Replaced by low-intrinsic-dimension data with fresh queries |
| First small HNSW test | Failed on `index_used`: with 2,000 vectors the planner correctly prefers an exact scan. The test now asserts that recall is 1.0 whenever the index is not used |

**Known limitations**

- The evaluation is optimistic (same author for corpus and labels, small clean corpus, one answer per query) and small (60 queries). See EVALUATION.md section 8.
- Overlap was not varied separately (150 characters for fixed windows).
- HNSW numbers use synthetic vectors; latencies come from a laptop with Docker and varied 2–3 times between runs.

**Exit criteria:** met. Retrieval quality is measured with a reproducible, validated dataset; modes, chunk settings, backends and HNSW are compared, and the decisions are recorded.

## Phase 3 completion report

**Status: COMPLETE.** Phase 3 delivered local embeddings, tenant-isolated semantic, keyword and hybrid search with citations on SQLite and PostgreSQL + pgvector, and a retrieval evaluation.

**Phase 3 goals (CLAUDE_DEVELOPMENT_GUIDE.txt, Phase 3) against what was delivered**

| Goal | Delivered | Milestone |
|---|---|---|
| Provider-independent embedding interfaces | `Embedder` protocol; pinned local ONNX model (bge-small-en-v1.5) and a deterministic test embedder | P3-M1 |
| Generate and persist embeddings | Embedding during processing, versioned `model_id`, backfill command, readiness check | P3-M1 |
| Introduce PostgreSQL and pgvector when available | Docker Compose service, portable vector column, PostgreSQL migration, pgvector search, CI service container | P3-M4 |
| Semantic similarity search | `POST /api/v1/search`, exact search on both backends | P3-M2, P3-M4 |
| Metadata and authorization filters | Tenant, document status, model and dimension filters inside every search query; tested on both backends. Role- and document-level permissions arrive with RBAC (Phase 6) | P3-M2 to P3-M4 |
| Keyword search and hybrid retrieval | FTS5 BM25 (SQLite), PostgreSQL full-text search, reciprocal rank fusion; injection-safe query building | P3-M3, P3-M4 |
| Evaluate chunk size, overlap, top-k and retrieval quality | 6 chunk settings × 3 modes × 60 labelled queries, recall@1/3/5/10 and MRR; overlap only at one value | P3-M5 |
| Citations with document and page references | Filename, document ID, chunk index, page, section and offsets on every result | P3-M2 |
| Unauthorized content cannot enter model context | Other tenants' and unprocessed documents are filtered before scoring and never returned (tests in every mode and backend). No model context exists yet; Phase 4 must only use these results | P3-M2 to P3-M4 |

**Commits:** P3-M1 `2691620`, P3-M2 `d6e8781`, P3-M3 `97a2b93`, P3-M4 `2b28388`, P3-M5 `ce2117f`. CI passed for `ce2117f` with the PostgreSQL guard enabled, which proves the PostgreSQL tests ran in CI.

**Dependencies added in Phase 3:** `fastembed` (ONNX Runtime embeddings), `psycopg[binary]` (PostgreSQL driver), `pgvector` (vector type). Container image: `pgvector/pgvector:0.8.7-pg18`. Model: `Qdrant/bge-small-en-v1.5-onnx-Q` at a pinned revision (64 MB, downloaded once on request).

**Architecture decisions:** ADR-018 (embeddings), ADR-019 (vector index interface), ADR-020 (keyword and hybrid search), ADR-021 (PostgreSQL + pgvector), ADR-022 (exact search over HNSW for now).

**Tests:** 397 backend (212 unit, 136 integration, 3 real-model, 46 PostgreSQL) plus 27 frontend = 424, up from 266 at the end of Phase 2.

**Security considerations:** see [SECURITY.md](SECURITY.md). Main residual risks: SQLite BM25 statistics span tenants (not PostgreSQL); the development identity is still the only identity; the container image is pinned by tag.

**Manual verification steps** (from `apps/api`, with the API running and the model downloaded):

1. Upload a synthetic document: `curl.exe -F "file=@<synthetic.txt>" http://127.0.0.1:8000/api/v1/documents`.
2. Search in each mode with a JSON body file, as in DEVELOPMENT_GUIDE section 3: `{"query": "...", "top_k": 3, "mode": "hybrid"}` → results with citations.
3. Run `uv run python -m app.cli evaluate` → a report in `var/eval/`.

**Recommended next phase:** Phase 4, grounded RAG answering. Open decisions to settle in its plan: the model provider (a free local option such as Ollama, which is not installed), whether the API's default search mode becomes `hybrid`, and the chunk size, judged by answer quality.

## Phase 4: Grounded RAG Answering

Plan approved on 2026-11-14 with the recommended options: a provider-independent chat model interface with a deterministic fake for tests, Ollama running in Docker as the real provider (model chosen and downloads approved in P4-M3), and `hybrid` as the default search mode (P4-M2).

| Milestone | Scope | Status | Commit |
|---|---|---|---|
| P4-M1 | Chat model interface, fake model, Ollama adapter, model settings, readiness check | COMPLETE | `0474246` |
| P4-M2 | Grounded answer service and `POST /api/v1/answers`; bounded context, citations, insufficient-evidence handling; search default `hybrid` | COMPLETE | `83b25ff` |
| P4-M3 | Local model: llama.cpp server in Docker with a pinned Qwen2.5 1.5B GGUF (approved instead of Ollama, ADR-025), live tests, latency | COMPLETE | `2a6f715` |
| P4-M4 | Conversation context (conversations and messages, bounded history) | COMPLETE | the commit that adds this row |
| P4-M5 | Answer evaluation (unanswerable, false-premise and prompt-injection cases) and Phase 4 report | NOT STARTED | |

## P4-M1: Chat model interface

**Scope:** the model port and its adapters, configuration and readiness. No answer endpoint (P4-M2), no real model or downloads (P4-M3).

**Environment:** 4-core i5-1135G7, 16 GB RAM, Intel Iris Xe (no usable GPU); Docker has 8 CPUs and 8 GB. Ollama is not installed. `httpx` 0.28.1 was already installed (through fastembed) and is now a declared dependency; nothing new was downloaded.

**Implemented**

- `app/llm/`: the `ChatModel` protocol with `ChatMessage`, `ChatResult`, `ModelUnavailableError` and `ModelResponseError`; `FakeChatModel` (fixed or computed replies, call recording); `OllamaChatModel` (`/api/chat` non-streaming, `/api/tags` availability, no proxies, no redirects, timeouts, 20,000-character reply cap, errors without prompt text); `build_chat_model`.
- Settings: `model_provider` (`none` default, `fake`, `ollama`), `ollama_base_url` (validated `http(s)://host[:port]`), `model_name` (required and pattern-checked for Ollama), `model_timeout_seconds`, `model_max_output_tokens`, `model_temperature`; `fake` is rejected in production.
- `app.state.chat_model`; the Ollama client is closed on shutdown.
- Readiness gains `checks.model` (`ok`, `unavailable`, `disabled`); a configured but unavailable model makes readiness `503`, a disabled one does not. The web client ignores the new key.
- Tests: 37 unit (fake model, Ollama adapter against `httpx.MockTransport`, settings, factory, readiness), 2 integration (fake model ready; unreachable Ollama → `503`); 4 readiness assertions in 3 test files updated for the new key.
- Docs: API spec section 3.2, LLD section 2.6h, SECURITY (chat model controls), DEVELOPMENT_GUIDE configuration, `apps/api/.env.example`, HLD, README, ADR-023.

**Verification (executed 2026-11-14 and 2026-11-15)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1 -Backend` with PostgreSQL and `EASA_REQUIRE_POSTGRES_TESTS=1` | All checks passed |
| `uv run pytest` with PostgreSQL | 436 passed (249 unit, 138 integration, 3 real-model, 46 PostgreSQL); no throwaway databases left |
| `uv run pytest` without PostgreSQL | 390 passed, 46 skipped |
| Live server with `EASA_MODEL_PROVIDER=fake` | `GET /api/v1/health/ready` → `{"status":"ready","checks":{"database":"ok","embeddings":"ok","model":"ok"}}`; server tree stopped |
| `EASA_MODEL_PROVIDER=fake` with `EASA_ENVIRONMENT=production` | Settings refuse to load: `model_provider "fake" is not allowed in production` |
| First run of the checks on 2026-11-15 | Stalled because Docker Desktop was not running after a restart; the run was stopped, Docker Desktop and the `easa` container were started again, and the checks were rerun |

**Known limitations**

- The Ollama adapter is tested only against a mock transport; it meets a real server in P4-M3.
- Non-streaming only. When Ollama is configured but stopped, the whole API reports not ready, although search still works (ADR-023).

**Exit criteria:** met. Answer generation can be built against a tested, provider-independent interface, and model availability is visible in readiness.

## P4-M2: Grounded answers

**Scope:** an answer service and `POST /api/v1/answers` built against the fake model; the search API's default mode becomes `hybrid`. No real model (P4-M3), no conversation history (P4-M4). No new dependencies.

**Implemented**

- `app/services/answers.py` `AnswerService`: hybrid retrieval (default 5 chunks, at most 10) → numbered sources within a 6,000-character budget → the chat model → reply checks. No evidence → `insufficient_evidence` without a model call; marker, empty or uncited replies → `insufficient_evidence` with a reason; citations of unknown sources removed. Rules only in the system message; sources in `<source>` elements with tag-like text escaped and attributes HTML-escaped. Model errors → `503 model_unavailable` / `502 model_error`; no model configured → `503 answers_unavailable`. One metadata-only log line.
- `POST /api/v1/answers` (`AnswerRequest`, `AnswerResponse`), mounted only outside production.
- `extractive_reply` for `EASA_MODEL_PROVIDER=fake`: quotes the first sentence of source S1 with its citation, so the pipeline can be tried without a model.
- Search: default `mode` is `hybrid` in the API schema and the service.
- Tests: 23 unit (citations, refusals, prompt separation, escaping of hostile documents and attributes, context budget, model failures, bounded `top_k`, no logging of questions or answers, extractive fake) and 14 integration (end-to-end answer with citations, no documents, model refusal, other tenant's documents never in the prompt, injected `</source>` text, validation, no model → `503`, not mounted in production, no question in logs). Tests that relied on the old `semantic` default now request it explicitly (one integration, one real-model, one PostgreSQL test).
- Docs: API spec section 3.6 and search default, LLD section 2.6i, SECURITY (answer controls and residual risks), DEVELOPMENT_GUIDE (answer example), README, HLD, EVALUATION.md (recommendation 1 done), ADR-024.

**Verification (executed 2026-11-15)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1 -Backend` with PostgreSQL and `EASA_REQUIRE_POSTGRES_TESTS=1` | All checks passed |
| `uv run pytest` with PostgreSQL | 473 passed (272 unit, 152 integration, 3 real-model, 46 PostgreSQL); no throwaway databases left |
| `uv run pytest` without PostgreSQL | 427 passed, 46 skipped |
| Live server (`fake` provider, `hashing` embedder, scratch database) | Readiness `ready` with `model: ok`. Before any upload: `insufficient_evidence` / `no_results` / `model_id: null`. After uploading the synthetic handbook and travel fixtures: "How many days of annual leave do employees get?" → answered, citing handbook.docx section "Leave"; "When must receipts be submitted?" → answered, citing travel.pdf page 2. `top_k: 50` → `422`. Search without `mode` → `hybrid`. 3 `answer completed` log lines; neither question appears in the log. Server tree stopped |
| First test runs | Two answer tests failed and were fixed: a real bug (escaping lowercased `</SOURCE>`; it now escapes only `<` and keeps the text) and a test bug (it looked for "falcon" in the whole prompt, which includes the question). After the hybrid default, one integration, one real-model and one PostgreSQL test failed because they relied on the old default; they now request `semantic` explicitly |

**Known limitations**

- No real model yet: the `fake` provider quotes a sentence and does not answer the question. Prompt following, citation accuracy and injection resistance are untested with a real model until P4-M3 and P4-M5.
- The citation check verifies that a provided source is cited, not that it supports the claim.
- With the hybrid default, the real-model paraphrase example ("How much vacation time do staff get?") no longer ranks the Leave section first in search; `semantic` still does (EVALUATION.md section 4.3).
- Browsers cannot call the endpoint yet (CORS allows `GET` only).

**Exit criteria:** met. Questions are answered only from the caller's tenant with checked citations, unsupported replies are withheld, and the behaviour is covered by tests.

## P4-M3: Local chat model

**Scope:** a real model for answers, running locally on the CPU. After comparing runtimes and models (sizes and licence files read from the registries), the approved choice was the llama.cpp server in Docker with Qwen2.5 1.5B Instruct instead of the planned Ollama image (ADR-025). No conversation history (P4-M4), no answer evaluation (P4-M5).

**Downloads (approved):** `ghcr.io/ggml-org/llama.cpp:server-b12407` (282 MB compressed, 1.16 GB on disk, index digest `sha256:89fe93c2…`) and `qwen2.5-1.5b-instruct-q4_k_m.gguf` (1,117,320,736 bytes) from `Qwen/Qwen2.5-1.5B-Instruct-GGUF` at revision `91cad511…`, SHA-256 verified. No new Python dependencies.

**Implemented**

- `app/llm/registry.py`: the pinned model file, `download_chat_model` and `verify_model_file` (size and SHA-256); CLI `download-chat-model`.
- `app/llm/llamacpp.py` `LlamaCppChatModel` (OpenAI-compatible chat completions; readiness via `/health` and `/v1/models`) and `app/llm/http.py` (client rules and error mapping shared with the Ollama adapter, which was refactored onto it).
- Settings: `model_provider = "llamacpp"`, `llamacpp_base_url` (validated like the Ollama URL), `chat_model_dir`; `model_name` required for both HTTP providers.
- `compose.yaml`: `llm` service under the `llm` profile, `127.0.0.1:8082`, model directory mounted read-only, 4 threads, 4,096-token context, healthcheck.
- Answer prompt: `ANSWER_REMINDER` repeated after the question, and case-insensitive detection of the insufficient-evidence marker (see the probe results below). Token counts are now logged for declined and uncited replies too.
- Tests: 29 unit (adapter against `httpx.MockTransport`, file verification, settings, prompt reminder, marker case) and 4 live tests in `tests/llm` (skipped without `EASA_TEST_LLM_URL`).
- Docs: DEVELOPMENT_GUIDE section 6e, LLD, API spec readiness, SECURITY (supply chain, residual risks seen with the real model), `apps/api/.env.example`, README, HLD, ADR-025.

**Verification (executed 2026-11-15)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1 -Backend` with PostgreSQL, the CI guard and the live model | All checks passed |
| `uv run pytest` with PostgreSQL and `EASA_TEST_LLM_URL` | 506 passed (301 unit, 152 integration, 3 real-embedding, 46 PostgreSQL, 4 live model); no throwaway databases left |
| `uv run pytest` without either | 456 passed, 50 skipped |
| `download-chat-model` | Downloaded and verified in 21 s (see the first attempt below) |
| `docker compose --profile llm up -d llm` | Healthy after 66 s (model load about 55 s); serves `qwen2.5-1.5b-instruct-q4_k_m`; bound to `127.0.0.1:8082`; about 780 MB memory |
| Prompt probe: 8 questions over two synthetic sources, temperature 0, strict scoring (right source label and key fact, or a refusal) | Original prompt 4/8 (3 answers without citations, 1 incomplete); first reminder 6/8 (one junk reply listing file names, one wrong source label); adopted reminder 7/8 (one correct but incomplete answer). All 3 unanswerable questions were declined in every variant |
| End-to-end through the API (real embeddings, real model, synthetic handbook and travel fixtures, scratch database) | Leave question: answered correctly ("20 days", handbook section Leave) in 7.2 s, and 7.8 s when repeated. CEO question: declined in 6.0 s. Receipts question: withheld as `no_valid_citations` (17.2 s), a lost correct answer. Work-from-home question: "answered" in 16.3 s by listing facts from all 5 sources with valid citations, mostly irrelevant. Prompt 376 tokens. No question text in the log; API server stopped |
| First download attempt | Stalled at 0 bytes through Hugging Face's Xet transfer backend while a 5 MB plain HTTPS range request worked; restarted with `HF_HUB_DISABLE_XET=1` (same file and hash check) and finished in 21 s. Documented in DEVELOPMENT_GUIDE section 6e |
| Image pull | Slow from `ghcr.io` (about 56 KB/s measured on the largest layer); a stalled first pull was stopped and restarted, and finished |
| First full run with the live model | 2 failures in unrelated tests: the live-test fixture never closed the model's HTTP client, and the garbage-collected socket raised a `ResourceWarning` (warnings are errors) during later tests. The fixture now closes the client |

**Known limitations**

- Answer quality with a 1.5B model is uneven: correct answers are sometimes withheld for missing citations, and some answers dump unrelated cited facts or cite the wrong source; the citation check cannot detect the last two. P4-M5 measures this and evaluates fixes (fewer chunks, a per-sentence support check).
- 6–17 s per answer on 4 CPU cores; one request at a time.
- Image pinned by tag, not digest. The `llm` container is left running after this milestone; stop it with `docker compose --profile llm stop llm`.

**Exit criteria:** met. Answers come from a real, pinned, locally running model through the same interface, readiness reflects it, and its behaviour on probe questions is measured and recorded.

## P4-M4: Conversations

**Scope:** stored conversations with follow-up questions, as designed and approved before implementation (ADR-026). No answer evaluation (P4-M5), no frontend.

**Implemented**

- Migration `c0002f4a144e` (autogenerated, reviewed): `conversations` (tenant, owner, timestamps, index for recent conversations) and `conversation_messages` (position unique per conversation, role check, content, status, reason, JSON sources with citation metadata only, model ID; cascade delete).
- `ConversationRepository` (every query by tenant and owner) and `ConversationService` (create, list, get, ask, delete; 50-turn limit; a question and its reply stored together only after a successful answer; concurrent turns → `409 conversation_busy`).
- `AnswerService` follow-ups: `Turn`, `retrieval_query` (previous question + new one, within 1,000 characters), `build_history` (last 2 turns, 1,500 characters, old citation markers removed) in an escaped `<history>` element, system rule 6 (history is not evidence), and an explicit empty-question check.
- Endpoints: `POST/GET /api/v1/conversations`, `GET/DELETE /api/v1/conversations/{id}`, `POST /api/v1/conversations/{id}/messages`; development only. `to_answer_response` shared with the answers route.
- Tests: 7 unit (retrieval query, history selection and budget, prompt placement, escaping, empty follow-up), 15 integration (storage without chunk text, follow-up prompt contains history, own-only lists, other user and other tenant → `404` for get, ask and delete, delete cascade, model failure stores nothing, turn limit, validation, not mounted in production, no content in logs), 1 PostgreSQL round trip. Migration and metadata tests updated for the new head and tables; the PostgreSQL cleanup fixture now also empties conversations.
- Docs: DATABASE_DESIGN section 1.2a and migration chain, API spec section 3.7, LLD section 2.6j, SECURITY (conversation controls and residual risks), DEVELOPMENT_GUIDE example, README, HLD, ADR-026.

**Verification (executed 2026-11-15)**

| Command / check | Result |
|---|---|
| `scripts\check.ps1 -Backend` with PostgreSQL, the CI guard and the live model | All checks passed (including `alembic check` on a temporary SQLite database) |
| `uv run pytest` with PostgreSQL and `EASA_TEST_LLM_URL` | 529 passed (308 unit, 167 integration, 3 real-embedding, 47 PostgreSQL including `alembic check` on PostgreSQL with the new tables, 4 live model); no throwaway databases left |
| `uv run pytest` without either | 478 passed, 51 skipped |
| Live probe with the real model (two documents from the synthetic evaluation corpus, scratch database) | Turn 1 "How many days of annual leave do full-time employees get?" → answered, 25 days, leave_policy.txt (42.8 s). Turn 2 "Can unused ones be carried over?" → answered "up to five unused days … [S1]" (31.2 s); the same question without history → "Unused days may be carried over into the next year. [S1]" (17.0 s, less specific). Turn 3 "Until when do I have to use them?" → insufficient evidence both with history (27.2 s) and without (68.5 s), although the answer (end of March) is in the document. Stored positions 0–5 with roles and statuses as expected; stored sources had only `label` and `citation`. 5 `conversation turn stored` lines and no question text in the log; API server stopped |
| First full run | One failure: the metadata test listed the old set of tables; updated |

**Known limitations**

- Latency with larger chunks: 17–69 s per answer in the live probe (6–17 s with the smaller fixture chunks in P4-M3), approaching the 120 s model timeout. Fewer or shorter chunks are a P4-M5 candidate.
- Follow-ups that need the earlier answer rather than the earlier question can still fail (turn 3 above).
- Chat history has no retention limit (synthetic data only). Stored citations can outlive the documents they cite.
- No frontend for conversations yet; browsers cannot call `POST` endpoints (CORS allows `GET` only).

**Exit criteria:** met. Users can hold owner-scoped conversations whose follow-up questions use bounded history without weakening the evidence rules, covered by tests on SQLite and PostgreSQL and probed with the real model.