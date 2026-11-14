# EASA — Security

> **Status:** Phase 1. Foundational controls are implemented. Authentication, authorization, document handling and AI safeguards are **not implemented yet** and are listed with their planned phase.
> Checked against the M5 state (commit `3371ec3` plus M5 changes) on 2026-11-14. EASA is a learning project, not a production system.

Related: [HLD](HLD.md) · [API specification](API_SPECIFICATION.md) · [Architecture decisions](ARCHITECTURE_DECISIONS.md)

## 1. Principles

- Security is designed in from the first milestone, not added at the end.
- Deny by default. Every protected operation will be authorized on the server.
- Never trust a role, user ID, tenant ID or permission supplied only by the browser.
- Hiding UI is never an access control.
- Prompt instructions are never an authorization mechanism.
- Retrieved documents and user messages are untrusted data, not instructions.
- Only synthetic data. No real company information, credentials or customer data in the repository or in external AI services.

## 2. Current attack surface

| Surface | Exposure |
|---|---|
| `GET /api/v1/health`, `GET /api/v1/health/ready` | Public, unauthenticated; coarse status only |
| `/docs`, `/openapi.json` | Available outside `production` |
| Web dashboard | Static page; calls readiness from the browser without credentials |
| SQLite file | Local disk under `apps/api/var/`; holds no domain data |
| Configuration | Environment variables and git-ignored `.env` files |

The documented API command and `scripts/dev.ps1` bind the API to `127.0.0.1`. Next.js listens on all interfaces (`0.0.0.0`) by default, so since M5 the `dev` and `start` npm scripts pass `--hostname localhost`.

## 3. Implemented controls

### Configuration and secrets

| Control | Where |
|---|---|
| Strict settings: unknown `.env` keys rejected, typed values, immutable after load | [config.py](../apps/api/app/core/config.py) |
| Database URL stored as `SecretStr`; hidden from `repr()`; validation errors never echo input (`hide_input_in_errors`) | [config.py](../apps/api/app/core/config.py) — tested |
| Database driver allowlist | [config.py](../apps/api/app/core/config.py) |
| Only `.env.example` templates are committed; `.env` / `.env.*`, `var/`, `*.db`, `*.pem` and `*.key` are git-ignored | [.gitignore](../.gitignore), [apps/web/.gitignore](../apps/web/.gitignore) |
| Browser configuration limited to `NEXT_PUBLIC_API_BASE_URL`, validated (http/https only), never secret | [config.ts](../apps/web/src/lib/config.ts) |

### HTTP and errors

| Control | Where |
|---|---|
| Uniform error envelope; no stack traces or exception messages to clients | [errors.py](../apps/api/app/core/errors.py), [middleware.py](../apps/api/app/core/middleware.py) — tested |
| Validation errors omit submitted values | [errors.py](../apps/api/app/core/errors.py) — tested |
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
| Tracebacks go to server logs only | [middleware.py](../apps/api/app/core/middleware.py) |

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
| Document-level permissions applied before retrieval and before returning content | Phases 2, 3, 6 |
| Tenant and ownership filters inside the backend | Phase 6 |
| Upload validation (type, extension, size, content), safe filenames, no path traversal, storage outside web roots | Phase 2 |
| Prompt-injection defences; retrieved text kept separate from instructions | Phases 4, 5 |
| Allowlisted tools with strict schemas, permission re-check before execution, confirmation for consequential actions | Phase 5 |
| Audit logs for protected operations and tool executions (tool, user, authorization result, outcome, correlation ID) | Phases 5, 6 |
| Rate limiting and request size limits | Before any shared deployment |
| Security response headers on the API (e.g. CSP, `X-Content-Type-Options`) | Phase 7 / 8 |
| TLS | Any non-local deployment |
| Automated dependency review and secret scanning in CI; pinning Actions to commit SHAs | Phase 8 |

## 5. Threat notes for the current system

| Threat | Current mitigation | Residual risk |
|---|---|---|
| Secret leakage through errors or logs | `SecretStr`, hidden validation input, error-type-only DB logging, no query strings in logs | Developers could still log sensitive values in new code; reviews must catch it |
| Information disclosure via error responses | Generic 500 body; envelope everywhere | Health endpoints reveal whether the database is reachable |
| Cross-origin abuse | Explicit origin list, `GET` only, no credentials | None significant today; revisit when authentication arrives |
| Log injection or spoofed correlation IDs | IDs generated server-side; JSON-encoded log fields | Low |
| Accidental commit of secrets or data | `.gitignore` rules; manual pre-commit diff review and secret check required by the commit workflow | Manual process; automated scanning planned for CI |
| Web server reachable from the local network | npm scripts bind to `localhost` (M5) | Running `next` directly without `--hostname` still binds to all interfaces |
| Malicious API responses reaching the UI | Zod validation; React escaping | Low |

## 6. Security testing

**Automated today** (part of the 72 tests):

- Settings reject invalid values, wildcard/path CORS origins, non-allowlisted drivers and unknown `.env` keys; secrets are not echoed.
- Errors: 404/405/422/500 use the envelope; the 500 body has no internal details; validation errors omit input.
- Correlation IDs: unique per request; client-supplied values ignored; present in logs; query strings not logged.
- CORS: unlisted origins rejected; allowed origin can read `X-Correlation-ID`; 500 responses keep CORS headers.
- Web: config rejects non-http(s) URLs (including `javascript:`); invalid or non-JSON responses are rejected; unexpected errors are not shown verbatim.

**Planned:** unauthenticated and unauthorized access, horizontal and vertical privilege escalation, cross-tenant access, malicious uploads and filenames, prompt injection, unauthorized tool calls, secret leakage in model output.

## 7. Reporting

This is a personal portfolio project. Report issues through the GitHub repository's issue tracker. Never include real credentials or personal data in a report.
