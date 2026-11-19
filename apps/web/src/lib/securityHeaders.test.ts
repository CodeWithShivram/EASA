import { describe, expect, it } from "vitest";

import { contentSecurityPolicy, securityHeaders } from "./securityHeaders";

const header = (env: string, key: string) => securityHeaders(env).find((h) => h.key === key)?.value;

describe("securityHeaders", () => {
  it("allows scripts only from this origin and eval only in development", () => {
    expect(contentSecurityPolicy("production")).toContain("script-src 'self' 'unsafe-inline';");
    expect(contentSecurityPolicy("production")).not.toContain("unsafe-eval");
    expect(contentSecurityPolicy("development")).toContain("'unsafe-eval'");
  });

  it("blocks framing, plugins, other origins and foreign form targets", () => {
    const policy = contentSecurityPolicy("production");

    for (const directive of [
      "default-src 'self'",
      "connect-src 'self'",
      "object-src 'none'",
      "frame-ancestors 'none'",
      "form-action 'self'",
      "base-uri 'self'",
    ]) {
      expect(policy).toContain(directive);
    }
  });

  it("adds HSTS only in production and never forces https upgrades", () => {
    expect(header("production", "Strict-Transport-Security")).toMatch(/max-age=31536000/);
    expect(header("development", "Strict-Transport-Security")).toBeUndefined();
    // `next start` also serves plain http://localhost in production mode.
    expect(contentSecurityPolicy("production")).not.toContain("upgrade-insecure-requests");
  });

  it("sets the other defensive headers everywhere", () => {
    for (const env of ["development", "production", "test"]) {
      expect(header(env, "X-Content-Type-Options")).toBe("nosniff");
      expect(header(env, "X-Frame-Options")).toBe("DENY");
      expect(header(env, "Permissions-Policy")).toContain("camera=()");
    }
  });
});
