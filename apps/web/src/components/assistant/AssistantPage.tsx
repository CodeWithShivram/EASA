"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AnswerText } from "@/components/chat/AnswerText";
import { SourcePanel, sourceKey } from "@/components/chat/SourcePanel";
import { ApiError } from "@/lib/api/client";
import {
  MAX_MESSAGE_CHARS,
  agentApi,
  type AgentApi,
  type AgentResult,
  type PendingAction,
} from "@/lib/api/agent";
import { chatApi, type ChatApi, type Source } from "@/lib/api/conversations";

const TOOL_LABELS: Record<string, string> = {
  search_knowledge_base: "Searched your documents",
  get_ticket: "Looked up a ticket",
  get_ticket_status: "Checked a ticket's status",
  create_draft_ticket: "Proposed a draft ticket",
};

const OUTCOME_LABELS: Record<string, string> = {
  succeeded: "done",
  failed: "failed",
  denied: "not allowed for your role",
  confirmation_required: "waiting for your confirmation",
  repeated: "repeat skipped",
  invalid_arguments: "invalid request",
  unknown_tool: "not available",
  timeout: "took too long",
};

const FAILURES: Record<string, string> = {
  invalid_model_output:
    "The assistant could not produce a valid reply. Try rephrasing your request.",
  too_many_pending_actions:
    "You have too many unconfirmed proposals. Confirm or cancel them, or wait until they expire.",
};

const ERRORS: Record<string, string> = {
  model_unavailable: "The assistant's model is not available right now. Try again later.",
  agent_unavailable: "The assistant is not enabled on this server.",
  model_error: "The assistant's model failed to respond. Try again.",
  action_expired: "This proposal has expired. Ask again if you still need it.",
  action_not_pending: "This proposal was already decided.",
  action_not_found: "This proposal no longer exists.",
};

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const known = error.code ? ERRORS[error.code] : undefined;
    if (known) return known;
    if (error.kind === "timeout") return "The assistant took too long. Try a shorter request.";
    if (error.kind === "network") return "Cannot reach the server. Check your connection.";
  }
  return "Something went wrong. Try again.";
}

type Decision = { kind: "open" } | { kind: "busy" } | { kind: "done"; text: string; ok: boolean };

interface Turn {
  id: number;
  message: string;
  result?: AgentResult;
  error?: string;
  decision?: Decision;
}

export function AssistantPage({
  api = agentApi,
  sourcesApi = chatApi,
}: {
  api?: AgentApi;
  sourcesApi?: Pick<ChatApi, "chunkText">;
}) {
  const router = useRouter();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState<{ started: number } | null>(null);
  // The passage shown below a reply, after its citation was chosen.
  const [shown, setShown] = useState<{ turn: number; source: Source } | null>(null);

  const update = (id: number, change: Partial<Turn>) =>
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...change } : t)));

  const handle = useCallback(
    (error: unknown): string | null => {
      if (error instanceof ApiError && error.status === 401) {
        router.replace("/login");
        return null;
      }
      return describe(error);
    },
    [router],
  );

  async function send(message: string) {
    const id = Date.now();
    setTurns((all) => [...all, { id, message }]);
    setPending({ started: Date.now() });
    try {
      const result = await api.run(message);
      update(id, {
        result,
        decision: result.status === "confirmation_required" ? { kind: "open" } : undefined,
      });
    } catch (error) {
      const text = handle(error);
      if (text) update(id, { error: text });
    } finally {
      setPending(null);
    }
  }

  async function decide(turn: Turn, action: PendingAction, confirm: boolean) {
    update(turn.id, { decision: { kind: "busy" } });
    try {
      if (confirm) {
        const { result } = await api.confirm(action.id);
        const number = result.output?.number;
        const ok = result.outcome === "succeeded";
        update(turn.id, {
          decision: {
            kind: "done",
            ok,
            text: ok
              ? `Done: draft ticket ${typeof number === "number" ? `#${number} ` : ""}created.`
              : `Not done: ${result.message ?? "the action failed."}`,
          },
        });
      } else {
        await api.cancel(action.id);
        update(turn.id, {
          decision: { kind: "done", ok: true, text: "Cancelled. Nothing was done." },
        });
      }
    } catch (error) {
      const text = handle(error);
      if (text) update(turn.id, { decision: { kind: "done", ok: false, text } });
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Support assistant</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Ask about your support tickets or company policies, or ask for a new ticket. The assistant
          acts as you, with your role&apos;s permissions, and changes nothing without your
          confirmation. Answers from your documents cite their passages, checked by the server;
          other answers are not checked against sources.
        </p>
      </div>
      {turns.length === 0 && !pending && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          For example: &quot;What is the status of my ticket 2?&quot; or &quot;Open a ticket: my
          headset does not work.&quot;
        </p>
      )}
      <ol aria-live="polite" className="space-y-4">
        {turns.map((turn) => (
          <li key={turn.id} className="space-y-2">
            <p className="ml-auto max-w-prose rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
              {turn.message}
            </p>
            {turn.error && (
              <p role="alert" className="text-sm text-red-700 dark:text-red-400">
                {turn.error}
              </p>
            )}
            {turn.result && (
              <Reply
                turn={turn}
                result={turn.result}
                onDecide={(a, c) => void decide(turn, a, c)}
                onCite={(source) => setShown({ turn: turn.id, source })}
              />
            )}
            {shown?.turn === turn.id && (
              <SourcePanel
                source={shown.source}
                key={sourceKey(shown.source)}
                knownText={shown.source.text}
                api={sourcesApi}
                onClose={() => setShown(null)}
              />
            )}
          </li>
        ))}
        {pending && <Working started={pending.started} />}
      </ol>
      <MessageForm disabled={pending !== null} onSend={(m) => void send(m)} />
    </div>
  );
}

