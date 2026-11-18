// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, proxy } from "./proxy";

describe("proxy", () => {
  it("sends pages without a session cookie to the sign-in page", () => {
    const response = proxy(new NextRequest("http://localhost:3000/documents"));

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/login");
  });

  it("lets requests with a session cookie through (the API decides validity)", () => {
    const response = proxy(
      new NextRequest("http://localhost:3000/", {
        headers: { cookie: "easa_session=tok" },
      }),
    );

    expect(response.headers.get("location")).toBeNull();
  });

  it("does not run for the sign-in page, the bff routes or static files", () => {
    const matcher = new RegExp(`^${config.matcher[0]}$`);

    for (const path of [
      "/login",
      "/bff/session",
      "/bff/api/v1/health",
      "/_next/static/x.js",
      "/favicon.ico",
    ]) {
      expect(matcher.test(path)).toBe(false);
    }
    for (const path of ["/", "/documents", "/chat"]) {
      expect(matcher.test(path)).toBe(true);
    }
  });
});
