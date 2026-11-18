import { afterEach, describe, expect, it, vi } from "vitest";

import { documentsApi, levelsUpTo } from "./documents";

const DOC = {
  id: "d1",
  filename: "a.txt",
  min_role: "manager",
  media_type: "text/plain",
  size_bytes: 3,
  status: "processed",
  error_code: null,
  page_count: null,
  created_at: "x",
  updated_at: "x",
};

afterEach(() => vi.unstubAllGlobals());

describe("documentsApi", () => {
  it("uploads as multipart with the level and tells new from existing documents", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json(DOC, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    const first = await documentsApi.upload(new File(["abc"], "a.txt"), "manager");
    fetchMock.mockResolvedValueOnce(Response.json(DOC, { status: 200 }));
    const again = await documentsApi.upload(new File(["abc"], "a.txt"), "manager");

    expect([first.created, again.created]).toEqual([true, false]);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/bff/api/v1/documents");
    const body = init?.body as FormData;
    expect(body.get("min_role")).toBe("manager");
    expect((body.get("file") as File).name).toBe("a.txt");
  });

  it("pages documents and chunks", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await documentsApi.list(50);
    fetchMock.mockResolvedValueOnce(Response.json({ items: [], total: 0 }));
    await documentsApi.chunks("d1", 100);

    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "/bff/api/v1/documents?limit=50&offset=50",
      "/bff/api/v1/documents/d1/chunks?limit=100&offset=100",
    ]);
  });
});

describe("levelsUpTo", () => {
  it("offers a role's own level and the ones below", () => {
    expect(levelsUpTo("employee")).toEqual(["employee"]);
    expect(levelsUpTo("manager")).toEqual(["employee", "manager"]);
    expect(levelsUpTo("administrator")).toEqual(["employee", "manager", "administrator"]);
  });
});
