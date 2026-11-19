// Starts the API for the browser tests (P8-M3): a fresh SQLite database in
// apps/web/.e2e (git-ignored), one synthetic user per role with a generated
// password, the user's synthetic tickets, the fake chat model and the hashing
// embedder (no model files), then uvicorn. Run by Playwright's webServer.
//
// The passwords are written only to .e2e/credentials.json, which the tests
// read; they are never printed.

import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { API_PORT, E2E_DIR, ROLES, TENANT, username } from "./config.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const apiDir = resolve(here, "../../api");
const dataDir = resolve(here, "..", E2E_DIR);

rmSync(dataDir, { recursive: true, force: true });
mkdirSync(join(dataDir, "files"), { recursive: true });

const env = {
  ...process.env,
  EASA_ENVIRONMENT: "development",
  EASA_DATABASE_URL: `sqlite:///${join(dataDir, "e2e.db").replaceAll("\\", "/")}`,
  EASA_DOCUMENT_STORAGE_DIR: join(dataDir, "files"),
  EASA_MODEL_PROVIDER: "fake",
  EASA_EMBEDDING_PROVIDER: "hashing",
  EASA_LOG_LEVEL: "WARNING",
  // Every test signs in through the same web server; keep the limits out of the way.
  EASA_RATE_LIMIT_LOGIN_PER_MINUTE: "500",
  EASA_RATE_LIMIT_MODEL_PER_MINUTE: "500",
};

function run(args, input) {
  const result = spawnSync("uv", ["run", ...args], {
    cwd: apiDir,
    env,
    input,
    stdio: ["pipe", "ignore", "inherit"],
  });
  if (result.status !== 0) {
    throw new Error(`uv run ${args.slice(0, 4).join(" ")} failed with exit code ${result.status}`);
  }
}

run(["alembic", "upgrade", "head"]);
const credentials = {};
for (const role of ROLES) {
  const password = randomBytes(18).toString("base64url");
  run(
    [
      "python",
      "-m",
      "app.cli",
      "create-user",
      "--tenant",
      TENANT,
      "--username",
      username(role),
      "--role",
      role,
      "--password-stdin",
    ],
    `${password}\n`,
  );
  credentials[role] = { username: username(role), password };
}
run(["python", "-m", "app.cli", "seed-tickets", "--username", username("employee")]);
writeFileSync(join(dataDir, "credentials.json"), JSON.stringify(credentials), { mode: 0o600 });

const server = spawn(
  "uv",
  [
    "run",
    "uvicorn",
    "app.main:create_app",
    "--factory",
    "--host",
    "127.0.0.1",
    "--port",
    String(API_PORT),
    "--no-access-log",
    "--no-proxy-headers",
  ],
  { cwd: apiDir, env, stdio: "inherit" },
);
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
