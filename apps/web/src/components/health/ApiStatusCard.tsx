"use client";

import { useEffect, useState } from "react";

import { ApiError, type ApiResult } from "@/lib/api/client";
import { getReadiness } from "@/lib/api/health";
import type { Readiness } from "@/lib/api/schemas";
import { publicConfig } from "@/lib/config";

export type ReadinessLoader = (signal: AbortSignal) => Promise<ApiResult<Readiness>>;

const defaultLoader: ReadinessLoader = (signal) =>
  getReadiness(publicConfig.apiBaseUrl, { signal });

type CardState =
  | { kind: "loading" }
  | { kind: "loaded"; readiness: Readiness; correlationId: string | null }
  | { kind: "error"; message: string; correlationId: string | null };

function toErrorState(error: unknown): CardState {
  if (error instanceof ApiError) {
    const messages: Record<ApiError["kind"], string> = {
      network: "Cannot reach the API. Check that the backend is running.",
      timeout: "The API did not respond in time.",
      invalid_response: "The API returned an unexpected response.",
      http: error.message,
    };
    return { kind: "error", message: messages[error.kind], correlationId: error.correlationId };
  }
  return { kind: "error", message: "Unexpected error while checking the API.", correlationId: null };
}

export function ApiStatusCard({ loadReadiness = defaultLoader }: { loadReadiness?: ReadinessLoader }) {
  const [state, setState] = useState<CardState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    loadReadiness(controller.signal).then(
      (result) => {
        if (!controller.signal.aborted) {
          setState({ kind: "loaded", readiness: result.data, correlationId: result.correlationId });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState(toErrorState(error));
        }
      },
    );
    return () => controller.abort();
  }, [loadReadiness, attempt]);

  function retry() {
    setState({ kind: "loading" });
    setAttempt((value) => value + 1);
  }

  return (
    <section
      aria-labelledby="api-status-heading"
      className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 id="api-status-heading" className="text-base font-semibold">
          API status
        </h2>
        <button
          type="button"
          onClick={retry}
          disabled={state.kind === "loading"}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
        >
          Retry
        </button>
      </div>

      <div role="status" aria-live="polite" className="mt-4 text-sm">
        <StatusBody state={state} />
      </div>
    </section>
  );
}

function StatusBody({ state }: { state: CardState }) {
  switch (state.kind) {
    case "loading":
      return <p className="text-slate-600 dark:text-slate-400">Checking API readiness…</p>;
    case "loaded": {
      const ready = state.readiness.status === "ready";
      return (
        <>
          <p className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`inline-block size-2.5 rounded-full ${ready ? "bg-green-600" : "bg-amber-500"}`}
            />
            <span className="font-medium">{ready ? "Ready" : "Not ready"}</span>
          </p>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 text-slate-600 dark:text-slate-400">
            <dt>Database</dt>
            <dd>{state.readiness.checks.database === "ok" ? "OK" : "Unavailable"}</dd>
          </dl>
        </>
      );
    }
    case "error":
      return (
        <>
          <p className="flex items-center gap-2">
            <span aria-hidden="true" className="inline-block size-2.5 rounded-full bg-red-600" />
            <span className="font-medium">Error</span>
          </p>
          <p className="mt-2 text-slate-700 dark:text-slate-300">{state.message}</p>
          {state.correlationId && (
            <p className="mt-1 text-xs text-slate-500">
              Correlation ID: <code>{state.correlationId}</code>
            </p>
          )}
        </>
      );
  }
}
