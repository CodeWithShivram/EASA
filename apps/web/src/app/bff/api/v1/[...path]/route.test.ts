// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, PATCH, POST } from "./route";

const ORIGIN = "http://localhost:3000";
const ID = "0f8fad5b-d9cb-469f-a165-70867728950e";

function request(
  method: string,
  path: string,
  {
    cookie = "easa_session=good-token",
    origin = ORIGIN,
    body,
    headers = {},
  }: {
    cookie?: string;
    origin?: string | null;
    body?: string;
    headers?: Record<string, string>;
  } = {},
) {
  const all: Record<string, string> = { ...headers };
  if (cookie) all.cookie = cookie;
  if (origin) all.origin = origin;
  return new NextRequest(`${ORIGIN}/bff/api/v1${path}`, {
    method,
    headers: all,
    body,
  });
}

function context(path: string) {
  return { params: Promise.resolve({ path: path.split("/").filter(Boolean) }) };
}

let api: ReturnType<typeof vi.fn>;

beforeEach(() => {
  api = vi.fn(async () =>
    Response.json({ items: [] }, { status: 200, headers: { "X-Correlation-ID": "abc123" } }),
  );
  vi.stubGlobal("fetch", api);
});

afterEach(() => vi.unstubAllGlobals());

function forwarded(): {
  url: string;
  init: RequestInit & { headers: Record<string, string> };
} {
  const [url, init] = api.mock.calls[0] as [
    string,
    RequestInit & { headers: Record<string, string> },
  ];
  return { url, init };
}

describe("the proxy", () => {
  it("forwards allowlisted requests with the session token and the query string", async () => {
    const response = await GET(request("GET", "/documents?limit=5"), context("documents"));

    expect(response.status).toBe(200);
    expect(response.headers.get("X-Correlation-ID")).toBe("abc123");
    const { url, init } = forwarded();
    expect(url).toBe("http://localhost:8000/api/v1/documents?limit=5");
    expect(init.headers.Authorization).toBe("Bearer good-token");
    expect(init.redirect).toBe("manual");
  });

  it("never forwards the browser's own Authorization header or cookies", async () => {
    await GET(
      request("GET", "/documents", {
        headers: { authorization: "Bearer someone-else" },
      }),
      context("documents"),
    );

    const { init } = forwarded();
    expect(init.headers.Authorization).toBe("Bearer good-token");
    expect(Object.keys(init.headers).map((h) => h.toLowerCase())).not.toContain("cookie");
  });

  it.each([
    ["GET", "/tools"], // development-only API route
    ["POST", "/tools/get_ticket/invoke"],
    ["POST", "/auth/login"], // sign-in goes through /bff/session
    ["GET", "/documents/not-an-id"],
    ["DELETE", "/documents"],
    ["GET", "/health/../users"],
  ])("refuses %s %s, which is not on the allowlist", async (method, path) => {
    const handler = method === "POST" ? POST : GET;
    const response = await handler(request(method, path), context(path));

    expect(response.status).toBe(404);
    expect(api).not.toHaveBeenCalled();
  });

  it.each([null, "https://evil.example", "http://localhost:3001"])(
    "refuses changes from origin %s",
    async (origin) => {
      const response = await POST(
        request("POST", "/conversations", { origin }),
        context("conversations"),
      );

      expect(response.status).toBe(403);
      expect((await response.json()).error.code).toBe("bad_origin");
      expect(api).not.toHaveBeenCalled();
    },
  );

  it("needs a session except for health checks", async () => {
    const without = await GET(request("GET", "/documents", { cookie: "" }), context("documents"));
    const health = await GET(
      request("GET", "/health/ready", { cookie: "" }),
      context("health/ready"),
    );

    expect(without.status).toBe(401);
    expect(health.status).toBe(200);
    expect(api).toHaveBeenCalledTimes(1);
    expect(forwarded().init.headers.Authorization).toBeUndefined();
  });

  it("forwards bodies with their content type", async () => {
    await PATCH(
      request("PATCH", `/documents/${ID}`, {
        body: JSON.stringify({ min_role: "manager" }),
        headers: { "content-type": "application/json" },
      }),
      context(`documents/${ID}`),
    );

    const { init } = forwarded();
    expect(init.method).toBe("PATCH");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe('{"min_role":"manager"}');
  });

  it("refuses bodies over the upload limit", async () => {
    const response = await POST(
      request("POST", "/documents", {
        headers: { "content-length": String(20 * 1024 * 1024) },
      }),
      context("documents"),
    );

    expect(response.status).toBe(413);
    expect(api).not.toHaveBeenCalled();
  });

  it("clears the cookie when the API no longer accepts the token", async () => {
    api.mockResolvedValueOnce(
      Response.json({ error: { code: "not_authenticated" } }, { status: 401 }),
    );

    const response = await GET(request("GET", "/documents"), context("documents"));

    expect(response.status).toBe(401);
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toMatch(/easa_session=;/);
    expect(cookie).toMatch(/Max-Age=0/);
  });

  it("reports an unreachable or slow API", async () => {
    api.mockRejectedValueOnce(new TypeError("fetch failed"));
    const unreachable = await GET(request("GET", "/documents"), context("documents"));
    api.mockRejectedValueOnce(new DOMException("timed out", "TimeoutError"));
    const slow = await GET(request("GET", "/documents"), context("documents"));

    expect([unreachable.status, slow.status]).toEqual([502, 504]);
    expect((await slow.json()).error.code).toBe("api_timeout");
  });

  it("uses EASA_API_URL", async () => {
    vi.stubEnv("EASA_API_URL", "http://127.0.0.1:9000");

    await GET(request("GET", "/documents"), context("documents"));

    expect(forwarded().url).toBe("http://127.0.0.1:9000/api/v1/documents");
  });
});
