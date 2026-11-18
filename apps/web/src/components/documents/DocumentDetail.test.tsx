import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { Chunk, DocumentItem, DocumentsApi } from "@/lib/api/documents";

import { DocumentDetail } from "./DocumentDetail";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router, useParams: () => ({ id: "doc-1" }) }));

const DOC: DocumentItem = {
  id: "doc-1",
  filename: "handbook.pdf",
  min_role: "manager",
  media_type: "application/pdf",
  size_bytes: 5 * 1024 * 1024,
  status: "processed",
  error_code: null,
  page_count: 12,
  created_at: "2026-11-18T10:00:00Z",
  updated_at: "2026-11-18T10:00:00Z",
};

const chunk = (i: number): Chunk => ({
  chunk_index: i,
  text: `Text of part ${i + 1}.`,
  page_number: i + 1,
  section: i === 0 ? "Intro" : null,
});

function api(overrides: Partial<DocumentsApi> = {}): DocumentsApi {
  return {
    list: vi.fn(),
    get: vi.fn(async () => DOC),
    chunks: vi.fn(async (_id: string, offset: number) => ({ items: [chunk(offset)], total: 2 })),
    upload: vi.fn(),
    setLevel: vi.fn(),
    ...overrides,
  };
}

describe("DocumentDetail", () => {
  it("shows the document and its text in parts, with paging", async () => {
    const fake = api();
    render(<DocumentDetail api={fake} />);

    expect(await screen.findByRole("heading", { name: "handbook.pdf" })).toBeInTheDocument();
    expect(
      screen.getByText(/PDF · 5.0 MB · 12 pages · Visible to: Managers and administrators/),
    ).toBeInTheDocument();
    expect(screen.getByText("Part 1 · page 1 · Intro")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Text of part 2.")).toBeInTheDocument();
    expect(fake.chunks).toHaveBeenLastCalledWith("doc-1", 1);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("treats missing and hidden documents the same way", async () => {
    render(
      <DocumentDetail
        api={api({
          get: vi.fn(async () => {
            throw new ApiError("http", "Document not found.", { status: 404 });
          }),
        })}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not exist or is not available to you",
    );
  });

  it("explains failed processing instead of showing text", async () => {
    render(
      <DocumentDetail
        api={api({
          get: vi.fn(async () => ({
            ...DOC,
            status: "failed" as const,
            error_code: "encrypted_file",
          })),
        })}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("password-protected");
  });
});
