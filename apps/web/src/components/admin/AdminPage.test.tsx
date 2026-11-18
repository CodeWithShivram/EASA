import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/auth/SessionProvider";
import type { AdminApi, AuditRecord, User } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/client";
import type { CurrentUser } from "@/lib/api/session";

import { AdminPage } from "./AdminPage";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const ADMIN_ID = "a0000000-0000-4000-8000-000000000001";
const USERS: User[] = [
  {
    id: ADMIN_ID,
    username: "admin",
    role: "administrator",
    is_active: true,
    locked: false,
    created_at: "x",
  },
  { id: "e1", username: "erin", role: "employee", is_active: true, locked: false, created_at: "x" },
  { id: "m1", username: "mia", role: "manager", is_active: false, locked: false, created_at: "x" },
];
const RECORDS: AuditRecord[] = [
  {
    id: "r1",
    created_at: "2026-11-18T10:00:00Z",
    user_id: "e1",
    action: "access.denied",
    target: "POST /api/v1/documents",
    outcome: "denied",
    detail: "documents:upload",
    correlation_id: "c1",
  },
  {
    id: "r2",
    created_at: "2026-11-18T09:00:00Z",
    user_id: "00000000-0000-0000-0000-000000000000",
    action: "auth.login",
    target: "unknown",
    outcome: "failed",
    detail: "unknown_user",
    correlation_id: null,
  },
];

function fakeApi(overrides: Partial<AdminApi> = {}): AdminApi {
  return {
    listUsers: vi.fn(async () => USERS),
    createUser: vi.fn(async (username, _password, role) => ({
      id: "n1",
      username,
      role,
      is_active: true,
      locked: false,
      created_at: "x",
    })),
    updateUser: vi.fn(async (id, change) => ({ ...USERS.find((u) => u.id === id)!, ...change })),
    resetPassword: vi.fn(async () => undefined),
    audit: vi.fn(async () => RECORDS),
    ...overrides,
  };
}

function renderAs(role: CurrentUser["role"], api: AdminApi) {
  const permissions =
    role === "administrator" ? ["users:manage", "audit:read"] : ["knowledge:search"];
  const user: CurrentUser = {
    user_id: ADMIN_ID,
    username: role,
    role,
    tenant_id: "t",
    permissions,
  };
  render(
    <SessionProvider loadUser={async () => user}>
      <AdminPage api={api} />
    </SessionProvider>,
  );
}

describe("AdminPage", () => {
  it("explains the page to other roles and asks the API nothing", async () => {
    const api = fakeApi();
    renderAs("manager", api);

    expect(await screen.findByText(/Only administrators can manage users/)).toBeInTheDocument();
    expect(api.listUsers).not.toHaveBeenCalled();
  });

  it("lists users without self-changing controls on the administrator's own row", async () => {
    renderAs("administrator", fakeApi());

    const table = await screen.findByRole("table", { name: "Users of your organisation" });
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1]!).getByText("(you)")).toBeInTheDocument();
    expect(within(rows[1]!).queryByRole("button")).toBeNull();
    expect(within(rows[1]!).queryByRole("combobox")).toBeNull();
    expect(within(table).getByRole("combobox", { name: "Role of erin" })).toHaveValue("employee");
    expect(within(table).getByText("Disabled")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Enable mia" })).toBeInTheDocument();
  });

  it("creates users and shows the API's message for refused accounts", async () => {
    const api = fakeApi({
      createUser: vi
        .fn()
        .mockRejectedValueOnce(
          new ApiError("http", "The password must have 12-128 characters.", {
            status: 422,
            code: "invalid_account",
          }),
        )
        .mockResolvedValueOnce({
          id: "n1",
          username: "noah",
          role: "manager",
          is_active: true,
          locked: false,
          created_at: "x",
        }),
    });
    renderAs("administrator", api);
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Username"), "noah");
    await user.type(screen.getByLabelText(/Password \(12/), "short");
    await user.selectOptions(screen.getByLabelText("Role"), "manager");
    await user.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("12-128 characters");

    await user.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByRole("status")).toHaveTextContent("noah was created as Manager.");
    expect(screen.getByRole("combobox", { name: "Role of noah" })).toHaveValue("manager");
  });

  it("changes roles, disables users and resets passwords", async () => {
    const api = fakeApi();
    renderAs("administrator", api);
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Role of erin" }),
      "manager",
    );
    expect(api.updateUser).toHaveBeenCalledWith("e1", { role: "manager" });
    expect(await screen.findByRole("status")).toHaveTextContent("erin is now Manager.");

    await user.click(screen.getByRole("button", { name: "Disable erin" }));
    expect(api.updateUser).toHaveBeenLastCalledWith("e1", { is_active: false });
    expect(await screen.findByText("erin is disabled and signed out.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset password for erin" }));
    await user.type(screen.getByLabelText("New password for erin"), "a new synthetic password");
    await user.click(screen.getByRole("button", { name: "Save password" }));
    expect(api.resetPassword).toHaveBeenCalledWith("e1", "a new synthetic password");
    expect(await screen.findByText(/password was reset; their sessions ended/)).toBeInTheDocument();
  });

  it("shows the audit log with names, readable actions and filters", async () => {
    const api = fakeApi();
    renderAs("administrator", api);
    const user = userEvent.setup();

    const table = await screen.findByRole("table", { name: "Audit records, newest first" });
    expect(within(table).getByText("Request refused")).toBeInTheDocument();
    expect(within(table).getByText("erin")).toBeInTheDocument();
    // A sign-in for an unknown username belongs to no user: shown as "unknown".
    const row = within(table).getByText("unknown_user").closest("tr")!;
    expect(within(row).getAllByRole("cell")[1]).toHaveTextContent("unknown");
    await user.selectOptions(screen.getByLabelText("Outcome"), "denied");
    await user.selectOptions(screen.getByLabelText("User"), "e1");

    expect(api.audit).toHaveBeenLastCalledWith({ outcome: "denied", userId: "e1" }, 0);
  });

  it("explains taken usernames", async () => {
    const api = fakeApi({
      createUser: vi.fn(async () => {
        throw new ApiError("http", "The username is taken.", {
          status: 409,
          code: "username_taken",
        });
      }),
    });
    renderAs("administrator", api);
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Username"), "erin");
    await user.type(screen.getByLabelText(/Password \(12/), "a long synthetic password");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That username is taken.");
  });
});
