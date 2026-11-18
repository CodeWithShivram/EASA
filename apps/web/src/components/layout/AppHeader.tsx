"use client";

import { useSession } from "@/components/auth/SessionProvider";

const ROLE_LABELS = {
  employee: "Employee",
  manager: "Manager",
  administrator: "Administrator",
} as const;

export function AppHeader() {
  const { state, signOut } = useSession();
  return (
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 md:px-6 dark:border-slate-700">
      <p className="text-lg font-semibold tracking-tight">
        EASA <span className="font-normal text-slate-500">· Enterprise AI Support Agent</span>
      </p>
      <div className="flex items-center gap-3 text-sm">
        {state.status === "signed-in" && (
          <>
            <span>
              <span className="font-medium">{state.user.username}</span>{" "}
              <span className="text-slate-500">({ROLE_LABELS[state.user.role]})</span>
            </span>
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded-md border border-slate-300 px-2.5 py-1 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 dark:border-slate-600 dark:hover:bg-slate-800"
            >
              Sign out
            </button>
          </>
        )}
        {state.status === "error" && (
          <span role="alert" className="text-red-700 dark:text-red-400">
            {state.message}
          </span>
        )}
      </div>
    </header>
  );
}
