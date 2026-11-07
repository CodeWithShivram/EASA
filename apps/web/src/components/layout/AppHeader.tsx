export function AppHeader() {
  return (
    <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 md:px-6 dark:border-slate-700">
      <p className="text-lg font-semibold tracking-tight">
        EASA <span className="font-normal text-slate-500">· Enterprise AI Support Agent</span>
      </p>
      <span className="rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
        Development build
      </span>
    </header>
  );
}
