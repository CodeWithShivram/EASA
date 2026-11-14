# EASA — Security

> **Status:** Phase 3 in progress (P3-M1 embeddings). Foundational controls and the upload, parsing and chunking path are implemented and were security-reviewed in P2-M5. Authentication, authorization and AI safeguards are **not implemented yet** and are listed with their planned phase.
> Checked against the P2-M5 changes on 2026-11-14. EASA is a learning project, not a production system.

Related: [HLD](HLD.md) · [API specification](API_SPECIFICATION.md) · [Architecture decisions](ARCHITECTURE_DECISIONS.md)

## 1. Principles

- Security is designed in from the first milestone, not added at the end.
- Deny by default. Every protected operation will be authorized on the server.
- Never trust a role, user ID, tenant ID or permission supplied only by the browser.
- Hiding UI is never an access control.
- Prompt instructions are never an authorization mechanism.
- Retrieved documents, uploaded files and user messages are untrusted data, not instructions.
- Only synthetic data. No real company information, credentials or customer data in the repository or in external AI services.

## 2. Current attack surface

| Surface | Exposure |
|---|---|
| `GET /api/v1/health`, `GET /api/v1/health/ready` | Public, unauthenticated; coarse status only |
| `POST /api/v1/documents`, `GET /api/v1/documents[/{id}[/chunks]]` | Development only (not mounted in production); no authentication; act as a fixed development identity ([ADR-014](ARCHITECTURE_DECISIONS.md#adr-014)); accept untrusted files and parse them in the API process |
| `/docs`, `/openapi.json` | Available outside `production` |
| Web dashboard | Static page; calls readiness from the browser without credentials |
| SQLite file (`apps/api/var/easa.db`) | Local disk; holds synthetic document metadata and chunk text |
| File store (`apps/api/var/uploads/`) | Local disk; uploaded bytes by SHA-256; never served directly |
| Embedding model files (`apps/api/var/models/`) | Local disk, git-ignored; downloaded once by an explicit command; loaded by ONNX Runtime |
| Temporary files | Starlette spools uploads larger than 1 MiB to an OS temporary file while the request is parsed |
| Configuration | Environment variables and git-ignored `.env` files |

The documented API command and `scripts/dev.ps1` bind the API to `127.0.0.1`. Next.js listens on all interfaces (`0.0.0.0`) by default, so since M5 the `dev` and `start` npm scripts pass `--hostname localhost`.

## 3. Implemented controls

### Configuration and secrets

| Control | Where |
|---|---|
| Strict settings: unknown `.env` keys rejected, typed values, cross-field checks (chunk overlap), immutable after load | [config.py](../apps/api/app/core/config.py) — tested |
| Database URL stored as `SecretStr`; hidden from `repr()`; validation errors never echo input (`hide_input_in_errors`) | [config.py](../apps/api/app/core/config.py) — tested |
| Database driver allowlist | [config.py](../apps/api/app/core/config.py) |
| Only `.env.example` templates are committed; `.env` / `.env.*`, `var/`, `*.db`, `*.pem` and `*.key` are git-ignored | [.gitignore](../.gitignore), [apps/web/.gitignore](../apps/web/.gitignore) |
| Browser configuration limited to `NEXT_PUBLIC_API_BASE_URL`, validated (http/https only), never secret | [config.ts](../apps/web/src/lib/config.ts) |

### HTTP and errors

| Control | Where |
|---|---|
| Uniform error envelope; no stack traces or exception messages to clients | [errors.py](../apps/api/app/core/errors.py), [middleware.py](../apps/api/app/core/middleware.py) — tested |
| Validation errors omit submitted values | [errors.py](../apps/api/app/core/errors.py) — tested |
| Request body limit (`EASA_MAX_UPLOAD_BYTES` + 64 KiB), enforced on the declared `Content-Length` (ASCII digits only) and while streaming | [middleware.py](../apps/api/app/core/middleware.py) `BodySizeLimitMiddleware` — tested |
| Narrow CORS: explicit origins only (no wildcards), `GET` only, no credentials | [main.py](../apps/api/app/main.py), [config.py](../apps/api/app/core/config.py) — origin rules tested; `GET`-only and no-credentials are configured but not covered by tests |
| Interactive API docs disabled in production | [main.py](../apps/api/app/main.py) |
| Web server does not send `X-Powered-By` | [next.config.ts](../apps/web/next.config.ts) — verified |
| Web client sends no cookies or credentials (`credentials: "omit"`) and validates every response with Zod | [client.ts](../apps/web/src/lib/api/client.ts) — tested |
| Unexpected client-side errors show a generic message, not internal details | [ApiStatusCard.tsx](../apps/web/src/components/health/ApiStatusCard.tsx) — tested |

### Logging and traceability

| Control | Where |
|---|---|
| Server-generated correlation ID on every response, log line and error body; client values ignored (prevents log spoofing) | [middleware.py](../apps/api/app/core/middleware.py) — tested |
| Query strings are not logged (they may carry tokens) | [middleware.py](../apps/api/app/core/middleware.py) — tested |
| Database failures log only the error type, not driver messages | [probe.py](../apps/api/app/db/probe.py) |
| Processing logs carry metadata only (document ID, status, error code, page, block and chunk counts). A parser crash is logged at ERROR with only the exception type; the traceback, which may quote file content, is logged at DEBUG | [documents.py](../apps/api/app/services/documents.py) — tested |
| `pypdf`'s own warnings (which quote names from the file) are suppressed below ERROR | [extraction.py](../apps/api/app/services/extraction.py) |
| Filenames and document text are not written to the request or processing logs | [middleware.py](../apps/api/app/core/middleware.py), [documents.py](../apps/api/app/services/documents.py) — verified on a live server |

### Uploads

| Control | Where |
|---|---|
| Extension allowlist (`.pdf`, `.docx`, `.txt`) **and** content signature check; the client's declared content type is ignored | [uploads.py](../apps/api/app/services/uploads.py) — tested |
| DOCX archive checks from the zip directory before decompression: entry count, total uncompressed size, per-entry compression ratio (zip bombs); encrypted entries rejected; macro content rejected based on `[Content_Types].xml` (`vbaProject`, `macroEnabled`) and the `vbaProject.bin` part name. Python's `zipfile` caps output at the declared size and checks CRCs, so lying about sizes does not bypass the limits | [uploads.py](../apps/api/app/services/uploads.py) — tested |
| Malformed archives (bad structure, unsupported zip versions, invalid names) are rejected as `corrupt_file`, never a 500 (found by fuzzing in the P2-M5 review) | [uploads.py](../apps/api/app/services/uploads.py) — tested |
| TXT must be UTF-8 without NUL bytes (the whole file is decoded to check) | [uploads.py](../apps/api/app/services/uploads.py) — tested |
| Filenames sanitized for display: last path component only; Unicode control (`Cc`) and format (`Cf`) characters removed — zero-width characters, bidirectional controls that can disguise an extension, tag characters, soft hyphens; reserved characters removed; never used as paths. Windows reserved names (`CON.txt`) are kept, as names are display-only | [uploads.py](../apps/api/app/services/uploads.py) — tested |
| Bytes stored by SHA-256 outside any web root; only validated lowercase hex digests become paths | [blob_store.py](../apps/api/app/storage/blob_store.py) — tested |
| Identity comes from server configuration only; document endpoints are not mounted in production | [dependencies.py](../apps/api/app/api/dependencies.py), [main.py](../apps/api/app/main.py) — tested |
| Every repository query filters by `tenant_id`; another tenant's document (and its chunks) answers exactly like a missing one; deduplication is per tenant, so there is no cross-tenant content oracle | [documents.py](../apps/api/app/repositories/documents.py), [documents.py](../apps/api/app/services/documents.py) — tested |

### Parsing and chunking

| Control | Where |
|---|---|
| Uploaded files are parsed in memory and never executed or extracted to disk by EASA (Starlette's request spooling above is the only disk write besides the content-addressed store) | [extraction.py](../apps/api/app/services/extraction.py) |
| DOCX XML is parsed by `python-docx` with `resolve_entities=False`; `lxml` loads no external DTDs and makes no network requests by default. External general and parameter entities are never read (the document is processed with the reference dropped); an entity-expansion ("billion laughs") document fails as `corrupt_file` in milliseconds (libxml2's amplification limit) | `python-docx` 1.2.0 (verified in its source), [test_extraction.py](../apps/api/tests/unit/test_extraction.py) — tested |
| DOCX tables: each physical cell is read once. `python-docx`'s `row.cells` repeats a cell for every grid column it spans and `gridSpan` is attacker-controlled (a 35 KB file could otherwise expand into billions of cell copies) | [extraction.py](../apps/api/app/services/extraction.py) — tested with `gridSpan` 1,000,000 |
| PDF limits: `pypdf` stream output limits lowered from 75 MB to 20 MB per stream (applied only during EASA's parsing); at most 50 MB decoded per document; a 30-second wall-clock budget checked between pages; `EASA_MAX_PDF_PAGES` (default 500). Each page's content stream is decoded explicitly, because `extract_text()` silently returns empty text when a limit is hit. Failures surface as `resource_limit_exceeded` | [extraction.py](../apps/api/app/services/extraction.py) — tested |
| Work budgets enforced **while** extracting, not afterwards: 5,000,000 characters of normalized text (`text_too_large`) and 50,000 blocks (`document_too_complex`); chunking is capped at 20,000 chunks per document (`document_too_complex`) and runs in O(chunks · log blocks) | [extraction.py](../apps/api/app/services/extraction.py), [chunking.py](../apps/api/app/services/chunking.py) — tested |
| Encrypted PDFs are rejected. (`pypdf` tries the empty user password when opening a file; EASA rejects any file still reported as encrypted and never supplies a password.) | [extraction.py](../apps/api/app/services/extraction.py) — tested |
| Normalized text has Unicode format characters (`Cf`) removed, so chunk text cannot carry invisible bidi controls or tag characters that hide content from human reviewers (relevant for prompt injection in Phase 4) | [normalization.py](../apps/api/app/services/normalization.py) — tested |
| Parser or chunking failures mark the document `failed` with a generic code; exception text never reaches the client; partial chunks are rolled back | [documents.py](../apps/api/app/services/documents.py) — tested |
| A document interrupted mid-processing (process killed, final commit failed) stays `processing`; an identical re-upload more than 10 minutes later reprocesses it instead of returning it unchanged | [documents.py](../apps/api/app/services/documents.py) — tested |
| Chunk text is returned only through the tenant-scoped chunks endpoint | [documents.py](../apps/api/app/services/documents.py) — tested |

### Embeddings (Phase 3, P3-M1)

| Control | Where |
|---|---|
| The embedding model is pinned to an exact upstream revision (`Qdrant/bge-small-en-v1.5-onnx-Q@aa8f8b06…`, MIT licence) and an explicit file list, and downloaded only by an explicit command | [registry.py](../apps/api/app/embeddings/registry.py), [factory.py](../apps/api/app/embeddings/factory.py) |
| No network access at runtime: the model loads from local files with `local_files_only=True`; missing files make readiness report `embeddings: unavailable` instead of triggering a download | [onnx.py](../apps/api/app/embeddings/onnx.py) — tested |
| Vectors carry `tenant_id` (copied from the chunk) and the full `model_id` including the revision, so search can filter by tenant before scoring and never mixes models | [embeddings.py](../apps/api/app/db/embeddings.py) |
| Embedding logs carry document ID, model ID, counts and error type only, never chunk text | [documents.py](../apps/api/app/services/documents.py) |
| Unit tests and CI use a deterministic, offline hashing embedder; real-model checks run only where the model is present | [hashing.py](../apps/api/app/embeddings/hashing.py), `tests/model/` |

Model files are trusted as pinned upstream artifacts; their integrity relies on Hugging Face's revision and hash checks in `huggingface_hub`.

### Database
- Parameterized access through SQLAlchemy; the only raw SQL is the constant `SELECT 1` probe.
- Foreign keys enforced on SQLite connections.
- Schema changes only through reviewed Alembic migrations.

### Supply chain

- Lockfiles committed: `apps/api/uv.lock`, `apps/web/package-lock.json` (resolved only from `registry.npmjs.org`).
- Dependencies are added only with a stated purpose, after checking compatibility with Python 3.14 and Node 24.13.
- CI ([ci.yml](../.github/workflows/ci.yml)) installs strictly from the lockfiles (`uv sync --locked`, `npm ci`) with a read-only `GITHUB_TOKEN` (`permissions: contents: read`). Actions are pinned to major-version tags (setup-uv to an exact release tag), not commit SHAs.
- Ruff runs the bandit-derived `S` security rules on all Python code (`S101`, `assert`, is allowed in tests).
- No web fonts are fetched at build time. Next.js telemetry is not disabled by repository configuration; set `NEXT_TELEMETRY_DISABLED=1` in your shell to opt out.

## 4. Not yet implemented

| Requirement | Planned |
|---|---|
| Authentication from a verified identity context; session/token handling | Phase 6 |
| Role-based and resource-level authorization; deny by default | Phase 6 |
| Document-level permissions applied before retrieval and before returning content | Phases 3, 6 |
| Ownership filters and tenant management (tenant filters already exist for documents) | Phase 6 |
| Prompt-injection defences; retrieved text kept separate from instructions | Phases 4, 5 |
| Allowlisted tools with strict schemas, permission re-check before execution, confirmation for consequential actions | Phase 5 |
| Audit logs for protected operations and tool executions (tool, user, authorization result, outcome, correlation ID) | Phases 5, 6 |
| Rate limiting | Before any shared deployment |
| Running parsers in a separate process with hard CPU, memory and time limits. Today a PDF page can still take seconds of CPU (pypdf's form-XObject limit resets per page) within the 30-second budget, and memory is bounded only by the input and budget limits | Before handling untrusted uploads from real users |
| Security response headers on the API (e.g. CSP, `X-Content-Type-Options`) | Phase 7 / 8 |
| TLS | Any non-local deployment |
| Automated dependency review and secret scanning in CI; pinning Actions to commit SHAs | Phase 8 |
| Reference counting before blob deletion (blobs are shared across tenants with identical content) | With a delete endpoint |

## 5. Threat notes

| Threat | Current mitigation | Residual risk |
|---|---|---|
| Secret leakage through errors or logs | `SecretStr`, hidden validation input, error-type-only logging for DB and parser failures, no query strings in logs | Developers could still log sensitive values in new code; reviews must catch it |
| Information disclosure via error responses | Generic 500 body; envelope everywhere; identical 404 for foreign and missing documents | Health endpoints reveal whether the database is reachable |
| Cross-origin abuse | Explicit origin list, `GET` only, no credentials | None significant today; revisit when authentication arrives |
| Log injection or spoofed correlation IDs | IDs generated server-side; JSON-encoded log fields | Low |
| Malicious uploads (disguised executables, polyglots, zip bombs, macros) | Allowlist plus signature, zip directory limits, macro detection, nothing executed | Polyglot files that are valid as both an allowed type and something else are stored, but never executed or served |
| Parser resource exhaustion (decompression bombs, `gridSpan`, quadratic work, huge block counts) | Stream, decoded-byte, time, character, block and chunk budgets; linear algorithms (verified before/after in P2-M5) | Parsing still runs in the API process; a slow PDF occupies a worker for up to about 30 seconds |
| XML attacks via DOCX (XXE, entity expansion) | `resolve_entities=False`, no external DTDs or network in lxml, libxml2 amplification limit | Low |
| Spoofed or hidden text (bidi controls, tag characters) | Removed from filenames and from normalized text | Visually confusable letters (homoglyphs) are not normalized |
| Accidental commit of secrets or data | `.gitignore` rules; manual pre-commit diff review and secret check required by the commit workflow | Manual process; automated scanning planned for CI |
| Web server reachable from the local network | npm scripts bind to `localhost` (M5) | Running `next` directly without `--hostname` still binds to all interfaces |
| Malicious API responses reaching the UI | Zod validation; React escaping | Low |

## 6. Security review and testing

**P2-M5 review.** An independent read-only review of the upload, processing and chunk path (with timing and fuzzing experiments) reported 11 findings. All were reproduced or reasoned through and fixed, or documented here as residual risk: quadratic chunking, `gridSpan` amplification, PDF parsing cost, documents stuck in `processing`, a weak text cap, zip exceptions causing 500s, invisible characters in chunk text and filenames, a name-only macro check, file fragments in logs, and a non-ASCII `Content-Length` edge case. Details and before/after measurements are in [PROGRESS.md](PROGRESS.md#p2-m5-hardening-and-phase-2-report).

**Automated tests** (part of the 285 tests; 2 real-model tests skip without the model):

- Embeddings: one vector per chunk under the model's versioned ID; failed documents never embedded; embedding failures leave the document processed and are backfilled; vectors deleted with their chunks; readiness reports a missing model; the CLI refuses to run without the model.

- Settings reject invalid values, wildcard/path CORS origins, non-allowlisted drivers, unknown `.env` keys and invalid chunk settings; secrets are not echoed.
- Errors: 404/405/422/500 use the envelope; the 500 body has no internal details; validation errors omit input.
- Correlation IDs: unique per request; client-supplied values ignored; present in logs; query strings not logged.
- CORS: unlisted origins rejected; allowed origin can read `X-Correlation-ID`; 500 responses keep CORS headers.
- Body limit: oversized bodies with and without `Content-Length`; invalid and non-ASCII-digit `Content-Length`.
- Uploads: malicious filenames (`../`, `..\`, reserved, control, bidi, zero-width and tag characters, dot-prefixed), disallowed extensions, executables disguised as PDFs, mismatched content, empty and oversized files, non-UTF-8 text, corrupt, encrypted, zip-bomb and macro DOCX files (including macros found only through content types), unsupported zip versions.
- Parsing: encrypted, corrupt and over-long PDFs; PDF decompression bombs at 25 MB and 80 MB; decoded-bytes and time budgets; DOCX XXE (general and parameter entities) and entity-expansion bombs; `gridSpan` 1,000,000; text and block budgets; text-less documents; a simulated parser crash (no exception text in the response or the ERROR log).
- Processing: interrupted documents reprocessed on re-upload; recently started ones left alone.
- Chunks: tenant-scoped; failed documents have no chunks; chunk count capped; chunking of 40,000 blocks under 3 seconds.
- Documents: repository reads are tenant-scoped; the file store rejects path-traversal and malformed hashes.
- Web: config rejects non-http(s) URLs (including `javascript:`); invalid or non-JSON responses are rejected; unexpected errors are not shown verbatim.

**Planned:** unauthenticated and unauthorized access, horizontal and vertical privilege escalation, cross-tenant access through retrieval, prompt injection, unauthorized tool calls, secret leakage in model output.

## 7. Reporting

This is a personal portfolio project. Report issues through the GitHub repository's issue tracker. Never include real credentials or personal data in a report.
