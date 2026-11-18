import { describe, expect, it } from "vitest";

import { PROXIED_ROUTES, findRoute } from "./routes";

const ID = "0f8fad5b-d9cb-469f-a165-70867728950e";

describe("the proxy allowlist", () => {
  it.each([
    ["GET", "/documents"],
    ["POST", "/documents"],
    ["PATCH", `/documents/${ID}`],
    ["POST", `/conversations/${ID}/messages`],
    ["POST", `/agent/actions/${ID}/confirm`],
    ["GET", "/audit"],
  ])("allows %s %s", (method, path) => {
    expect(findRoute(method, path)).toBeDefined();
  });

  it.each([
    ["GET", "/tools"],
    ["POST", "/auth/login"],
    ["GET", "/auth/me"],
    ["GET", `/documents/${ID}/chunks/extra`],
    ["GET", `/documents/${ID}x`],
    ["PUT", "/documents"],
    ["GET", "/DOCUMENTS"],
  ])("refuses %s %s", (method, path) => {
    expect(findRoute(method, path)).toBeUndefined();
  });

  it("marks only the health checks as public and the model routes as slow", () => {
    const publicPaths = ["/health", "/health/ready", "/documents", "/users", "/audit"].filter(
      (path) => PROXIED_ROUTES.some((r) => r.public && r.pattern.test(path)),
    );
    expect(publicPaths).toEqual(["/health", "/health/ready"]);
    expect(findRoute("POST", "/agent")?.slow).toBe(true);
    expect(findRoute("POST", "/search")?.slow).toBeUndefined();
  });
});
