import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentApi, AgentResult, PendingAction } from "@/lib/api/agent";
import { ApiError } from "@/lib/api/client";

import { AssistantPage } from "./AssistantPage";

const { router } = vi.hoisted(() => ({ router: { replace: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const ACTION: PendingAction = {
  id: "a1",
  tool: "create_draft_ticket",
  arguments: {
    title: "Headset broken",
    description: "My headset does not work.",
    priority: "normal",
  },
  status: "pending",
  result: null,
  created_at: "2026-11-18T10:00:00Z",
  expires_at: "2026-11-18T10:10:00Z",
  decided_at: null,
};

function result(overrides: Partial<AgentResult>): AgentResult {
  return {
    status: "answered",
    answer: null,
    reason: null,
    steps: [],
    pending_action: null,
    model_id: "m",
    ...overrides,
  };
}

function fakeApi(overrides: Partial<AgentApi> = {}): AgentApi {
  return {
    run: vi.fn(async () =>
      result({
        answer: "Your ticket 2 is in progress.",
        steps: [{ tool: "get_ticket_status", outcome: "succeeded", detail: null }],
      }),
    ),
    confirm: vi.fn(async () => ({
      action: { ...ACTION, status: "confirmed" as const },
      result: {
        tool: "create_draft_ticket",
        outcome: "succeeded",
        output: { number: 8 },
        message: null,
      },
    })),
    cancel: vi.fn(async () => ({ ...ACTION, status: "cancelled" as const })),
    ...overrides,
  };
}

async function send(api: AgentApi, text = "What is the status of my ticket 2?") {
  const user = userEvent.setup();
  render(<AssistantPage api={api} />);
  await user.type(screen.getByLabelText("Your request"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

const PROPOSAL = result({
  status: "confirmation_required",
  answer:
    'Nothing has been done yet. Confirm to run create_draft_ticket with title="Headset broken", description="My headset does not work.", priority="normal", or cancel.',
  steps: [{ tool: "create_draft_ticket", outcome: "confirmation_required", detail: null }],
  pending_action: ACTION,
});

describe("AssistantPage", () => {
  it("shows answers as uncited, with the steps taken", async () => {
    await send(fakeApi());

    expect(await screen.findByText("Your ticket 2 is in progress.")).toBeInTheDocument();
    expect(screen.getByText(/Not checked against sources/)).toBeInTheDocument();
    expect(screen.getByText("Steps: Checked a ticket's status (done)")).toBeInTheDocument();
  });

  it("shows a proposal with the server's prompt and exact arguments, and confirms it", async () => {
    const api = fakeApi({ run: vi.fn(async () => PROPOSAL) });
    const user = await send(api, "Open a ticket: my headset does not work.");

    const proposal = await screen.findByRole("region", { name: "Proposed action" });
    expect(within(proposal).getByText(/Nothing has been done yet/)).toBeInTheDocument();
    expect(within(proposal).getByText("Headset broken")).toBeInTheDocument();
    expect(within(proposal).getByText("normal")).toBeInTheDocument();
    await user.click(within(proposal).getByRole("button", { name: "Confirm" }));

    expect(api.confirm).toHaveBeenCalledWith("a1");
    expect(await within(proposal).findByRole("status")).toHaveTextContent(
      "Done: draft ticket #8 created.",
    );
    expect(within(proposal).queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("cancels a proposal", async () => {
    const api = fakeApi({ run: vi.fn(async () => PROPOSAL) });
    const user = await send(api);

    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(api.cancel).toHaveBeenCalledWith("a1");
    expect(await screen.findByRole("status")).toHaveTextContent("Cancelled. Nothing was done.");
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it("explains an expired proposal", async () => {
    const api = fakeApi({
      run: vi.fn(async () => PROPOSAL),
      confirm: vi.fn(async () => {
        throw new ApiError("http", "Expired.", { status: 409, code: "action_expired" });
      }),
    });
    const user = await send(api);

    await user.click(await screen.findByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("status")).toHaveTextContent("This proposal has expired");
  });

  it("explains replaced claims, failures and model errors", async () => {
    const api = fakeApi({
      run: vi
        .fn()
        .mockResolvedValueOnce(
          result({
            answer: "I can't do that, and nothing has been changed.",
            reason: "unsupported_claim",
          }),
        )
        .mockResolvedValueOnce(result({ status: "failed", reason: "too_many_pending_actions" }))
        .mockRejectedValueOnce(
          new ApiError("http", "x", { status: 503, code: "model_unavailable" }),
        ),
    });
    const user = await send(api, "Close my ticket 1");

    expect(await screen.findByText(/claimed a change that did not happen/)).toBeInTheDocument();
    for (const text of ["Another request", "A third request"]) {
      await user.type(screen.getByLabelText("Your request"), text);
      await user.click(screen.getByRole("button", { name: "Send" }));
    }

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((a) => a.textContent)).toEqual([
      expect.stringContaining("too many unconfirmed proposals"),
      expect.stringContaining("model is not available"),
    ]);
  });

  it("shows that it is working while the model runs", async () => {
    const api = fakeApi({ run: vi.fn(() => new Promise<never>(() => undefined)) });
    await send(api);

    expect(screen.getByRole("status")).toHaveTextContent("The assistant is working");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("renders the model's text as text, never as HTML", async () => {
    const { container } = render(
      <AssistantPage
        api={fakeApi({
          run: vi.fn(async () => result({ answer: "<img src=x onerror=alert(1)>" })),
        })}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your request"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
