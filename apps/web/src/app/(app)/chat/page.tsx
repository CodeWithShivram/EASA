import type { Metadata } from "next";

import { ChatPage } from "@/components/chat/ChatPage";

export const metadata: Metadata = { title: "Chat — EASA" };

export default function Chat() {
  return <ChatPage />;
}
