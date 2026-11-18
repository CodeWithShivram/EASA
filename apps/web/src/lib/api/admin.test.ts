import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi } from "./admin";

afterEach(() => vi.unstubAllGlobals());

describe("adminApi", () => {
  it("builds audit queries from the filters", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await adminApi.audit({}, 0);
    await adminApi.audit({ action: "auth.login", outcome: "failed", userId: "u1" }, 50);

    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "/bff/api/v1/audit?limit=50&offset=0",
      "/bff/api/v1/audit?limit=50&offset=50&action=auth.login&outcome=failed&user_id=u1",
    ]);
  });

  it("sends user changes and password resets", async () => {
    const user = {
      id: "u1",
      username: "erin",
      role: "manager",
      is_active: true,
      locked: false,
      created_at: "x",
    };
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json(user));
    vi.stubGlobal("fetch", fetchMock);

    await adminApi.updateUser("u1", { role: "manager" });
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await adminApi.resetPassword("u1", "a new password!");

    expect(fetchMock.mock.calls.map((c) => [c[0], c[1]?.method, c[1]?.body])).toEqual([
      ["/bff/api/v1/users/u1", "PATCH", '{"role":"manager"}'],
      ["/bff/api/v1/users/u1/password", "POST", '{"password":"a new password!"}'],
    ]);
  });
});
