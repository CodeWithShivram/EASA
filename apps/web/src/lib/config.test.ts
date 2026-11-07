import { describe, expect, it } from "vitest";

import { parsePublicConfig } from "./config";

describe("parsePublicConfig", () => {
  it("defaults to the local API", () => {
    expect(parsePublicConfig({ apiBaseUrl: undefined })).toEqual({
      apiBaseUrl: "http://localhost:8000",
    });
  });

  it("accepts https and strips a trailing slash", () => {
    expect(parsePublicConfig({ apiBaseUrl: "https://api.example.com/" })).toEqual({
      apiBaseUrl: "https://api.example.com",
    });
  });

  it.each([
    "not a url",
    "ftp://api.example.com",
    "javascript:alert(1)",
    "http://localhost:8000/api",
    "http://localhost:8000?x=1",
  ])("rejects %s", (apiBaseUrl) => {
    expect(() => parsePublicConfig({ apiBaseUrl })).toThrow(/NEXT_PUBLIC_API_BASE_URL/);
  });
});
