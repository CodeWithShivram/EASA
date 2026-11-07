import Link from "next/link";

interface PlannedItem {
  label: string;
  phase: number;
}

// Placeholders only: these features do not exist yet. Rendered as
// non-interactive text, not links. Hiding UI is never an access control.
const PLANNED_ITEMS: readonly PlannedItem[] = [
  { label: "Documents", phase: 2 },
  { label: "Chat", phase: 4 },
  { label: "Admin", phase: 6 },
];

export function SideNav() {
  return (
    <nav
      aria-label="Primary"
      className="border-b border-slate-200 bg-slate-50 md:w-56 md:shrink-0 md:border-r md:border-b-0 dark:border-slate-700 dark:bg-slate-900"
    >
      <ul className="flex gap-1 overflow-x-auto p-3 md:flex-col">
        <li>
          <Link
            href="/"
            aria-current="page"
            className="block rounded-md bg-slate-200 px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 dark:bg-slate-800"
          >
            Dashboard
          </Link>
        </li>
        {PLANNED_ITEMS.map((item) => (
          <li key={item.label}>
            <span
              aria-disabled="true"
              className="block cursor-not-allowed rounded-md px-3 py-2 text-sm text-slate-500 dark:text-slate-400"
            >
              {item.label}
              <span className="ml-2 text-xs whitespace-nowrap">(Phase {item.phase})</span>
            </span>
          </li>
        ))}
      </ul>
    </nav>
  );
}
