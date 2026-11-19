import { afterEach, describe, expect, it, vi } from "vitest";

import { agentApi } from "./agent";

const ACTION = {
  id: "0f8fad5b-d9cb-469f-a165-70867728950e",
  tool: "create_draft_ticket",
  arguments: { title: "Chair" },
  status: "cancelled",
  result: null,
  created_at: "x",
  expires_at: "x",
  decided_at: "x",
};

afterEach(() => vi.unstubAllGlobals());

describe("agentApi", () => {
  it("runs, confirms and cancels through the backend for frontend", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({
        status: "answered",
        answer: "Hi",
        reason: null,
        steps: [],
        pending_action: null,
        model_id: null,
        sources: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    expect((await agentApi.run("Hello")).answer).toBe("Hi");
    fetchMock.mockResolvedValueOnce(
      Response.json({
        action: { ...ACTION, status: "confirmed" },
        result: {
          tool: "create_draft_ticket",
          outcome: "succeeded",
          output: { number: 8 },
          message: null,
        },
      }),
    );
    expect((await agentApi.confirm(ACTION.id)).result.output).toEqual({ number: 8 });
    fetchMock.mockResolvedValueOnce(Response.json(ACTION));
    expect((await agentApi.cancel(ACTION.id)).status).toBe("cancelled");

    expect(fetchMock.mock.calls.map((c) => [c[0], c[1]?.method])).toEqual([
      ["/bff/api/v1/agent", "POST"],
      [`/bff/api/v1/agent/actions/${ACTION.id}/confirm`, "POST"],
      [`/bff/api/v1/agent/actions/${ACTION.id}/cancel`, "POST"],
    ]);
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe('{"message":"Hello"}');
  });
});
