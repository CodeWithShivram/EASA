import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/layout/AppHeader";
import { SideNav } from "@/components/layout/SideNav";

import "./globals.css";

export const metadata: Metadata = {
  title: "EASA — Enterprise AI Support Agent",
  description: "Learning and portfolio project. Uses synthetic data only.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:shadow dark:focus:bg-slate-900"
        >
          Skip to main content
        </a>
        <AppHeader />
        <div className="flex flex-1 flex-col md:flex-row">
          <SideNav />
          <main id="main-content" tabIndex={-1} className="flex-1 p-4 md:p-6">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
