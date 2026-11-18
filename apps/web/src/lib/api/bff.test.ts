import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { bffRequest } from "./bff";
import { ApiError } from "./client";

function fakeFetch(response: Response) {
  return vi.fn<typeof fetch>(async () => response);
}

describe("bffRequest", () => {
  it("sends JSON to the same origin with cookies and validates the response", async () => {
    const fetchImpl = fakeFetch(
      Response.json({ id: "c1" }, { status: 201, headers: { "X-Correlation-ID": "abc" } }),
    );

    const result = await bffRequest("/bff/api/v1/conversations", {
      method: "POST",
      json: { question: "Hi" },
      schema: z.object({ id: z.string() }),
      fetchImpl,
    });

    expect(result).toEqual({
      data: { id: "c1" },
      status: 201,
      correlationId: "abc",
    });
    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe("/bff/api/v1/conversations");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.body).toBe('{"question":"Hi"}');
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("accepts empty responses without a schema", async () => {
    const result = await bffRequest("/bff/session", {
      method: "DELETE",
      fetchImpl: fakeFetch(new Response(null, { status: 204 })),
    });

    expect(result.status).toBe(204);
  });

  it("turns error envelopes into ApiError with the code and correlation ID", async () => {
    const fetchImpl = fakeFetch(
      Response.json(
        {
          error: {
            code: "forbidden",
            message: "You do not have permission.",
            correlation_id: "c9",
          },
        },
        { status: 403 },
      ),
    );

    const error = await bffRequest("/bff/api/v1/users", { fetchImpl }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      kind: "http",
      status: 403,
      code: "forbidden",
      correlationId: "c9",
    });
  });

  it("reports responses that do not match the schema", async () => {
    const error = await bffRequest("/x", {
      schema: z.object({ id: z.string() }),
      fetchImpl: fakeFetch(Response.json({ id: 5 })),
    }).catch((e: unknown) => e);

    expect(error).toMatchObject({ kind: "invalid_response" });
  });

  it("reports network failures and timeouts", async () => {
    const network = await bffRequest("/x", {
      fetchImpl: vi.fn(async () => {
        throw new TypeError("down");
      }),
    }).catch((e: unknown) => e);
    const timeout = await bffRequest("/x", {
      timeoutMs: 10,
      fetchImpl: vi.fn(
        (_url: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) =>
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            ),
          ),
      ),
    }).catch((e: unknown) => e);

    expect(network).toMatchObject({ kind: "network" });
    expect(timeout).toMatchObject({ kind: "timeout" });
  });
});
