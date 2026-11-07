import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError, apiGet } from "./client";
import { getReadiness } from "./health";

const BASE_URL = "http://api.test";

/** Test double: a fetch that returns one canned response. */
function fakeFetch(body: string, init: { status?: number; correlationId?: string } = {}) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init.correlationId) headers.set("X-Correlation-ID", init.correlationId);
  return vi.fn<typeof fetch>(async () => new Response(body, { status: init.status ?? 200, headers }));
}

/** Test double: a fetch that never resolves until its signal aborts. */
function hangingFetch() {
  return vi.fn<typeof fetch>(
    (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      }),
  );
}

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => {
      throw new Error("expected the request to fail");
    },
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

const okSchema = z.object({ status: z.literal("ok") });

describe("apiGet", () => {
  it("sends a credential-free JSON GET to the joined URL", async () => {
    const fetchImpl = fakeFetch('{"status":"ok"}');

    await apiGet(BASE_URL, "/api/v1/health", { schema: okSchema, fetchImpl });

    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("http://api.test/api/v1/health");
    expect(init).toMatchObject({
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
  });

  it("returns validated data and the correlation ID", async () => {
    const fetchImpl = fakeFetch('{"status":"ok","extra":"ignored"}', { correlationId: "abc" });

    const result = await apiGet(BASE_URL, "/x", { schema: okSchema, fetchImpl });

    expect(result).toEqual({ data: { status: "ok" }, status: 200, correlationId: "abc" });
  });

  it("rejects a 2xx body that does not match the schema", async () => {
    const fetchImpl = fakeFetch('{"status":"maybe"}', { correlationId: "abc" });

    const error = await captureError(apiGet(BASE_URL, "/x", { schema: okSchema, fetchImpl }));

    expect(error.kind).toBe("invalid_response");
    expect(error.correlationId).toBe("abc");
  });

  it("rejects a body that is not JSON", async () => {
    const fetchImpl = fakeFetch("<html>proxy error</html>", { status: 200 });

    const error = await captureError(apiGet(BASE_URL, "/x", { schema: okSchema, fetchImpl }));

    expect(error.kind).toBe("invalid_response");
  });

  it("maps the standard error envelope to an http ApiError", async () => {
    const fetchImpl = fakeFetch(
      '{"error":{"code":"not_found","message":"Not Found","correlation_id":"cid-1"}}',
      { status: 404, correlationId: "cid-1" },
    );

    const error = await captureError(apiGet(BASE_URL, "/x", { schema: okSchema, fetchImpl }));

    expect(error).toMatchObject({
      kind: "http",
      status: 404,
      code: "not_found",
      message: "Not Found",
      correlationId: "cid-1",
    });
  });

  it("uses a generic message when an error body is not the standard envelope", async () => {
    const fetchImpl = fakeFetch('{"detail":"something"}', { status: 502, correlationId: "cid-2" });

    const error = await captureError(apiGet(BASE_URL, "/x", { schema: okSchema, fetchImpl }));

    expect(error).toMatchObject({ kind: "http", status: 502, code: null, correlationId: "cid-2" });
    expect(error.message).toBe("The API request failed with status 502.");
  });

  it("reports a network failure", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError("Failed to fetch");
    });

    const error = await captureError(apiGet(BASE_URL, "/x", { schema: okSchema, fetchImpl }));

    expect(error.kind).toBe("network");
  });

  it("times out", async () => {
    const error = await captureError(
      apiGet(BASE_URL, "/x", { schema: okSchema, fetchImpl: hangingFetch(), timeoutMs: 10 }),
    );

    expect(error.kind).toBe("timeout");
  });

  it("propagates a caller abort without converting it to an ApiError", async () => {
    const controller = new AbortController();
    const request = apiGet(BASE_URL, "/x", {
      schema: okSchema,
      fetchImpl: hangingFetch(),
      signal: controller.signal,
    });
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("getReadiness", () => {
  it("parses a ready response", async () => {
    const fetchImpl = fakeFetch('{"status":"ready","checks":{"database":"ok"}}');

    const result = await getReadiness(BASE_URL, { fetchImpl });

    expect(result.data).toEqual({ status: "ready", checks: { database: "ok" } });
    expect(fetchImpl.mock.calls[0]![0]).toBe("http://api.test/api/v1/health/ready");
  });

  it("treats a 503 not_ready body as a valid result", async () => {
    const fetchImpl = fakeFetch('{"status":"not_ready","checks":{"database":"unavailable"}}', {
      status: 503,
    });

    const result = await getReadiness(BASE_URL, { fetchImpl });

    expect(result.status).toBe(503);
    expect(result.data.checks.database).toBe("unavailable");
  });
});
