"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useSession } from "@/components/auth/SessionProvider";
import { ApiError } from "@/lib/api/client";
import {
  MAX_UPLOAD_BYTES,
  PAGE_SIZE,
  documentsApi,
  levelsUpTo,
  type DocumentItem,
  type DocumentsApi,
  type Level,
} from "@/lib/api/documents";

import { FAILURE_REASONS, LEVEL_LABELS, UPLOAD_ERRORS, fileType, formatSize } from "./labels";

function message(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const known = error.code ? UPLOAD_ERRORS[error.code] : undefined;
    if (known) return known;
    if (error.kind === "network") return "Cannot reach the server. Check your connection.";
    if (error.kind === "timeout") return "The server took too long. Try again.";
  }
  return fallback;
}

function StatusBadge({ document }: { document: DocumentItem }) {
  if (document.status === "processed") {
    return (
      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-800 dark:bg-green-950 dark:text-green-200">
        Ready
      </span>
    );
  }
  if (document.status === "failed") {
    return (
      <span className="text-xs text-red-700 dark:text-red-400">
        Failed: {FAILURE_REASONS[document.error_code ?? ""] ?? "processing failed."}
      </span>
    );
  }
  return <span className="text-xs text-slate-500">Processing…</span>;
}

export function DocumentsPage({ api = documentsApi }: { api?: DocumentsApi }) {
  const router = useRouter();
  const { state, can } = useSession();
  const role = state.status === "signed-in" ? state.user.role : null;
  const canUpload = can("documents:upload");
  const [documents, setDocuments] = useState<DocumentItem[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const fail = useCallback(
    (caught: unknown, fallback: string) => {
      if (caught instanceof ApiError && caught.status === 401) {
        router.replace("/login");
        return;
      }
      setError(message(caught, fallback));
    },
    [router],
  );

  useEffect(() => {
    let active = true;
    api.list(0).then(
      (items) => {
        if (!active) return;
        setDocuments(items);
        setHasMore(items.length === PAGE_SIZE);
      },
      (caught: unknown) => active && fail(caught, "The documents could not be loaded."),
    );
    return () => {
      active = false;
    };
  }, [api, fail, version]);

  async function loadMore() {
    try {
      const more = await api.list(documents?.length ?? 0);
      setDocuments((current) => [...(current ?? []), ...more]);
      setHasMore(more.length === PAGE_SIZE);
    } catch (caught) {
      fail(caught, "More documents could not be loaded.");
    }
  }

  async function changeLevel(document: DocumentItem, level: Level) {
    setError(null);
    setNotice(null);
    try {
      const updated = await api.setLevel(document.id, level);
      setDocuments((current) => current?.map((d) => (d.id === updated.id ? updated : d)) ?? null);
      setNotice(`${updated.filename} is now visible to: ${LEVEL_LABELS[updated.min_role]}.`);
    } catch (caught) {
      fail(caught, "The visibility could not be changed.");
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Documents of your organisation that your role may see. Synthetic data only.
        </p>
      </div>

      {canUpload && role && (
        <UploadForm
          levels={levelsUpTo(role)}
          upload={api.upload}
          onUploaded={(text) => {
            setError(null);
            setNotice(text);
            setVersion((v) => v + 1);
          }}
          onError={(caught) => {
            setNotice(null);
            fail(caught, "The upload failed.");
          }}
        />
      )}

      <div aria-live="polite">
        {notice && (
          <p role="status" className="text-sm text-green-800 dark:text-green-300">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            {error}
          </p>
        )}
      </div>

      {documents === null && !error && <p className="text-sm text-slate-500">Loading documents…</p>}
      {documents?.length === 0 && (
        <p className="text-sm text-slate-500">
          No documents yet.{canUpload ? " Upload one above." : ""}
        </p>
      )}
      {documents && documents.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <caption className="sr-only">Documents</caption>
            <thead className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Name
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Type
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Size
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Status
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Visible to
                </th>
                <th scope="col" className="py-2 font-medium">
                  Uploaded
                </th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.id} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="py-2 pr-3">
                    <Link
                      href={`/documents/${d.id}`}
                      className="font-medium text-blue-700 hover:underline dark:text-blue-400"
                    >
                      {d.filename}
                    </Link>
                  </td>
                  <td className="py-2 pr-3">{fileType(d.media_type)}</td>
                  <td className="py-2 pr-3">{formatSize(d.size_bytes)}</td>
                  <td className="py-2 pr-3">
                    <StatusBadge document={d} />
                  </td>
                  <td className="py-2 pr-3">
                    {canUpload && role ? (
                      <select
                        aria-label={`Visibility of ${d.filename}`}
                        value={d.min_role}
                        onChange={(e) => void changeLevel(d, e.target.value as Level)}
                        className="rounded-md border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900"
                      >
                        {levelsUpTo(role).map((level) => (
                          <option key={level} value={level}>
                            {LEVEL_LABELS[level]}
                          </option>
                        ))}
                      </select>
                    ) : (
                      LEVEL_LABELS[d.min_role]
                    )}
                  </td>
                  <td className="py-2">{new Date(d.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {hasMore && (
        <button
          type="button"
          onClick={() => void loadMore()}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
        >
          Load more
        </button>
      )}
    </div>
  );
}

function UploadForm({
  levels,
  upload,
  onUploaded,
  onError,
}: {
  levels: Level[];
  upload: DocumentsApi["upload"];
  onUploaded: (notice: string) => void;
  onError: (error: unknown) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [level, setLevel] = useState<Level>("employee");
  const [pending, setPending] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const tooLarge = file !== null && file.size > MAX_UPLOAD_BYTES;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || tooLarge) return;
    setPending(true);
    try {
      const { document, created } = await upload(file, level);
      onUploaded(
        created
          ? document.status === "processed"
            ? `${document.filename} was uploaded and is ready.`
            : `${document.filename} was uploaded but could not be processed.`
          : `This content was already uploaded as ${document.filename}; nothing was added.`,
      );
      setFile(null);
      setInputKey((k) => k + 1);
    } catch (caught) {
      onError(caught);
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-slate-200 p-4 dark:border-slate-700"
    >
      <h2 className="text-sm font-semibold">Upload a document</h2>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="document-file" className="block text-sm font-medium">
            File (PDF, DOCX or TXT, up to 10 MB)
          </label>
          <input
            key={inputKey}
            id="document-file"
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </div>
        <div>
          <label htmlFor="document-level" className="block text-sm font-medium">
            Visible to
          </label>
          <select
            id="document-level"
            value={level}
            onChange={(e) => setLevel(e.target.value as Level)}
            className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
          >
            {levels.map((l) => (
              <option key={l} value={l}>
                {LEVEL_LABELS[l]}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={!file || tooLarge || pending}
          className="rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? "Uploading…" : "Upload"}
        </button>
      </div>
      {tooLarge && (
        <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-400">
          The file is larger than 10 MB.
        </p>
      )}
    </form>
  );
}
