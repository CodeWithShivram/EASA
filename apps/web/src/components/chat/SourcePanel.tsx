"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import type { ChatApi, Source } from "@/lib/api/conversations";

type TextState =
  { kind: "loading" } | { kind: "loaded"; text: string } | { kind: "unavailable"; message: string };

export function sourceKey(source: Source): string {
  return `${source.citation.document_id}:${source.citation.chunk_index}`;
}

/**
 * Where a cited statement comes from. A fresh answer carries the text the
 * model saw; for earlier answers the chunk is loaded again, with the same
 * visibility rules (a document restricted since then is not shown).
 */
export function SourcePanel({
  source,
  knownText,
  api,
  onClose,
}: {
  source: Source;
  knownText?: string;
  api: Pick<ChatApi, "chunkText">;
  onClose: () => void;
}) {
  const [state, setState] = useState<TextState>(
    knownText ? { kind: "loaded", text: knownText } : { kind: "loading" },
  );

  // The parent remounts this panel per source (key), so the initial state above
  // always belongs to the current source and only the async load updates it.
  useEffect(() => {
    if (knownText) return;
    let active = true;
    api.chunkText(source.citation).then(
      (text) => active && setState({ kind: "loaded", text }),
      (error: unknown) =>
        active &&
        setState({
          kind: "unavailable",
          message:
            error instanceof ApiError && error.status === 404
              ? "This source is no longer available to you."
              : "The source text could not be loaded.",
        }),
    );
    return () => {
      active = false;
    };
  }, [api, source, knownText]);

  const { citation } = source;
  const location = [
    citation.page_number !== null ? `page ${citation.page_number}` : null,
    citation.section,
    `part ${citation.chunk_index + 1}`,
  ].filter(Boolean);

  return (
    <aside
      aria-label={`Source ${source.label}`}
      className="rounded-lg border border-slate-200 p-4 text-sm dark:border-slate-700"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold">
            {source.label} · {citation.filename}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">{location.join(" · ")}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close source"
          className="rounded px-2 py-0.5 text-slate-500 dark:text-slate-400 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-blue-600 dark:hover:bg-slate-800"
        >
          ×
        </button>
      </div>
      <div className="mt-3" aria-live="polite">
        {state.kind === "loading" && <p className="text-slate-500 dark:text-slate-400">Loading the source text…</p>}
        {state.kind === "loaded" && (
          <blockquote className="border-l-4 border-slate-300 pl-3 whitespace-pre-wrap dark:border-slate-600">
            {state.text}
          </blockquote>
        )}
        {state.kind === "unavailable" && <p role="alert">{state.message}</p>}
      </div>
    </aside>
  );
}
