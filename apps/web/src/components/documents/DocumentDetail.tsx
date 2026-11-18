"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  documentsApi,
  type Chunk,
  type DocumentItem,
  type DocumentsApi,
} from "@/lib/api/documents";

import { FAILURE_REASONS, LEVEL_LABELS, fileType, formatSize } from "./labels";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; document: DocumentItem; chunks: Chunk[]; total: number }
  | { kind: "error"; message: string };

/** One document and its text, in the parts used for search and citations. */
export function DocumentDetail({ api = documentsApi }: { api?: DocumentsApi }) {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [moreError, setMoreError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.get(id), api.chunks(id, 0)]).then(
      ([document, page]) =>
        active && setState({ kind: "loaded", document, chunks: page.items, total: page.total }),
      (error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          router.replace("/login");
          return;
        }
        setState({
          kind: "error",
          // Missing and hidden documents look the same, as in the API.
          message:
            error instanceof ApiError && error.status === 404
              ? "This document does not exist or is not available to you."
              : "The document could not be loaded.",
        });
      },
    );
    return () => {
      active = false;
    };
  }, [api, id, router]);

  async function loadMore() {
    if (state.kind !== "loaded") return;
    try {
      const page = await api.chunks(id, state.chunks.length);
      setState({ ...state, chunks: [...state.chunks, ...page.items], total: page.total });
    } catch {
      setMoreError("More of the text could not be loaded.");
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <Link href="/documents" className="text-sm text-blue-700 hover:underline dark:text-blue-400">
        ← All documents
      </Link>
      {state.kind === "loading" && <p className="text-sm text-slate-500 dark:text-slate-400">Loading the document…</p>}
      {state.kind === "error" && (
        <p role="alert" className="text-sm">
          {state.message}
        </p>
      )}
      {state.kind === "loaded" && (
        <>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight break-words">
              {state.document.filename}
            </h1>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {fileType(state.document.media_type)} · {formatSize(state.document.size_bytes)}
              {state.document.page_count !== null ? ` · ${state.document.page_count} pages` : ""} ·
              Visible to: {LEVEL_LABELS[state.document.min_role]}
            </p>
          </div>
          {state.document.status === "failed" ? (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              {FAILURE_REASONS[state.document.error_code ?? ""] ?? "Processing failed."} No text is
              available.
            </p>
          ) : (
            <section aria-label="Document text" className="space-y-3">
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {state.total} part{state.total === 1 ? "" : "s"}; showing {state.chunks.length}.
              </p>
              {state.chunks.map((chunk) => (
                <article
                  key={chunk.chunk_index}
                  className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-700"
                >
                  <p className="mb-1 text-xs text-slate-500 dark:text-slate-400">
                    Part {chunk.chunk_index + 1}
                    {chunk.page_number !== null ? ` · page ${chunk.page_number}` : ""}
                    {chunk.section ? ` · ${chunk.section}` : ""}
                  </p>
                  <p className="whitespace-pre-wrap">{chunk.text}</p>
                </article>
              ))}
              {state.chunks.length < state.total && (
                <button
                  type="button"
                  onClick={() => void loadMore()}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
                >
                  Load more
                </button>
              )}
              {moreError && (
                <p role="alert" className="text-sm text-red-700">
                  {moreError}
                </p>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
