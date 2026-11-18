import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/auth/SessionProvider";
import { ApiError } from "@/lib/api/client";
import type { DocumentItem, DocumentsApi } from "@/lib/api/documents";
import type { CurrentUser } from "@/lib/api/session";

import { DocumentsPage } from "./DocumentsPage";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

function doc(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: "0f8fad5b-d9cb-469f-a165-70867728950e",
    filename: "leave_policy.txt",
    min_role: "employee",
    media_type: "text/plain",
    size_bytes: 2048,
    status: "processed",
    error_code: null,
    page_count: null,
    created_at: "2026-11-18T10:00:00Z",
    updated_at: "2026-11-18T10:00:00Z",
    ...overrides,
  };
}

const PERMISSIONS: Record<CurrentUser["role"], string[]> = {
  employee: ["documents:read"],
  manager: ["documents:read", "documents:upload"],
  administrator: ["documents:read", "documents:upload", "users:manage"],
};

function renderAs(role: CurrentUser["role"], api: DocumentsApi) {
  const user: CurrentUser = {
    user_id: "u",
    username: role,
    role,
    tenant_id: "t",
    permissions: PERMISSIONS[role],
  };
  render(
    <SessionProvider loadUser={async () => user}>
      <DocumentsPage api={api} />
    </SessionProvider>,
  );
}

function fakeApi(overrides: Partial<DocumentsApi> = {}): DocumentsApi {
  return {
    list: vi.fn(async () => [
      doc(),
      doc({
        id: "a",
        filename: "scan.pdf",
        media_type: "application/pdf",
        status: "failed",
        error_code: "no_extractable_text",
      }),
    ]),
    get: vi.fn(),
    chunks: vi.fn(),
    upload: vi.fn(async (file: File) => ({
      document: doc({ filename: file.name }),
      created: true,
    })),
    setLevel: vi.fn(async (id, level) => doc({ id, min_role: level })),
    ...overrides,
  };
}

describe("DocumentsPage", () => {
  it("lists documents with status, readable failure reasons and visibility", async () => {
    renderAs("employee", fakeApi());

    const table = await screen.findByRole("table", { name: "Documents" });
    expect(within(table).getByRole("link", { name: "leave_policy.txt" })).toHaveAttribute(
      "href",
      "/documents/0f8fad5b-d9cb-469f-a165-70867728950e",
    );
    expect(within(table).getByText("Ready")).toBeInTheDocument();
    expect(within(table).getByText(/scanned PDFs are not supported/)).toBeInTheDocument();
    expect(within(table).getAllByText("Everyone")).toHaveLength(2);
  });

  it("hides upload and level changes from employees (the API also refuses them)", async () => {
    renderAs("employee", fakeApi());

    await screen.findByRole("table");
    expect(screen.queryByText("Upload a document")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("lets managers upload with a level up to their own role", async () => {
    const api = fakeApi();
    renderAs("manager", api);
    const user = userEvent.setup();

    const level = await screen.findByLabelText("Visible to");
    expect(
      within(level)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Everyone", "Managers and administrators"]);
    await user.upload(
      screen.getByLabelText(/File \(PDF/),
      new File(["Some policy text."], "handbook.txt", { type: "text/plain" }),
    );
    await user.selectOptions(level, "manager");
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(api.upload).toHaveBeenCalledWith(
      expect.objectContaining({ name: "handbook.txt" }),
      "manager",
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "handbook.txt was uploaded and is ready.",
    );
    expect(api.list).toHaveBeenCalledTimes(2); // the list is reloaded
  });

  it("explains refused uploads and duplicates", async () => {
    const api = fakeApi({
      upload: vi
        .fn()
        .mockRejectedValueOnce(
          new ApiError("http", "x", { status: 415, code: "unsupported_file_type" }),
        )
        .mockResolvedValueOnce({ document: doc(), created: false }),
    });
    renderAs("manager", api);
    const user = userEvent.setup();
    const input = await screen.findByLabelText(/File \(PDF/);

    await user.upload(input, new File(["x"], "notes.txt"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only PDF, DOCX and TXT files");

    await user.upload(screen.getByLabelText(/File \(PDF/), new File(["x"], "copy.txt"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "already uploaded as leave_policy.txt",
    );
  });

  it("refuses files over 10 MB before sending them", async () => {
    const api = fakeApi();
    renderAs("manager", api);
    const user = userEvent.setup();
    const big = new File(["x"], "big.pdf");
    Object.defineProperty(big, "size", { value: 11 * 1024 * 1024 });

    await user.upload(await screen.findByLabelText(/File \(PDF/), big);

    expect(screen.getByRole("alert")).toHaveTextContent("larger than 10 MB");
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  });

  it("changes a document's visibility", async () => {
    const api = fakeApi();
    renderAs("administrator", api);
    const user = userEvent.setup();

    const select = await screen.findByRole("combobox", { name: "Visibility of leave_policy.txt" });
    expect(within(select).getAllByRole("option")).toHaveLength(3);
    await user.selectOptions(select, "administrator");

    expect(api.setLevel).toHaveBeenCalledWith(
      "0f8fad5b-d9cb-469f-a165-70867728950e",
      "administrator",
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Administrators only");
  });

  it("shows the empty state", async () => {
    renderAs("manager", fakeApi({ list: vi.fn(async () => []) }));

    expect(await screen.findByText("No documents yet. Upload one above.")).toBeInTheDocument();
  });
});
