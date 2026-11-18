import { describe, expect, it, vi } from "vitest";

import { parseServerConfig, serverConfig } from "./config";

describe("parseServerConfig", () => {
  it("defaults to the local API", () => {
    expect(parseServerConfig({ apiUrl: undefined })).toEqual({
      apiUrl: "http://localhost:8000",
    });
    expect(parseServerConfig({ apiUrl: "" })).toEqual({
      apiUrl: "http://localhost:8000",
    });
  });

  it("accepts https and strips a trailing slash", () => {
    expect(parseServerConfig({ apiUrl: "https://api.example.com/" })).toEqual({
      apiUrl: "https://api.example.com",
    });
  });

  it.each([
    "not a url",
    "ftp://api.example.com",
    "javascript:alert(1)",
    "http://localhost:8000/api",
    "http://localhost:8000?x=1",
    "http://user:secret@localhost:8000",
  ])("rejects %s", (apiUrl) => {
    expect(() => parseServerConfig({ apiUrl })).toThrow(/EASA_API_URL/);
  });

  it("reads EASA_API_URL at call time", () => {
    vi.stubEnv("EASA_API_URL", "http://127.0.0.1:9000");
    expect(serverConfig().apiUrl).toBe("http://127.0.0.1:9000");
  });
});
