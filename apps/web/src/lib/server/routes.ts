/**
 * The API routes the browser may reach through the backend for frontend
 * (`/bff/api/v1/...`). Anything not listed is refused before it reaches the
 * API; the API still checks every permission itself. Development-only tool
 * endpoints and the API's own sign-in route are deliberately absent.
 */

export interface ProxiedRoute {
  method: "GET" | "POST" | "PATCH" | "DELETE";
  pattern: RegExp;
  /** Reachable without a session (health checks only). */
  public?: boolean;
  /** Answers and the agent wait for the CPU model: up to a few minutes. */
  slow?: boolean;
}

const ID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";

const route = (
  method: ProxiedRoute["method"],
  path: string,
  extra: Partial<ProxiedRoute> = {},
): ProxiedRoute => ({
  method,
  pattern: new RegExp(`^${path.replaceAll(":id", ID)}$`),
  ...extra,
});

export const PROXIED_ROUTES: readonly ProxiedRoute[] = [
  route("GET", "/health", { public: true }),
  route("GET", "/health/ready", { public: true }),
  route("GET", "/documents"),
  route("POST", "/documents"),
  route("GET", "/documents/:id"),
  route("PATCH", "/documents/:id"),
  route("GET", "/documents/:id/chunks"),
  route("POST", "/search"),
  route("POST", "/answers", { slow: true }),
  route("GET", "/conversations"),
  route("POST", "/conversations"),
  route("GET", "/conversations/:id"),
  route("DELETE", "/conversations/:id"),
  route("POST", "/conversations/:id/messages", { slow: true }),
  route("POST", "/agent", { slow: true }),
  route("GET", "/agent/actions/:id"),
  route("POST", "/agent/actions/:id/confirm"),
  route("POST", "/agent/actions/:id/cancel"),
  route("GET", "/users"),
  route("POST", "/users"),
  route("PATCH", "/users/:id"),
  route("POST", "/users/:id/password"),
  route("GET", "/audit"),
];

export function findRoute(method: string, path: string): ProxiedRoute | undefined {
  return PROXIED_ROUTES.find((r) => r.method === method && r.pattern.test(path));
}
