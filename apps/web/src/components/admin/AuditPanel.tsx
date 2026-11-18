"use client";

import { useEffect, useState } from "react";

import {
  AUDIT_OUTCOMES,
  AUDIT_PAGE_SIZE,
  type AdminApi,
  type AuditFilters,
  type AuditRecord,
  type User,
} from "@/lib/api/admin";

const ACTIONS: Record<string, string> = {
  "auth.login": "Sign-in",
  "auth.logout": "Sign-out",
  "user.create": "User created",
  "user.update": "User changed",
  "user.password_reset": "Password reset",
  "access.denied": "Request refused",
  "document.upload": "Document uploaded",
  "document.update": "Document visibility changed",
  "tool.execute": "Assistant tool",
  "audit.read": "Audit log read",
};

const NO_ID = "00000000-0000-0000-0000-000000000000";

/** The organisation's audit log, newest first, with filters (reads are themselves audited). */
export function AuditPanel({
  api,
  users,
  onError,
}: {
  api: AdminApi;
  users: User[];
  onError: (error: unknown, fallback: string) => void;
}) {
  const [filters, setFilters] = useState<AuditFilters>({});
  const [records, setRecords] = useState<AuditRecord[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const names = new Map(users.map((u) => [u.id, u.username]));

  useEffect(() => {
    let active = true;
    api.audit(filters, 0).then(
      (items) => {
        if (!active) return;
        setRecords(items);
        setHasMore(items.length === AUDIT_PAGE_SIZE);
      },
      (error: unknown) => active && onError(error, "The audit log could not be loaded."),
    );
    return () => {
      active = false;
    };
  }, [api, filters, onError]);

  async function loadMore() {
    try {
      const more = await api.audit(filters, records?.length ?? 0);
      setRecords((current) => [...(current ?? []), ...more]);
      setHasMore(more.length === AUDIT_PAGE_SIZE);
    } catch (error) {
      onError(error, "More records could not be loaded.");
    }
  }

  const select =
    "mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900";

  return (
    <section aria-labelledby="audit-heading" className="space-y-4">
      <h2 id="audit-heading" className="text-lg font-semibold">
        Audit log
      </h2>
      <div className="flex flex-wrap gap-3">
        <div>
          <label htmlFor="audit-action" className="block text-sm font-medium">
            Action
          </label>
          <select
            id="audit-action"
            value={filters.action ?? ""}
            onChange={(e) => setFilters({ ...filters, action: e.target.value || undefined })}
            className={select}
          >
            <option value="">All actions</option>
            {Object.entries(ACTIONS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="audit-outcome" className="block text-sm font-medium">
            Outcome
          </label>
          <select
            id="audit-outcome"
            value={filters.outcome ?? ""}
            onChange={(e) => setFilters({ ...filters, outcome: e.target.value || undefined })}
            className={select}
          >
            <option value="">All outcomes</option>
            {AUDIT_OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {o.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="audit-user" className="block text-sm font-medium">
            User
          </label>
          <select
            id="audit-user"
            value={filters.userId ?? ""}
            onChange={(e) => setFilters({ ...filters, userId: e.target.value || undefined })}
            className={select}
          >
            <option value="">All users</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </div>
      </div>
      {records === null && <p className="text-sm text-slate-500 dark:text-slate-400">Loading the audit log…</p>}
      {records?.length === 0 && (
        <p className="text-sm text-slate-500 dark:text-slate-400">No records match these filters.</p>
      )}
      {records && records.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <caption className="sr-only">Audit records, newest first</caption>
            <thead className="border-b border-slate-200 text-xs text-slate-500 dark:text-slate-400 dark:border-slate-700">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Time
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  User
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Action
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Outcome
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Target
                </th>
                <th scope="col" className="py-2 font-medium">
                  Detail
                </th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-slate-100 align-top dark:border-slate-800"
                >
                  <td className="py-2 pr-3 whitespace-nowrap">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                  <td className="py-2 pr-3">
                    {r.user_id === NO_ID
                      ? "unknown"
                      : (names.get(r.user_id) ?? r.user_id.slice(0, 8))}
                  </td>
                  <td className="py-2 pr-3">{ACTIONS[r.action] ?? r.action}</td>
                  <td className="py-2 pr-3">{r.outcome.replaceAll("_", " ")}</td>
                  <td className="py-2 pr-3 break-all">{r.target}</td>
                  <td className="py-2 break-all text-slate-600 dark:text-slate-400">{r.detail}</td>
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
    </section>
  );
}
