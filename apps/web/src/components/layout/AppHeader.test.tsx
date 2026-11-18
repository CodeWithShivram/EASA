import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/components/auth/SessionProvider";
import { ApiError } from "@/lib/api/client";

import { AppHeader } from "./AppHeader";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

afterEach(() => vi.unstubAllGlobals());

const USER = {
  user_id: "u1",
  username: "alice",
  role: "manager" as const,
  tenant_id: "t1",
  permissions: [],
};

describe("AppHeader", () => {
  it("shows the signed-in user and signs out through the session endpoint", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <SessionProvider loadUser={async () => USER}>
        <AppHeader />
      </SessionProvider>,
    );

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByText("(Manager)")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/bff/session",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("sends users without a valid session to the sign-in page", async () => {
    render(
      <SessionProvider
        loadUser={async () => {
          throw new ApiError("http", "Authentication required.", {
            status: 401,
          });
        }}
      >
        <AppHeader />
      </SessionProvider>,
    );

    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("explains when the session cannot be loaded", async () => {
    render(
      <SessionProvider
        loadUser={async () => {
          throw new ApiError("network", "down");
        }}
      >
        <AppHeader />
      </SessionProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your session");
  });
});
