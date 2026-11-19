// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

const ORIGIN = "http://localhost:3000";
const USER = {
  user_id: "u1",
  username: "alice",
  role: "manager",
  tenant_id: "t1",
  permissions: ["knowledge:search"],
};

function request(
  method: string,
  { cookie = "", origin = ORIGIN as string | null, body = undefined as string | undefined } = {},
) {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (cookie) headers.cookie = cookie;
  if (origin) headers.origin = origin;
  return new NextRequest(`${ORIGIN}/bff/session`, { method, headers, body });
}

let api: ReturnType<typeof vi.fn>;

beforeEach(() => {
  api = vi.fn();
  vi.stubGlobal("fetch", api);
});

afterEach(() => vi.unstubAllGlobals());

describe("POST /bff/session (sign in)", () => {
  it("keeps the token in an HttpOnly, SameSite=Strict cookie and out of the response", async () => {
    api.mockResolvedValueOnce(
      Response.json({
        token: "secret-token-value",
        token_type: "bearer",
        expires_at: "2026-11-19T10:00:00Z",
        user: USER,
      }),
    );

    const response = await POST(
      request("POST", {
        body: JSON.stringify({ username: "alice", password: "pw" }),
      }),
    );

    expect(response.status).toBe(200);
    const text = await response.text();
    expect(text).not.toContain("secret-token-value");
    expect(JSON.parse(text).user.username).toBe("alice");
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("easa_session=secret-token-value");
    expect(cookie).toMatch(/HttpOnly/i);
    expect(cookie).toMatch(/SameSite=strict/i);
    expect(cookie).toMatch(/Path=\//);
    const [url, init] = api.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/auth/login");
    expect(init.body).toBe('{"username":"alice","password":"pw"}');
  });

  it("passes the browser's forwarded address on, for the API's sign-in limit", async () => {
    api.mockResolvedValueOnce(
      Response.json(
        { error: { code: "rate_limited", message: "Too many requests.", correlation_id: null } },
        { status: 429 },
      ),
    );
    const req = new NextRequest(`${ORIGIN}/bff/session`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: ORIGIN,
        "x-forwarded-for": "198.51.100.7",
      },
      body: '{"username":"a","password":"b"}',
    });

    const response = await POST(req);

    expect(response.status).toBe(429);
    const init = api.mock.calls[0]?.[1] as { headers: Record<string, string> };
    expect(init.headers["X-Forwarded-For"]).toBe("198.51.100.7");
  });

  it("relays a failed sign-in without setting a cookie", async () => {
    api.mockResolvedValueOnce(
      Response.json(
        {
          error: {
            code: "invalid_credentials",
            message: "Invalid username or password.",
            correlation_id: "c1",
          },
        },
        { status: 401 },
      ),
    );

    const response = await POST(request("POST", { body: '{"username":"a","password":"b"}' }));

    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe("invalid_credentials");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("refuses sign-ins from other origins (login CSRF)", async () => {
    const response = await POST(request("POST", { origin: "https://evil.example", body: "{}" }));

    expect(response.status).toBe(403);
    expect(api).not.toHaveBeenCalled();
  });

  it("refuses a body that is not JSON", async () => {
    const response = await POST(request("POST", { body: "username=alice" }));

    expect(response.status).toBe(422);
    expect(api).not.toHaveBeenCalled();
  });
});

describe("GET /bff/session (current user)", () => {
  it("needs a session cookie", async () => {
    expect((await GET(request("GET"))).status).toBe(401);
    expect(api).not.toHaveBeenCalled();
  });

  it("returns the user and clears an expired session", async () => {
    api.mockResolvedValueOnce(Response.json(USER));
    const ok = await GET(request("GET", { cookie: "easa_session=tok" }));
    api.mockResolvedValueOnce(
      Response.json({ error: { code: "not_authenticated" } }, { status: 401 }),
    );
    const expired = await GET(request("GET", { cookie: "easa_session=old" }));

    expect(await ok.json()).toEqual(USER);
    expect(
      (api.mock.calls[0]?.[1] as { headers: Record<string, string> }).headers.Authorization,
    ).toBe("Bearer tok");
    expect(expired.status).toBe(401);
    expect(expired.headers.get("set-cookie")).toMatch(/Max-Age=0/);
  });
});

describe("DELETE /bff/session (sign out)", () => {
  it("ends the API session and clears the cookie", async () => {
    api.mockResolvedValueOnce(new Response(null, { status: 204 }));

    const response = await DELETE(request("DELETE", { cookie: "easa_session=tok" }));

    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/);
    expect(api.mock.calls[0]?.[0]).toBe("http://localhost:8000/api/v1/auth/logout");
  });

  it("still clears the cookie when the API is down", async () => {
    api.mockRejectedValueOnce(new TypeError("fetch failed"));

    const response = await DELETE(request("DELETE", { cookie: "easa_session=tok" }));

    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/);
  });

  it("refuses sign-outs from other origins", async () => {
    expect(
      (await DELETE(request("DELETE", { cookie: "easa_session=tok", origin: null }))).status,
    ).toBe(403);
  });
});
