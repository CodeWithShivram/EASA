import type { Metadata } from "next";

import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = { title: "Sign in — EASA" };

export default function LoginPage() {
  return (
    <main id="main-content" tabIndex={-1} className="flex flex-1 items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 p-6 shadow-sm dark:border-slate-700">
        <h1 className="text-xl font-semibold tracking-tight">Sign in to EASA</h1>
        <p className="mt-1 mb-6 text-sm text-slate-600 dark:text-slate-400">
          Enterprise AI Support Agent. Synthetic data only.
        </p>
        <LoginForm />
      </div>
    </main>
  );
}
