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
| P2-M5 | Security review and hardening, documentation, Phase 2 report | COMPLETE | the commit that adds this row |

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

**Commits:** P2-M1 `1d549ee`, P2-M2 `6704107`, P2-M3 `02117b6`, P2-M4 `9bd5df7`, P2-M5 (the commit that adds this report).

**Dependencies added in Phase 2:** `python-multipart` (uploads), `pypdf` (PDF text), `python-docx` and `lxml` (DOCX text). All are prebuilt wheels for Python 3.14.

**Architecture decisions:** ADR-014 (development identity), ADR-015 (content-addressed storage, tenant-scoped data), ADR-016 (in-request processing), ADR-017 (chunking).

**Tests:** 239 backend (169 unit, 70 integration) plus 27 frontend = 266, up from 72 at the end of Phase 1.

**Security considerations:** see [SECURITY.md](SECURITY.md); the P2-M5 review is summarized above.

**Manual verification steps** (from `apps/api`, with the API running):

1. `curl.exe -F "file=@<synthetic.pdf>" http://127.0.0.1:8000/api/v1/documents` → `201`, `status: processed`.
2. `curl.exe http://127.0.0.1:8000/api/v1/documents/<id>/chunks` → chunks with page numbers.
3. Upload the same file again → `200` with the same `id`.

**Recommended next phase:** Phase 3, embeddings and retrieval. It starts with an environment check (PostgreSQL and pgvector availability, a CPU-friendly local embedding model compatible with Python 3.14) and an embedding interface independent of any provider, plus a plan for your approval.