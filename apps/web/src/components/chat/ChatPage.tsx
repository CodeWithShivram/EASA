"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import {
  MAX_QUESTION_CHARS,
  chatApi,
  type ChatApi,
  type Conversation,
  type ConversationSummary,
  type Message,
  type Source,
} from "@/lib/api/conversations";

import { AnswerText } from "./AnswerText";
import { SourcePanel, sourceKey } from "./SourcePanel";

const REASONS: Record<string, string> = {
  no_results: "No documents you can access matched this question.",
  model_declined: "The documents you can access do not answer this question.",
  no_valid_citations: "The reply could not be tied to your documents, so it is not shown.",
};

const ERROR_MESSAGES: Record<string, string> = {
  conversation_full: "This conversation has reached its limit of 50 questions. Start a new one.",
  conversation_busy: "The previous question is still being answered. Wait a moment.",
  model_unavailable: "The answer model is not available right now. Try again later.",
  answers_unavailable: "Answers are not enabled on this server.",
  model_error: "The answer model failed to respond. Try again.",
  conversation_not_found: "This conversation no longer exists.",
};

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const known = error.code ? ERROR_MESSAGES[error.code] : undefined;
    if (known) return known;
    if (error.kind === "timeout") return "The answer took too long. Try a shorter question.";
    if (error.kind === "network") return "Cannot reach the server. Check your connection.";
  }
  return "Something went wrong. Try again.";
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function ChatPage({ api = chatApi }: { api?: ChatApi }) {
  const router = useRouter();
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [asking, setAsking] = useState<{ question: string; started: number } | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  // Text the model saw, from fresh answers (stored answers keep citation metadata only).
  const [knownTexts, setKnownTexts] = useState<Record<string, string>>({});
  // Bumped to reload the conversation list.
  const [listVersion, setListVersion] = useState(0);
  const refreshList = () => setListVersion((v) => v + 1);

  const handle = useCallback(
    (error: unknown, show: (message: string) => void) => {
      if (error instanceof ApiError && error.status === 401) {
        router.replace("/login");
        return;
      }
      show(describe(error));
    },
    [router],
  );

  useEffect(() => {
    let active = true;
    api.list().then(
      (items) => {
        if (!active) return;
        setConversations(items);
        setListError(null);
      },
      (error: unknown) => active && handle(error, setListError),
    );
    return () => {
      active = false;
    };
  }, [api, handle, listVersion]);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    api.get(selected).then(
      (loaded) => {
        if (!active) return;
        setConversation(loaded);
        setThreadError(null);
      },
      (error: unknown) => active && handle(error, setThreadError),
    );
    return () => {
      active = false;
    };
  }, [api, selected, handle]);

  async function startConversation() {
    try {
      const created = await api.create();
      setSource(null);
      setSelected(created.id);
      refreshList();
    } catch (error) {
      handle(error, setListError);
    }
  }

  async function remove(id: string) {
    setConfirmDelete(null);
    try {
      await api.remove(id);
      if (selected === id) {
        setSelected(null);
        setSource(null);
      }
      refreshList();
    } catch (error) {
      handle(error, setListError);
    }
  }

  async function ask(question: string) {
    if (!selected) return;
    setAsking({ question, started: Date.now() });
    setAskError(null);
    try {
      const result = await api.ask(selected, question);
      const texts: Record<string, string> = {};
      for (const s of result.answer.sources) {
        if (s.text) texts[sourceKey(s)] = s.text;
      }
      setKnownTexts((known) => ({ ...known, ...texts }));
      setConversation(await api.get(selected));
      refreshList();
    } catch (error) {
      handle(error, setAskError);
    } finally {
      setAsking(null);
    }
  }

  return (
    <div className="mx-auto grid max-w-7xl gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_20rem]">
      {/* One h1 first, so headings stay in order for screen-reader navigation. */}
      <h1 className="sr-only">Chat</h1>
      <section aria-labelledby="conversations-heading" className="min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h2 id="conversations-heading" className="text-sm font-semibold">
            Conversations
          </h2>
          <button
            type="button"
            onClick={() => void startConversation()}
            className="rounded-md bg-blue-700 px-2.5 py-1 text-sm font-medium text-white hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            New
          </button>
        </div>
        {listError && (
          <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-400">
            {listError}
          </p>
        )}
        {conversations === null && !listError && (
          <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">Loading conversations…</p>
        )}
        {conversations?.length === 0 && (
          <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
            No conversations yet. Start one with New.
          </p>
        )}
        <ul className="mt-3 flex gap-2 overflow-x-auto lg:flex-col lg:overflow-visible">
          {conversations?.map((c) => (
            <li key={c.id} className="shrink-0">
              <div
                className={`rounded-md border px-3 py-2 text-sm ${
                  c.id === selected
                    ? "border-blue-500 bg-blue-50 dark:bg-blue-950"
                    : "border-slate-200 dark:border-slate-700"
                }`}
              >
                <button
                  type="button"
                  onClick={() => {
                    setSource(null);
                    setThreadError(null);
                    setSelected(c.id);
                  }}
                  aria-current={c.id === selected ? "true" : undefined}
                  className="block w-full text-left focus-visible:outline-2 focus-visible:outline-blue-600"
                >
                  <span className="block font-medium">{formatDate(c.created_at)}</span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {c.messages / 2} question{c.messages === 2 ? "" : "s"}
                  </span>
                </button>
                {confirmDelete === c.id ? (
                  <span className="mt-1 flex gap-2 text-xs">
                    <span>Delete permanently?</span>
                    <button
                      type="button"
                      onClick={() => void remove(c.id)}
                      className="font-semibold text-red-700 dark:text-red-400"
                    >
                      Delete
                    </button>
                    <button type="button" onClick={() => setConfirmDelete(null)}>
                      Keep
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(c.id)}
                    aria-label={`Delete conversation from ${formatDate(c.created_at)}`}
                    className="mt-1 text-xs text-slate-500 dark:text-slate-400 hover:text-red-700"
                  >
                    Delete
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Conversation" className="flex min-w-0 flex-col">
        {!selected && (
          <div className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-600 dark:border-slate-600 dark:text-slate-400">
            <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">Chat</p>
            <p className="mt-1">
              Ask questions about the documents you can access. Answers cite their sources; choose a
              citation to read the text it comes from.
            </p>
          </div>
        )}
        {threadError && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            {threadError}
          </p>
        )}
        {selected && conversation?.id === selected && (
          <>
            <ol aria-live="polite" className="space-y-3">
              {conversation.messages.length === 0 && !asking && (
                <li className="text-sm text-slate-500 dark:text-slate-400">No questions yet.</li>
              )}
              {conversation.messages.map((m) => (
                <MessageItem key={m.id} message={m} onCite={setSource} />
              ))}
              {asking && (
                <>
                  <li className="ml-auto max-w-prose rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
                    {asking.question}
                  </li>
                  <Pending started={asking.started} />
                </>
              )}
            </ol>
            {askError && (
              <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-400">
                {askError}
              </p>
            )}
            <AskForm disabled={asking !== null} onAsk={(q) => void ask(q)} />
          </>
        )}
      </section>

      <div className="min-w-0">
        {source ? (
          <SourcePanel
            source={source}
            key={sourceKey(source)}
            knownText={source.text ?? knownTexts[sourceKey(source)]}
            api={api}
            onClose={() => setSource(null)}
          />
        ) : (
          selected && (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Choose a citation such as S1 to see its source.
            </p>
          )
        )}
      </div>
    </div>
  );
}

function MessageItem({ message, onCite }: { message: Message; onCite: (s: Source) => void }) {
  if (message.role === "user") {
    return (
      <li className="ml-auto max-w-prose rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
        {message.content}
      </li>
    );
  }
  if (message.status === "answered" && message.content) {
    return (
      <li className="max-w-prose rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
        <AnswerText text={message.content} sources={message.sources} onCite={onCite} />
        {message.sources.length > 0 && (
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Sources:{" "}
            {message.sources.map((s, i) => (
              <span key={s.label}>
                {i > 0 && ", "}
                <button
                  type="button"
                  onClick={() => onCite(s)}
                  className="underline hover:text-blue-700"
                >
                  {s.label} {s.citation.filename}
                  {s.citation.page_number !== null ? `, p. ${s.citation.page_number}` : ""}
                </button>
              </span>
            ))}
          </p>
        )}
      </li>
    );
  }
  return (
    <li className="max-w-prose rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
      <p className="font-medium">No supported answer</p>
      <p>
        {REASONS[message.reason ?? ""] ??
          "The documents you can access do not answer this question."}
      </p>
    </li>
  );
}

function Pending({ started }: { started: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.round((now - started) / 1000));
  return (
    <li
      role="status"
      className="max-w-prose rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-400"
    >
      Searching your documents and writing an answer… {seconds} s. Answers usually take 10–40
      seconds on this server.
    </li>
  );
}

function AskForm({ disabled, onAsk }: { disabled: boolean; onAsk: (question: string) => void }) {
  const [question, setQuestion] = useState("");
  const trimmed = question.trim();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmed || disabled) return;
    onAsk(trimmed);
    setQuestion("");
  }

  return (
    <form onSubmit={submit} className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
      <div className="flex-1">
        <label htmlFor="question" className="block text-sm font-medium">
          Your question
        </label>
        <textarea
          id="question"
          rows={2}
          maxLength={MAX_QUESTION_CHARS}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
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
        Ask
      </button>
    </form>
  );
}
