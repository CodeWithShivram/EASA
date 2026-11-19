// Shared settings of the browser tests (P8-M3), used by the stack script,
// the Playwright configuration and the tests.

export const API_PORT = 8200;
export const WEB_PORT = 3200;
// Relative to apps/web; git-ignored.
export const E2E_DIR = ".e2e";
export const TENANT = "e2e";
export const ROLES = ["employee", "manager", "administrator"];

export function username(role) {
  return `e2e-${role}`;
}
