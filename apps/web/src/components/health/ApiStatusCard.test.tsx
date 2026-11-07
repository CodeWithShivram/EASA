import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, type ApiResult } from "@/lib/api/client";
import type { Readiness } from "@/lib/api/schemas";

import { ApiStatusCard, type ReadinessLoader } from "./ApiStatusCard";

function result(readiness: Readiness): ApiResult<Readiness> {
  return { data: readiness, status: readiness.status === "ready" ? 200 : 503, correlationId: "c1" };
}

/** Test double: a readiness loader with scripted outcomes. */
function loader(...outcomes: (ApiResult<Readiness> | Error)[]) {
  return vi.fn<ReadinessLoader>(async () => {
    const next = outcomes.shift();
    if (next === undefined) throw new Error("no scripted outcome left");
    if (next instanceof Error) throw next;
    return next;
  });
}

describe("ApiStatusCard", () => {
  it("shows loading, then ready", async () => {
    render(
      <ApiStatusCard
        loadReadiness={loader(result({ status: "ready", checks: { database: "ok" } }))}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Checking API readiness");
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("shows not ready when the database is unavailable", async () => {
    render(
      <ApiStatusCard
        loadReadiness={loader(result({ status: "not_ready", checks: { database: "unavailable" } }))}
      />,
    );

    expect(await screen.findByText("Not ready")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("shows a friendly network error", async () => {
    render(<ApiStatusCard loadReadiness={loader(new ApiError("network", "Cannot reach the API."))} />);

    expect(
      await screen.findByText("Cannot reach the API. Check that the backend is running."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Correlation ID/)).not.toBeInTheDocument();
  });

  it("shows the server message and correlation ID for an http error", async () => {
    const error = new ApiError("http", "Not Found", { status: 404, correlationId: "cid-404" });
    render(<ApiStatusCard loadReadiness={loader(error)} />);

    expect(await screen.findByText("Not Found")).toBeInTheDocument();
    expect(screen.getByText("cid-404")).toBeInTheDocument();
  });

  it("does not leak details of unexpected errors", async () => {
    render(<ApiStatusCard loadReadiness={loader(new Error("internal stack detail"))} />);

    expect(await screen.findByText("Unexpected error while checking the API.")).toBeInTheDocument();
    expect(screen.queryByText(/internal stack detail/)).not.toBeInTheDocument();
  });

  it("retries on demand", async () => {
    const load = loader(
      new ApiError("timeout", "timeout"),
      result({ status: "ready", checks: { database: "ok" } }),
    );
    render(<ApiStatusCard loadReadiness={load} />);
    expect(await screen.findByText("The API did not respond in time.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("aborts the request when unmounted", () => {
    let captured: AbortSignal | undefined;
    const load = vi.fn<ReadinessLoader>((signal) => {
      captured = signal;
      return new Promise(() => {});
    });
    const { unmount } = render(<ApiStatusCard loadReadiness={load} />);

    unmount();

    expect(captured?.aborted).toBe(true);
  });
});
