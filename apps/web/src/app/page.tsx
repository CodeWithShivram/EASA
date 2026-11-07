import { ApiStatusCard } from "@/components/health/ApiStatusCard";

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
      <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
        Phase 1 foundation. Document search, chat and administration arrive in later phases. All
        data in this project is synthetic.
      </p>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <ApiStatusCard />
      </div>
    </div>
  );
}
