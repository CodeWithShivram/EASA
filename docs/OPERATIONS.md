# EASA — Operations Runbook

> **Status:** Phase 8, P8-M5 (2026-11-19). It describes running the container stack on one machine with synthetic data ([ADR-039](ARCHITECTURE_DECISIONS.md#adr-039)). This is not a production deployment guide; [PROJECT_REPORT.md](PROJECT_REPORT.md#7-known-limitations) lists what a real deployment would still need.

Commands run from the repository root in PowerShell unless stated otherwise. `docker compose` reads the git-ignored `.env` there (`EASA_POSTGRES_PASSWORD`).

## 1. The stack

| Service | Image | Port (localhost only) | Notes |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:0.8.7-pg18` (pinned by digest) | 5433 | Volume `easa_postgres-data`. Holds the development database `easa` and the stack's own database `easa_app` |
| `app-db` | same | - | One-shot step: creates `easa_app` if it is missing, then exits |
| `api` | `easa-api:local`, built from `apps/api/Dockerfile` | 8000 | Production mode, non-root user. Runs `alembic upgrade head` on every start, then Uvicorn with `--no-proxy-headers`. Uploads in volume `easa_uploads`; models mounted read-only from `apps/api/var/models` |
| `web` | `easa-web:local`, built from `apps/web/Dockerfile` | 3000 | `next start`, non-root. Talks to the API at `http://api:8000` |
| `llm` | `ghcr.io/ggml-org/llama.cpp:server-b12407` (pinned) | 8082 | Profile `llm`; CPU only, one request at a time |

## 2. Start and stop

| Task | Command |
|---|---|
| Start everything, with demo data the first time | `powershell -ExecutionPolicy Bypass -File scripts\demo.ps1` |
| Start without the chat model (fake model, development mode) | `scripts\demo.ps1 -NoModel` |
| Stop (data kept) | `scripts\demo.ps1 -Down` |
| Delete the demo data (`easa_app`, uploads, demo credentials) | `scripts\demo.ps1 -Reset` |
| Status and health | `docker compose --profile app --profile llm ps` |
| Rebuild after a code change | `docker compose --profile app --profile llm up -d --build --wait` |

`demo.ps1` builds the images, starts the services and waits until every health check passes. It loads the demo data once: three users, 16 synthetic documents at three visibility levels, and 7 tickets. The users' generated passwords go to `var\demo\credentials.txt` (git-ignored) and are never printed. Without the model file, the API runs in development mode with the fake model. Without the embedding model, search uses the hashing embedder. The script warns in both cases.

## 3. Health and logs

- Liveness: `GET http://localhost:8000/api/v1/health`. Readiness (database, embedding model, chat model): `GET /api/v1/health/ready`, which returns `503` with the failing check.
- Logs are JSON lines on stderr: `docker compose logs -f api`. Every request has a server-generated `correlation_id`, which is also returned in the `X-Correlation-ID` header and the error body; search the logs for it. Messages, questions, answers, passwords and tokens are never logged.
- Useful messages:
  - `request completed` (method, path, status, duration);
  - `answer completed` (status, tokens, duration);
  - `agent run finished` (steps, tokens, duration);
  - `sign-in failed` / `sign-in refused`;
  - `database unavailable`;
  - `database ping failed`.

## 4. Users

| Task | How |
|---|---|
| Create a user | `docker compose exec -T api python -m app.cli create-user --tenant "Larkspur Analytics" --username NAME --role employee --password-stdin`, then type the password and press Enter. Or use **Admin → Create a user** in the web app as an administrator |
| Change a role, disable or enable, reset a password | **Admin** page (administrators only). A disabled user's sessions stop working at once. Administrators cannot change or disable themselves |
| A user is locked out | Five failed sign-ins lock an account for 15 minutes; it unlocks by itself. Many `429 rate_limited` responses for everyone mean the sign-in limit of the web server's address was reached (20 a minute), which clears within a minute |
| Load documents | **Documents** page, or `docker compose exec -T api python -m app.cli upload-documents --username NAME --min-role employee FILE...` (files inside the container). Both are audited |
| Review activity | **Admin → Audit log** (sign-ins, refusals, user changes, uploads, assistant tool calls) |

## 5. Backup and restore

Back up the stack's database and the uploaded files together. Both commands were run and checked in P8-M5: a restore into a scratch database had the same row counts, and the extracted archive matched the volume's file checksums.

```powershell
New-Item -ItemType Directory -Force var\backup | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
# Database (custom format; written inside the container, then copied out)
docker compose exec -T postgres pg_dump -U easa -Fc -f /tmp/easa_app.dump easa_app
docker compose cp postgres:/tmp/easa_app.dump "var/backup/easa_app-$stamp.dump"
docker compose exec -T postgres rm /tmp/easa_app.dump
# Uploaded files
docker run --rm -v easa_uploads:/data:ro -v "${PWD}\var\backup:/backup" easa-api:local tar czf "/backup/uploads-$stamp.tgz" -C /data .
```

Restore (stop the API and web first: `docker compose --profile app stop api web`):

```powershell
docker compose cp var/backup/easa_app-<stamp>.dump postgres:/tmp/restore.dump
docker compose exec -T postgres dropdb -U easa --if-exists --force easa_app
docker compose exec -T postgres createdb -U easa easa_app
docker compose exec -T postgres pg_restore -U easa -d easa_app --no-owner /tmp/restore.dump
docker run --rm -v easa_uploads:/data -v "${PWD}\var\backup:/backup:ro" --user root easa-api:local sh -c "rm -rf /data/* && tar xzf /backup/uploads-<stamp>.tgz -C /data && chown -R 10001:10001 /data"
docker compose --profile app --profile llm up -d --wait
```

Do not pipe `pg_dump` output through PowerShell (`>`): Windows PowerShell re-encodes binary output and corrupts the dump. Use `-f` and `docker compose cp` as above. Backups contain password hashes and the documents; keep them as private as the database.

## 6. Upgrades

1. `git pull`, then `docker compose --profile app --profile llm up -d --build --wait`. The API applies new migrations when it starts.
2. Changing evaluation data needs a new manifest version (`update-eval-manifest`), see the [Development guide](DEVELOPMENT_GUIDE.md#6d-retrieval-evaluation).
3. Base images are pinned by digest in the Dockerfiles and `compose.yaml`. To update one, pull the new tag, take the digest from `docker image inspect --format "{{index .RepoDigests 0}}" <image>`, and update the reference and SECURITY.md.

## 7. Incidents

| Symptom | Likely cause | What to do |
|---|---|---|
| Pages load, but every action says the server is unreachable; the API answers `502 api_unreachable` through the web app | The API container is down or restarting | `docker compose --profile app ps`; `docker compose logs api`; `docker compose --profile app up -d --wait api`. The load test measured recovery in 9–17 s |
| `503 database_unavailable` with `Retry-After: 5`; readiness `503` | PostgreSQL is stopped or unreachable | `docker compose up -d --wait postgres`. The API reconnects by itself; no restart needed (measured: serving again immediately) |
| Chat and the assistant say the model is unavailable (`503 model_unavailable`); search still works | The `llm` container is down or still loading the model | `docker compose --profile llm up -d --wait llm`; about 20–35 s until ready |
| Answers take minutes | One CPU model answers one request at a time; others queue (three at once took 36–110 s each in the load test) | Expected on this hardware. The model call limit (10 a minute per user) bounds the queue |
| Many `429 rate_limited` | The sign-in limit (per client address; all web sign-ins share the web server's) or the model call limit (per user) | Wait for `Retry-After`. Raise `EASA_RATE_LIMIT_*` only with a reason (ADR-035) |
| A password may be known to someone else | - | Reset it on the Admin page; a reset ends all of that user's sessions at once. Disabling the user does too |
| A secret was committed or pushed | - | Treat it as compromised: change it where it is used (for `.env`, a new `EASA_POSTGRES_PASSWORD` needs a new database volume or `ALTER USER`), then remove it from the history with the repository owner. GitHub secret scanning, once enabled, reports pushes ([SECURITY.md](SECURITY.md#secret-scanning)) |
| Suspicious activity | - | Admin → Audit log: filter by user, action (Sign-in `auth.login`, Request refused `access.denied`) and outcome; correlate with the logs by correlation ID |

## 8. Load and failure tests

```powershell
uv run --project apps/api python scripts/load_test.py            # load only, about 3 minutes
uv run --project apps/api python scripts/load_test.py --failures # also stops PostgreSQL, the model and the API in turn
```

It needs the running demo stack and `var\demo\credentials.txt`. It goes through the web app like a browser and writes a report to `var\loadtest\`. The sign-in burst at the end trips the sign-in limit for a minute. Latest results: [PROJECT_REPORT.md section 5](PROJECT_REPORT.md#5-delivery-and-operations).
