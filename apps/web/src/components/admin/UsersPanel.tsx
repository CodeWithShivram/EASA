"use client";

import { useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import { ROLES, type AdminApi, type Role, type User } from "@/lib/api/admin";

const ROLE_LABELS: Record<Role, string> = {
  employee: "Employee",
  manager: "Manager",
  administrator: "Administrator",
};

const ERRORS: Record<string, string> = {
  username_taken: "That username is taken.",
  cannot_modify_self: "You cannot change your own role or disable yourself.",
  user_not_found: "That user no longer exists.",
  forbidden: "Your role cannot manage users.",
};

/** API messages for invalid accounts (username and password rules) are written for users. */
export function describeAdminError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const known = error.code ? ERRORS[error.code] : undefined;
    if (known) return known;
    if (error.code === "invalid_account" || error.code === "validation_error") return error.message;
    if (error.kind === "network") return "Cannot reach the server. Check your connection.";
  }
  return fallback;
}

const input =
  "mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900";

export function UsersPanel({
  api,
  users,
  currentUserId,
  onChanged,
  onError,
  onNotice,
}: {
  api: AdminApi;
  users: User[];
  currentUserId: string;
  onChanged: (user: User) => void;
  onError: (error: unknown, fallback: string) => void;
  onNotice: (text: string) => void;
}) {
  const [resetFor, setResetFor] = useState<string | null>(null);

  async function update(user: User, change: { role?: Role; is_active?: boolean }, done: string) {
    try {
      onChanged(await api.updateUser(user.id, change));
      onNotice(done);
    } catch (error) {
      onError(error, "The user could not be changed.");
    }
  }

  return (
    <section aria-labelledby="users-heading" className="space-y-4">
      <h2 id="users-heading" className="text-lg font-semibold">
        Users
      </h2>
      <CreateUserForm api={api} onCreated={onChanged} onError={onError} onNotice={onNotice} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <caption className="sr-only">Users of your organisation</caption>
          <thead className="border-b border-slate-200 text-xs text-slate-500 dark:text-slate-400 dark:border-slate-700">
            <tr>
              <th scope="col" className="py-2 pr-3 font-medium">
                Username
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Role
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Status
              </th>
              <th scope="col" className="py-2 font-medium">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const self = user.id === currentUserId;
              return (
                <tr
                  key={user.id}
                  className="border-b border-slate-100 align-top dark:border-slate-800"
                >
                  <td className="py-2 pr-3 font-medium">
                    {user.username}
                    {self && <span className="ml-1 text-xs text-slate-500 dark:text-slate-400">(you)</span>}
                  </td>
                  <td className="py-2 pr-3">
                    {self ? (
                      ROLE_LABELS[user.role]
                    ) : (
                      <select
                        aria-label={`Role of ${user.username}`}
                        value={user.role}
                        onChange={(e) =>
                          void update(
                            user,
                            { role: e.target.value as Role },
                            `${user.username} is now ${ROLE_LABELS[e.target.value as Role]}.`,
                          )
                        }
                        className="rounded-md border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900"
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {ROLE_LABELS[role]}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    {!user.is_active
                      ? "Disabled"
                      : user.locked
                        ? "Locked (failed sign-ins)"
                        : "Active"}
                  </td>
                  <td className="py-2">
                    {!self && (
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            void update(
                              user,
                              { is_active: !user.is_active },
                              user.is_active
                                ? `${user.username} is disabled and signed out.`
                                : `${user.username} is enabled.`,
                            )
                          }
                          className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
                        >
                          {user.is_active ? `Disable ${user.username}` : `Enable ${user.username}`}
                        </button>
                        <button
                          type="button"
                          onClick={() => setResetFor(resetFor === user.id ? null : user.id)}
                          aria-expanded={resetFor === user.id}
                          className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
                        >
                          Reset password for {user.username}
                        </button>
                      </div>
                    )}
                    {resetFor === user.id && (
                      <ResetPasswordForm
                        user={user}
                        api={api}
                        onDone={() => {
                          setResetFor(null);
                          onNotice(`${user.username}'s password was reset; their sessions ended.`);
                        }}
                        onError={onError}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CreateUserForm({
  api,
  onCreated,
  onError,
  onNotice,
}: {
  api: AdminApi;
  onCreated: (user: User) => void;
  onError: (error: unknown, fallback: string) => void;
  onNotice: (text: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("employee");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    try {
      const user = await api.createUser(username, password, role);
      onCreated(user);
      onNotice(`${user.username} was created as ${ROLE_LABELS[user.role]}.`);
      setUsername("");
      setPassword("");
      setRole("employee");
    } catch (error) {
      onError(error, "The user could not be created.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="grid gap-3 rounded-lg border border-slate-200 p-4 sm:grid-cols-4 sm:items-end dark:border-slate-700"
    >
      <h3 className="text-sm font-semibold sm:col-span-4">Create a user</h3>
      <div>
        <label htmlFor="new-username" className="block text-sm font-medium">
          Username
        </label>
        <input
          id="new-username"
          autoComplete="off"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className={input}
        />
      </div>
      <div>
        <label htmlFor="new-password" className="block text-sm font-medium">
          Password (12+ characters)
        </label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={input}
        />
      </div>
      <div>
        <label htmlFor="new-role" className="block text-sm font-medium">
          Role
        </label>
        <select
          id="new-role"
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
          className={input}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </select>
      </div>
      <button
        type="submit"
        disabled={pending || !username || !password}
        className="rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Creating…" : "Create user"}
      </button>
    </form>
  );
}

function ResetPasswordForm({
  user,
  api,
  onDone,
  onError,
}: {
  user: User;
  api: AdminApi;
  onDone: () => void;
  onError: (error: unknown, fallback: string) => void;
}) {
  const [password, setPassword] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await api.resetPassword(user.id, password);
      setPassword("");
      onDone();
    } catch (error) {
      onError(error, "The password could not be reset.");
    }
  }

  return (
    <form onSubmit={submit} className="mt-2 flex flex-wrap items-end gap-2">
      <div>
        <label htmlFor={`reset-${user.id}`} className="block text-xs font-medium">
          New password for {user.username}
        </label>
        <input
          id={`reset-${user.id}`}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={input}
        />
      </div>
      <button
        type="submit"
        disabled={!password}
        className="rounded-md bg-blue-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60"
      >
        Save password
      </button>
    </form>
  );
}
