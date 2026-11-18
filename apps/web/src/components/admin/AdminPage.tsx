"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/auth/SessionProvider";
import { adminApi, type AdminApi, type User } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/client";

import { AuditPanel } from "./AuditPanel";
import { UsersPanel, describeAdminError } from "./UsersPanel";

/** Administration of the caller's organisation. The API decides every request (users:manage, audit:read). */
export function AdminPage({ api = adminApi }: { api?: AdminApi }) {
  const router = useRouter();
  const { state, can } = useSession();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const allowed = can("users:manage");

  const fail = useCallback(
    (caught: unknown, fallback: string) => {
      if (caught instanceof ApiError && caught.status === 401) {
        router.replace("/login");
        return;
      }
      setNotice(null);
      setError(describeAdminError(caught, fallback));
    },
    [router],
  );

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    api.listUsers().then(
      (items) => active && setUsers(items),
      (caught: unknown) => active && fail(caught, "The users could not be loaded."),
    );
    return () => {
      active = false;
    };
  }, [api, allowed, fail]);

  if (state.status !== "signed-in") return <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>;
  if (!allowed) {
    return (
      <div className="mx-auto max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Administration</h1>
        <p className="mt-2 text-sm">Only administrators can manage users and read the audit log.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Administration</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Users and audit records of your organisation only.
        </p>
      </div>
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
      {users === null && !error && <p className="text-sm text-slate-500 dark:text-slate-400">Loading users…</p>}
      {users && (
        <UsersPanel
          api={api}
          users={users}
          currentUserId={state.user.user_id}
          onChanged={(changed) => {
            setError(null);
            setUsers((current) => {
              const list = current ?? [];
              const exists = list.some((u) => u.id === changed.id);
              const next = exists
                ? list.map((u) => (u.id === changed.id ? changed : u))
                : [...list, changed];
              return next.sort((a, b) => a.username.localeCompare(b.username));
            });
          }}
          onError={fail}
          onNotice={(text) => {
            setError(null);
            setNotice(text);
          }}
        />
      )}
      {users && can("audit:read") && <AuditPanel api={api} users={users} onError={fail} />}
    </div>
  );
}
