import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/auth/SessionProvider";
import type { CurrentUser } from "@/lib/api/session";

import { SideNav } from "./SideNav";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/",
}));

const PERMISSIONS = {
  employee: ["knowledge:search", "documents:read", "tickets:read", "tickets:create"],
  administrator: [
    "knowledge:search",
    "documents:read",
    "documents:upload",
    "users:manage",
    "audit:read",
  ],
};

function renderAs(role: "employee" | "administrator") {
  const user: CurrentUser = {
    user_id: "u1",
    username: role,
    role,
    tenant_id: "t1",
    permissions: PERMISSIONS[role],
  };
  render(
    <SessionProvider loadUser={async () => user}>
      <SideNav />
    </SessionProvider>,
  );
  return screen.getByRole("navigation", { name: "Primary" });
}

describe("SideNav", () => {
  it("is a labelled navigation landmark with the dashboard as the current page", () => {
    const nav = renderAs("employee");

    const dashboard = within(nav).getByRole("link", { name: "Dashboard" });
    expect(dashboard).toHaveAttribute("aria-current", "page");
    expect(dashboard).toHaveAttribute("href", "/");
  });

  it("links the built features", async () => {
    const nav = renderAs("employee");

    expect(await within(nav).findByRole("link", { name: "Chat" })).toHaveAttribute("href", "/chat");
    expect(within(nav).getByRole("link", { name: "Documents" })).toHaveAttribute(
      "href",
      "/documents",
    );
    expect(within(nav).getByRole("link", { name: "Assistant" })).toHaveAttribute(
      "href",
      "/assistant",
    );
    expect(within(nav).getAllByRole("link")).toHaveLength(4);
  });

  it("shows Admin only to roles that may manage users (a convenience, not a control)", async () => {
    const employeeNav = renderAs("employee");
    await within(employeeNav).findByRole("link", { name: "Chat" });
    expect(within(employeeNav).queryByText("Admin")).toBeNull();
  });

  it("shows Admin to administrators", async () => {
    const nav = renderAs("administrator");

    // Still planned (P7-M5): disabled text, not a link.
    expect(await within(nav).findByText("Admin")).toHaveAttribute("aria-disabled", "true");
  });
});
