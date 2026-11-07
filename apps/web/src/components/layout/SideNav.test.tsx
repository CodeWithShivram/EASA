import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SideNav } from "./SideNav";

describe("SideNav", () => {
  it("is a labelled navigation landmark with the dashboard as the current page", () => {
    render(<SideNav />);

    const nav = screen.getByRole("navigation", { name: "Primary" });
    const dashboard = within(nav).getByRole("link", { name: "Dashboard" });
    expect(dashboard).toHaveAttribute("aria-current", "page");
    expect(dashboard).toHaveAttribute("href", "/");
  });

  it("renders planned features as disabled text, not links", () => {
    render(<SideNav />);

    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getAllByRole("link")).toHaveLength(1);
    for (const label of ["Documents", "Chat", "Admin"]) {
      expect(within(nav).getByText(label)).toHaveAttribute("aria-disabled", "true");
    }
  });
});
