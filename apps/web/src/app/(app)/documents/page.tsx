import type { Metadata } from "next";

import { DocumentsPage } from "@/components/documents/DocumentsPage";

export const metadata: Metadata = { title: "Documents — EASA" };

export default function Documents() {
  return <DocumentsPage />;
}
