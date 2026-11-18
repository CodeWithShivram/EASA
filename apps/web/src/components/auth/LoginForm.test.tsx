import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { CurrentUser } from "@/lib/api/session";

import { LoginForm } from "./LoginForm";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const USER: CurrentUser = {
  user_id: "u1",
  username: "alice",
  role: "employee",
  tenant_id: "t1",
  permissions: [],
};

async function fillAndSubmit(password = "a synthetic password") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "alice");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginForm", () => {
  it("signs in and goes to the dashboard", async () => {
    const submit = vi.fn(async () => USER);
    render(<LoginForm submit={submit} />);

    await fillAndSubmit();

    expect(submit).toHaveBeenCalledWith("alice", "a synthetic password");
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("shows the same message for every failed sign-in", async () => {
    const submit = vi.fn(async () => {
      throw new ApiError("http", "Invalid username or password.", {
        status: 401,
        code: "invalid_credentials",
      });
    });
    render(<LoginForm submit={submit} />);

    await fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("says when sign-in is unavailable", async () => {
    render(
      <LoginForm
        submit={vi.fn(async () => {
          throw new ApiError("network", "down");
        })}
      />,
    );

    await fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent("not available");
  });

  it("uses the browser's credential autocomplete and a password field", () => {
    render(<LoginForm submit={vi.fn()} />);

    expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled(); // nothing typed yet
  });
});
