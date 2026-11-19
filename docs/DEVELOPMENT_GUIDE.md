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

| Docker Desktop | 29.9.3 (Compose v5.7.0, WSL 2) | Optional: runs PostgreSQL 18 + pgvector for section 6c. SQLite needs nothing extra |

Ollama is not used yet. No administrator rights are required for the default SQLite setup.

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
uv run python -m app.cli download-embedding-model   # once: 64 MB from Hugging Face, pinned revision
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Always pass `--no-proxy-headers`: by default Uvicorn trusts `X-Forwarded-For` from 127.0.0.1 and rewrites the client address before the API sees it, which would let anyone reaching the API through the web app on the same host choose their address and evade the sign-in limit. Which proxies to trust is decided by the API's own `EASA_TRUSTED_PROXIES` ([ADR-035](ARCHITECTURE_DECISIONS.md#adr-035)).

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

Every endpoint except health and sign-in needs a session token (Phase 6, [ADR-031](ARCHITECTURE_DECISIONS.md#adr-031)). Create a synthetic user once, then sign in:

```powershell
# once, from apps/api: asks for a password (12-128 characters, not containing the username)
uv run python -m app.cli create-user --tenant Larkspur --username alice --role manager
# sign in (prompts for the password; nothing is written to disk or history)
$cred = Get-Credential alice
$body = @{ username = $cred.UserName; password = $cred.GetNetworkCredential().Password } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/login -ContentType application/json -Body $body).token
$auth = "Authorization: Bearer $token"
curl.exe -H $auth http://127.0.0.1:8000/api/v1/auth/me
```

Roles: employees search and read documents, managers can also upload, administrators can also manage users (API spec section 3.11). An administrator manages users of their own tenant, for example `curl.exe -H $auth http://127.0.0.1:8000/api/v1/users`, and reads its audit log with `curl.exe -H $auth "http://127.0.0.1:8000/api/v1/audit?action=auth.login&limit=20"`. In the web app (http://localhost:3000, with `npm run dev` or `npm run start` in `apps/web`) sign in on `/login`; **Chat** asks questions over the documents your role may see (it needs `EASA_MODEL_PROVIDER` on the API) and shows the cited text when you choose a citation; **Documents** lists what your role may see, and managers and administrators upload there and choose who may see each document; **Assistant** answers questions about your tickets and policies and proposes draft tickets that run only after you choose Confirm (after `seed-tickets --username <you>` there are tickets to ask about). Sessions end after 8 hours without use or 24 hours at most; `curl.exe -X POST -H $auth http://127.0.0.1:8000/api/v1/auth/logout` ends one now. Five wrong passwords in a row lock the account for 15 minutes.

Uploading a document from PowerShell (`curl.exe`, not the PowerShell `curl` alias):

```powershell
curl.exe -H $auth -F "file=@C:\path\to\policy.txt" http://127.0.0.1:8000/api/v1/documents   # 201, or 200 if already uploaded
curl.exe -H $auth -F "file=@C:\path\to\handbook.txt" -F "min_role=manager" http://127.0.0.1:8000/api/v1/documents   # managers and administrators only
curl.exe -H $auth "http://127.0.0.1:8000/api/v1/documents?limit=10"
curl.exe -H $auth "http://127.0.0.1:8000/api/v1/documents/<id>/chunks"
# Search: write the JSON body to a file to avoid PowerShell quoting issues
[IO.File]::WriteAllText("$PWD\q.json", '{"query": "How much vacation time do staff get?", "top_k": 3}')
curl.exe -H $auth -H "Content-Type: application/json" --data-binary "@q.json" http://127.0.0.1:8000/api/v1/search
# Modes: "hybrid" (default), "semantic", or "keyword" (BM25, works without the embedding model)
[IO.File]::WriteAllText("$PWD\q.json", '{"query": "receipts deadline", "top_k": 3, "mode": "hybrid"}')
curl.exe -H $auth -H "Content-Type: application/json" --data-binary "@q.json" http://127.0.0.1:8000/api/v1/search
```

Conversations keep earlier turns for follow-up questions (same model requirement):

```powershell
$c = (curl.exe -H $auth -s -X POST http://127.0.0.1:8000/api/v1/conversations | ConvertFrom-Json).id
[IO.File]::WriteAllText("$PWD\a.json", '{"question": "How many days of annual leave do employees get?"}')
curl.exe -H $auth -H "Content-Type: application/json" --data-binary "@a.json" "http://127.0.0.1:8000/api/v1/conversations/$c/messages"
curl.exe -H $auth "http://127.0.0.1:8000/api/v1/conversations/$c"
```

Asking a single question (needs `EASA_MODEL_PROVIDER` set; with `fake` the "answer" is the first sentence of the top source, which is enough to try the pipeline without a model):

```powershell
[IO.File]::WriteAllText("$PWD\a.json", '{"question": "How many days of annual leave do employees get?"}')
curl.exe -H $auth -H "Content-Type: application/json" --data-binary "@a.json" http://127.0.0.1:8000/api/v1/answers
```

Tools (Phase 5, development only), after `uv run python -m app.cli seed-tickets --username alice` (synthetic tickets in alice's tenant, once):

```powershell
curl.exe -H $auth http://127.0.0.1:8000/api/v1/tools
[IO.File]::WriteAllText("$PWD\t.json", '{"arguments": {"number": 1}}')
curl.exe -H $auth -H "Content-Type: application/json" --data-binary "@t.json" http://127.0.0.1:8000/api/v1/tools/get_ticket/invoke
```

The agent (needs a configured model, e.g. the local one in section 6e):

```powershell
[IO.File]::WriteAllText("$PWD\g.json", '{"message": "What is the status of my ticket 3?"}')
curl.exe -H $auth -H "Content-Type: application/json" --data-binary "@g.json" http://127.0.0.1:8000/api/v1/agent
# a proposed draft ticket returns "pending_action"; review it, then:
curl.exe -H $auth -X POST http://127.0.0.1:8000/api/v1/agent/actions/<id>/confirm    # or /cancel
```

Use synthetic documents only.

Stop servers with `Ctrl+C`. If you start them in the background from a script, stop the **whole process tree** (`taskkill /PID <pid> /T /F`); killing only the parent can leave the server running (see section 9).

### Browser check (by hand)

The automated checks drive the web server over HTTP; a person should also look at the pages in a browser now and then (Phase 8 adds browser tests). With the API and `npm run start` running and an administrator created:

1. Open http://localhost:3000: you land on `/login`. Sign in; the header shows your name and role.
2. **Admin**: create an employee and a manager. Check that your own row has no role or disable controls.
3. **Documents** (as the administrator): upload a TXT at "Managers and administrators"; open it and read its parts.
4. Sign out, sign in as the employee: the document is not listed; Admin explains it is for administrators; **Chat** answers a question about an employee-level policy with a clickable citation that opens its source.
5. **Assistant**: ask for a new ticket, check the prompt and arguments, then Cancel.
6. Narrow the window to phone width: navigation, chat and tables stay usable (tables scroll sideways).
7. Use only the keyboard (Tab, Shift+Tab, Enter): every control is reachable and shows a focus ring; switch the system to dark mode and check that text stays readable.

## 4. Configuration

| Variable | App | Default | Notes |
|---|---|---|---|
| `EASA_ENVIRONMENT` | API | `development` | `development`, `test`, `production` (production disables `/docs`) |
| `EASA_LOG_LEVEL` | API | `INFO` | `DEBUG` … `CRITICAL` |
| `EASA_DATABASE_URL` | API | `sqlite:///…/apps/api/var/easa.db` | Drivers: `sqlite`, `sqlite+pysqlite`, `postgresql+psycopg` (PostgreSQL: section 6c) |
| `EASA_CORS_ALLOWED_ORIGINS` | API | `["http://localhost:3000"]` | JSON list; no wildcards |
| `EASA_STORAGE_DIR` | API | `apps/api/var/uploads` | Uploaded file contents (content-addressed); git-ignored |
| `EASA_MAX_UPLOAD_BYTES` | API | `10485760` (10 MiB) | Largest accepted file (1 byte to 100 MiB); the request body limit is this plus 64 KiB |
| `EASA_MAX_PDF_PAGES` | API | `500` | PDFs with more pages fail processing with `too_many_pages` (1–5000) |
| `EASA_CHUNK_STRATEGY` | API | `structured` | `structured` (whole blocks, page/section-aware) or `fixed` (overlapping windows) |
| `EASA_CHUNK_MAX_CHARS` | API | `1200` | Largest chunk in characters (100–20000) |
| `EASA_CHUNK_OVERLAP_CHARS` | API | `150` | Overlap between consecutive windows; must be less than half of `EASA_CHUNK_MAX_CHARS` |
| `EASA_EMBEDDING_PROVIDER` | API | `onnx` | `onnx` (pinned local bge-small-en-v1.5; download first) or `hashing` (deterministic, non-semantic; used by tests) |
| `EASA_EMBEDDING_MODEL_DIR` | API | `apps/api/var/models` | Where the pinned model files live (git-ignored) |
| `EASA_EMBEDDING_BATCH_SIZE` | API | `32` | Chunks per embedding batch (1–256) |
| `EASA_MODEL_PROVIDER` | API | `none` | Answer generation: `none` (disabled), `fake` (deterministic test double that quotes the first source and scripts the agent's steps; rejected in production), `llamacpp` (local llama.cpp server, section 6e) or `ollama` |
| `EASA_LLAMACPP_BASE_URL`, `EASA_OLLAMA_BASE_URL` | API | `http://127.0.0.1:8082`, `http://127.0.0.1:11434` | `http(s)://host[:port]` only; proxy environment variables are ignored for model calls |
| `EASA_MODEL_NAME` | API | empty | Required for `llamacpp` and `ollama`; letters, digits and `. _ : / -`. For the local model: `qwen2.5-1.5b-instruct-q4_k_m` |
| `EASA_CHAT_MODEL_DIR` | API | `apps/api/var/models/llm` | Where `download-chat-model` stores the GGUF file (git-ignored; mounted read-only into the `llm` container) |
| `EASA_MODEL_TIMEOUT_SECONDS`, `EASA_MODEL_MAX_OUTPUT_TOKENS`, `EASA_MODEL_TEMPERATURE` | API | `120`, `512`, `0.1` | Per-call limits (0–600 s, 16–4096 tokens, 0–1) |
| `EASA_ANSWER_SUPPORT_CHECK` | API | `false` | Drop citations whose source shares no content words with the citing sentence (P4-M5; see EVALUATION.md section 10) |
| `EASA_SESSION_IDLE_MINUTES`, `EASA_SESSION_LIFETIME_HOURS` | API | `480`, `24` | Sign-in sessions end after this long without use, and at the latest after the lifetime (ADR-031) |
| `EASA_PASSWORD_HASH_N` | API | `32768` | scrypt cost (power of two); production refuses lower values. Tests use 1024 |
| `EASA_RATE_LIMIT_LOGIN_PER_MINUTE`, `EASA_RATE_LIMIT_MODEL_PER_MINUTE` | API | `20`, `10` | Sign-in attempts per client address and model calls (answers, conversation questions, agent) per user per minute; `0` turns a limit off; per API process (ADR-035). Tests turn them off unless they test them |
| `EASA_TRUSTED_PROXIES` | API | `[]` | JSON list of IP addresses whose `X-Forwarded-For` is believed for the sign-in limit. List a proxy only if it overwrites that header; Next.js does not, so leave it empty unless a reverse proxy sits in front |
| `EASA_API_URL` | Web (server only) | `http://localhost:8000` | Where the web app's backend for frontend finds the API (ADR-034); never sent to the browser |

Invalid API settings stop the server at startup with a validation error that never shows the submitted value.

## 5. Checks

**All checks** (from the repository root):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1   # backend + frontend, about 2 minutes
scripts\check.ps1 -Backend                                    # or -Frontend, -SkipBuild
```

It runs every check even after a failure, prints a PASS/FAIL table and exits with code 1 if anything failed. The Alembic step uses a temporary SQLite database that is deleted afterwards. Dependencies must already be installed. Since P8-M1 it also audits dependencies (`pip-audit --strict`; `npm audit --omit=dev --audit-level=high`); both need network access to the advisory databases.

**CI:** [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs the same checks on GitHub Actions (Ubuntu, Python 3.14, uv 0.12.9, Node 24.13.0) for pushes to `main` and for pull requests.

Individual commands:

**Backend** (from `apps/api`):

```powershell
uv sync --locked              # fails if uv.lock is out of date with pyproject.toml
uv run ruff format --check .  # formatting (use `uv run ruff format .` to fix)
uv run ruff check .           # lint, including security rules
uv run pip-audit --strict     # known vulnerabilities in the locked dependencies
uv run pytest                 # 892 tests: 3 real-embedding tests skip without the model, 49 PostgreSQL tests without EASA_TEST_POSTGRES_URL, 4 live chat model tests without EASA_TEST_LLM_URL; warnings are errors
```

**Frontend** (from `apps/web`):

```powershell
npm run lint        # ESLint
npm run typecheck   # tsc --noEmit
npm test            # Vitest, 135 tests
npm audit --omit=dev --audit-level=high   # known vulnerabilities in what the app ships
npm run build       # production build
```

`npm run test:watch` exists for interactive use; it has not been run as part of verification.

**Browser tests** (P8-M3, [ADR-037](ARCHITECTURE_DECISIONS.md#adr-037); from `apps/web`, with the API dependencies installed by `uv sync`):

```powershell
npm run build                              # the tests run the built app (next start)
$env:EASA_E2E_CHANNEL = "msedge"           # use the installed Edge (or "chrome"); or once: npx playwright install chromium
npm run test:e2e                           # 16 tests, about 3 minutes
```

Playwright starts both servers itself: the API on port 8200 (`e2e/stack.mjs`: a fresh SQLite database in the git-ignored `.e2e` folder, synthetic users with generated passwords, the fake chat model and the hashing embedder) and the web app on port 3200, and stops them afterwards. Ports 8200 and 3200 must be free. A failed test keeps a trace in `test-results/` (`npx playwright show-trace <file>`); traces contain the generated passwords, so do not share them. CI runs the same tests in the `e2e` job with Playwright's Chromium.

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

## 6a. Embeddings

```powershell
uv run python -m app.cli download-embedding-model   # downloads the pinned model into var/models (network)
uv run python -m app.cli embed-missing              # embeds chunks that have no vector for the active model
uv run pytest tests/model                           # real-model checks (skip if not downloaded)
```

The API never downloads models at runtime. Without the model files, readiness reports `embeddings: unavailable`, uploads still succeed (text and chunks are stored), and `embed-missing` fills in the vectors after the download. Set `EASA_EMBEDDING_PROVIDER=hashing` to work without the model (not semantic).

## 6b. Keyword index

On SQLite, migration `6d544dac46b3` creates the FTS5 keyword index and indexes existing chunks; triggers keep it in sync afterwards. If the database file is ever compacted with `VACUUM`, or keyword results look inconsistent, rebuild it from `apps/api`:

```powershell
uv run python -m app.cli rebuild-keyword-index
```

## 6c. PostgreSQL + pgvector (optional)

SQLite is the default. To run the API on PostgreSQL 18 with pgvector 0.8.7 in Docker (from the repository root):

```powershell
Copy-Item .env.example .env          # then set EASA_POSTGRES_PASSWORD to a random value
docker compose up -d postgres        # pgvector/pgvector:0.8.7-pg18 on 127.0.0.1:5433 (healthcheck: pg_isready)
docker compose ps                    # wait for "healthy"
```

Then point the API at it (for example in `apps/api/.env`, which is git-ignored) and migrate, from `apps/api`:

```powershell
# EASA_DATABASE_URL=postgresql+psycopg://easa:<password>@127.0.0.1:5433/easa
uv run alembic upgrade head          # also enables the vector extension and the full-text index
uv run python -m app.cli embed-missing
```

On PostgreSQL, vector search runs inside the database (pgvector, exact) and keyword search uses PostgreSQL full-text search; see [DATABASE_DESIGN.md](DATABASE_DESIGN.md) section 9. The migration converts existing vectors by deleting them (they are derived data); `embed-missing` recreates them.

**PostgreSQL tests.** `tests/postgres` runs only when `EASA_TEST_POSTGRES_URL` is set to a URL whose user may create databases. Each run creates throwaway databases (`easa_test_<random>`), migrates them and drops them; the database in the URL is not written to.

```powershell
$env:EASA_TEST_POSTGRES_URL = "postgresql+psycopg://easa:<password>@127.0.0.1:5433/easa"
uv run pytest tests/postgres
$env:EASA_TEST_POSTGRES_URL = $null
```

Stop the container with `docker compose stop` (keeps data) or `docker compose down -v` (deletes the data volume). CI runs the same tests against a `pgvector/pgvector:0.8.7-pg18` service container, with `EASA_REQUIRE_POSTGRES_TESTS=1` so that skipped PostgreSQL tests fail the build.

## 6d. Retrieval evaluation

```powershell
uv run python -m app.cli evaluate                        # SQLite, default chunking, real model
uv run python -m app.cli evaluate --configs all          # 6 chunking settings, about 1 minute
$env:EASA_EVAL_POSTGRES_URL = "postgresql+psycopg://easa:<password>@127.0.0.1:5433/easa"
uv run python -m app.cli evaluate --backend postgres --configs all
uv run python -m app.cli evaluate-hnsw --tenants 10      # exact vs HNSW, 50,000 synthetic vectors
$env:EASA_EVAL_POSTGRES_URL = $null
```

Answer evaluation (P4-M5) needs the local chat model (section 6e) and takes hours on a CPU:

```powershell
$env:EASA_MODEL_PROVIDER = "llamacpp"; $env:EASA_MODEL_NAME = "qwen2.5-1.5b-instruct-q4_k_m"
uv run python -m app.cli evaluate-answers --limit 5          # a quick look
uv run python -m app.cli evaluate-answers --configs all      # 43 cases x 3 settings
uv run python -m app.cli evaluate-agent                      # 26 agent tasks (P5-M5); nothing is confirmed
uv run python -m app.cli evaluate-access --surfaces search   # leakage by role, no model (P6-M5)
uv run python -m app.cli evaluate-access                     # search, answers and agent with the model
```

All evaluations with one command (P8-M4, [ADR-038](ARCHITECTURE_DECISIONS.md#adr-038)). It runs every evaluation whose prerequisites are present and writes `<time>-all.md`, listing each report and each skipped evaluation with the reason:

```powershell
uv run python -m app.cli evaluate-all --no-model   # retrieval and search-only access: about a minute
uv run python -m app.cli evaluate-all              # plus answers, agent and full access with the chat model: about an hour
```

**Changing evaluation data.** `eval/manifest.json` records a version and the SHA-256 of every file under `eval/`. After reviewing a change to any file there, run `uv run python -m app.cli update-eval-manifest --version <current + 1>` and commit the manifest together with the data. Until then the evaluation commands refuse to run, and a unit test fails. Each report starts with its run: the data version, manifest SHA-256, commit, models, settings and timing.

The dataset is in `apps/api/eval/` (`answers.json`, `agent.json`, `access.json`, `adversarial/` with prompt-injection documents used only by the answer and agent evaluations, and `access/` with role-restricted documents for the leakage evaluation); reports go to `apps/api/var/eval/` (git-ignored). PostgreSQL runs create and drop throwaway `easa_eval_<random>` databases. Method and results: [EVALUATION.md](EVALUATION.md).

## 6e. Local chat model (llama.cpp)

Answers can use a real model running on the CPU: Qwen2.5 1.5B Instruct (Apache-2.0, 4-bit GGUF, 1.12 GB) served by llama.cpp in Docker.

```powershell
# from apps/api: download the pinned file (revision and SHA-256 are checked)
uv run python -m app.cli download-chat-model
# from the repository root: start the server (image ghcr.io/ggml-org/llama.cpp:server-b12407, 282 MB)
docker compose --profile llm up -d llm
docker compose --profile llm ps       # wait for "healthy": loading took about a minute on the dev laptop
```

Then set, for example in `apps/api/.env`: `EASA_MODEL_PROVIDER=llamacpp` and `EASA_MODEL_NAME=qwen2.5-1.5b-instruct-q4_k_m`. Readiness reports `model: ok` once the server has loaded the model. On the dev laptop (4 cores) an answer took 6–17 seconds and the server used about 780 MB of memory.

Live model tests (skipped unless the server is running; never run in CI):

```powershell
$env:EASA_TEST_LLM_URL = "http://127.0.0.1:8082"
uv run pytest tests/llm
$env:EASA_TEST_LLM_URL = $null
```

Stop it with `docker compose --profile llm stop llm`. The server listens only on `127.0.0.1:8082` (change with `EASA_LLM_PORT` in the root `.env`) and reads the model directory read-only.

If `download-chat-model` stays at 0 bytes, the Hugging Face "Xet" transfer backend may be blocked on your network; set `$env:HF_HUB_DISABLE_XET = "1"` for that command to use plain HTTPS (the file and its SHA-256 check are the same). Pulling the image from `ghcr.io` can be slow on some networks; let `docker pull` finish rather than restarting it.

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
