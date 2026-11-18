import type { Metadata } from "next";
import { Suspense } from "react";

import { DocumentDetail } from "@/components/documents/DocumentDetail";

export const metadata: Metadata = { title: "Document — EASA" };

// The document ID is only known at request time (useParams), so the detail
// streams in after the prerendered shell.
export default function Document() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Loading the document…</p>}>
      <DocumentDetail />
    </Suspense>
  );
}
