"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/components/auth/SessionProvider";

interface NavItem {
  label: string;
  href: string;
  /** Shown only to users whose role has this permission. A convenience, not a control. */
  permission?: string;
  /** Not built yet: rendered as disabled text with its milestone. */
  planned?: string;
}

const ITEMS: readonly NavItem[] = [
  { label: "Dashboard", href: "/" },
  {
    label: "Chat",
    href: "/chat",
    permission: "knowledge:search",
    planned: "P7-M2",
  },
  {
    label: "Documents",
    href: "/documents",
    permission: "documents:read",
    planned: "P7-M3",
  },
  { label: "Assistant", href: "/assistant", planned: "P7-M4" },
  {
    label: "Admin",
    href: "/admin",
    permission: "users:manage",
    planned: "P7-M5",
  },
];

export function SideNav() {
  const pathname = usePathname();
  const { can } = useSession();
  return (
    <nav
      aria-label="Primary"
      className="border-b border-slate-200 bg-slate-50 md:w-56 md:shrink-0 md:border-r md:border-b-0 dark:border-slate-700 dark:bg-slate-900"
    >
      <ul className="flex gap-1 overflow-x-auto p-3 md:flex-col">
        {ITEMS.filter((item) => !item.permission || can(item.permission)).map((item) => (
          <li key={item.href}>
            {item.planned ? (
              <span
                aria-disabled="true"
                className="block cursor-not-allowed rounded-md px-3 py-2 text-sm text-slate-500 dark:text-slate-400"
              >
                {item.label}
                <span className="ml-2 text-xs whitespace-nowrap">({item.planned})</span>
              </span>
            ) : (
              <Link
                href={item.href}
                aria-current={pathname === item.href ? "page" : undefined}
                className="block rounded-md px-3 py-2 text-sm font-medium hover:bg-slate-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 aria-[current=page]:bg-slate-200 dark:hover:bg-slate-800 dark:aria-[current=page]:bg-slate-800"
              >
                {item.label}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
