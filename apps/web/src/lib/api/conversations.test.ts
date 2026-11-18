import { afterEach, describe, expect, it, vi } from "vitest";

import { chatApi } from "./conversations";

const CITATION = {
  document_id: "0f8fad5b-d9cb-469f-a165-70867728950e",
  filename: "leave.txt",
  page_number: null,
  section: null,
  chunk_index: 3,
  char_start: 0,
  char_end: 10,
};

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>(async () =>
    body === null ? new Response(null, { status }) : Response.json(body, { status }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("chatApi", () => {
  it("asks through the backend for frontend with a long timeout", async () => {
    const fetchMock = stubFetch({
      conversation_id: "c1",
      turn: 1,
      answer: {
        status: "answered",
        answer: "Yes [S1].",
        reason: null,
        sources: [],
        retrieved: 1,
        model_id: "m",
      },
    });

    const result = await chatApi.ask("c1", "Question?");

    expect(result.turn).toBe(1);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/bff/api/v1/conversations/c1/messages");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe('{"question":"Question?"}');
  });

  it("loads one cited chunk by offset and checks it is the right one", async () => {
    const fetchMock = stubFetch({ items: [{ chunk_index: 3, text: "The text." }] });

    expect(await chatApi.chunkText(CITATION)).toBe("The text.");
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/bff/api/v1/documents/${CITATION.document_id}/chunks?offset=3&limit=1`,
    );

    stubFetch({ items: [] });
    await expect(chatApi.chunkText(CITATION)).rejects.toThrow("no longer available");
  });

  it("lists, creates and deletes conversations", async () => {
    const summary = { id: "c1", created_at: "x", updated_at: "x", messages: 0 };
    let fetchMock = stubFetch({ items: [summary] });
    expect(await chatApi.list()).toEqual([summary]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/bff/api/v1/conversations?limit=100");

    fetchMock = stubFetch(summary, 201);
    expect((await chatApi.create()).id).toBe("c1");

    fetchMock = stubFetch(null, 204);
    await chatApi.remove("c1");
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("DELETE");
  });
});
