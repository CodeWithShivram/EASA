import type { Metadata } from "next";

import { AdminPage } from "@/components/admin/AdminPage";

export const metadata: Metadata = { title: "Administration — EASA" };

export default function Admin() {
  return <AdminPage />;
}