const REPLACED: Record<string, string> = {
  unsupported_claim:
    "The assistant's reply claimed a change that did not happen, so it was replaced.",
  no_valid_citations: "No cited answer could be written from the documents the assistant found.",
  model_declined: "The documents the assistant found do not answer this.",
  no_results: "No documents available to you match this request.",
};

function Reply({
  turn,
  result,
  onDecide,
  onCite,
}: {
  turn: Turn;
  result: AgentResult;
  onDecide: (action: PendingAction, confirm: boolean) => void;
  onCite: (source: Source) => void;
}) {
  const replaced = result.reason ? REPLACED[result.reason] : undefined;
  const cited = result.sources.length;
  const steps = result.steps.map(
    (s) => `${TOOL_LABELS[s.tool] ?? s.tool} (${OUTCOME_LABELS[s.outcome] ?? s.outcome})`,
  );
  return (
    <div className="max-w-prose space-y-2 rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
      {result.status === "failed" ? (
        <p role="alert">
          {FAILURES[result.reason ?? ""] ?? "The assistant could not complete this request."}
        </p>
      ) : result.status === "confirmation_required" && result.pending_action ? (
        <Proposal
          action={result.pending_action}
          prompt={result.answer}
          decision={turn.decision}
          onDecide={onDecide}
        />
      ) : (
        <>
          <AnswerText text={result.answer ?? ""} sources={result.sources} onCite={onCite} />
          {replaced ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">{replaced}</p>
          ) : cited > 0 ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Cites {cited === 1 ? "1 passage" : `${cited} passages`} from your documents, checked
              by the server. Choose a label such as S1 to read it.
            </p>
          ) : (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              Not checked against sources. Verify important details in Chat or the documents.
            </p>
          )}
        </>
      )}
      {steps.length > 0 && (
        <p className="text-xs text-slate-500 dark:text-slate-400">Steps: {steps.join("; ")}</p>
      )}
    </div>
  );
}

function Proposal({
  action,
  prompt,
  decision,
  onDecide,
}: {
  action: PendingAction;
  prompt: string | null;
  decision?: Decision;
  onDecide: (action: PendingAction, confirm: boolean) => void;
}) {
  const expires = new Date(action.expires_at).toLocaleTimeString(undefined, { timeStyle: "short" });
  return (
    <section aria-label="Proposed action" className="space-y-2">
      <p className="font-medium">{prompt}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md bg-slate-50 p-2 text-xs dark:bg-slate-900">
        {Object.entries(action.arguments).map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="font-medium text-slate-600 dark:text-slate-400">{key}</dt>
            <dd className="break-words whitespace-pre-wrap">{String(value)}</dd>
          </div>
        ))}
      </dl>
      {decision?.kind === "done" ? (
        <p
          role="status"
          className={
            decision.ok ? "text-green-800 dark:text-green-300" : "text-red-700 dark:text-red-400"
          }
        >
          {decision.text}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={decision?.kind === "busy"}
            onClick={() => onDecide(action, true)}
            className="rounded-md bg-blue-700 px-3 py-1.5 font-medium text-white hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-60"
          >
            Confirm
          </button>
          <button
            type="button"
            disabled={decision?.kind === "busy"}
            onClick={() => onDecide(action, false)}
            className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            Cancel
          </button>
          <span className="text-xs text-slate-500 dark:text-slate-400">Expires at {expires}.</span>
        </div>
      )}
    </section>
  );
}

function Working({ started }: { started: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <li role="status" className="text-sm text-slate-600 dark:text-slate-400">
      The assistant is working… {Math.max(0, Math.round((now - started) / 1000))} s. This usually
      takes 10–60 seconds on this server.
    </li>
  );
}

function MessageForm({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (message: string) => void;
}) {
  const [message, setMessage] = useState("");
  const trimmed = message.trim();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setMessage("");
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
      <div className="flex-1">
        <label htmlFor="assistant-message" className="block text-sm font-medium">
          Your request
        </label>
        <textarea
          id="assistant-message"
          rows={2}
          maxLength={MAX_MESSAGE_CHARS}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
        />
      </div>
      <button
        type="submit"
        disabled={disabled || !trimmed}
        className="rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        Send
      </button>
    </form>
  );
}
