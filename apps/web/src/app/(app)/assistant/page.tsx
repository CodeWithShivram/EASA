import type { Metadata } from "next";

import { AssistantPage } from "@/components/assistant/AssistantPage";

export const metadata: Metadata = { title: "Assistant — EASA" };

export default function Assistant() {
  return <AssistantPage />;
}
