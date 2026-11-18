import type { ReactNode } from "react";

import { SessionProvider } from "@/components/auth/SessionProvider";
import { AppHeader } from "@/components/layout/AppHeader";
import { SideNav } from "@/components/layout/SideNav";

/** Pages for signed-in users. The session decides what the UI shows; the API decides what is allowed. */
export default function AppLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <SessionProvider>
      <AppHeader />
      <div className="flex flex-1 flex-col md:flex-row">
        <SideNav />
        <main id="main-content" tabIndex={-1} className="flex-1 p-4 md:p-6">
          {children}
        </main>
      </div>
    </SessionProvider>
  );
}
