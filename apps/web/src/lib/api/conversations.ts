import { z } from "zod";

import { BFF_API, bffRequest } from "./bff";

/** Conversations and grounded answers (API sections 3.6 and 3.7), through the backend for frontend. */

export const MAX_QUESTION_CHARS = 1000;
// The CPU model can take a few minutes; the web server allows 330 s.
const ASK_TIMEOUT_MS = 340_000;

export const citationSchema = z.object({
  document_id: z.string(),
  filename: z.string(),
  page_number: z.number().int().nullable(),
  section: z.string().nullable(),
  chunk_index: z.number().int(),
  char_start: z.number().int(),
  char_end: z.number().int(),
});

export type Citation = z.infer<typeof citationSchema>;

/** A cited source; `text` is present for a fresh answer and absent for stored ones. */
export const sourceSchema = z.object({
  label: z.string(),
  citation: citationSchema,
  text: z.string().optional(),
});

export type Source = z.infer<typeof sourceSchema>;

export const answerSchema = z.object({
  status: z.enum(["answered", "insufficient_evidence"]),
  answer: z.string().nullable(),
  reason: z.enum(["no_results", "model_declined", "no_valid_citations"]).nullable(),
  sources: z.array(sourceSchema),
  retrieved: z.number().int(),
  model_id: z.string().nullable(),
});

export const askResponseSchema = z.object({
  conversation_id: z.string(),
  turn: z.number().int(),
  answer: answerSchema,
});

export type AskResponse = z.infer<typeof askResponseSchema>;

export const messageSchema = z.object({
  id: z.string(),
  position: z.number().int(),
  role: z.enum(["user", "assistant"]),
  content: z.string().nullable(),
  status: z.string().nullable(),
  reason: z.string().nullable(),
  sources: z.array(sourceSchema),
  model_id: z.string().nullable(),
  created_at: z.string(),
});

export type Message = z.infer<typeof messageSchema>;

export const conversationSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  messages: z.array(messageSchema),
});

export type Conversation = z.infer<typeof conversationSchema>;

export const conversationSummarySchema = z.object({
  id: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  messages: z.number().int(),
});

export type ConversationSummary = z.infer<typeof conversationSummarySchema>;

const chunkListSchema = z.object({
  items: z.array(z.object({ chunk_index: z.number().int(), text: z.string() })),
});

/** Everything the chat page needs; injected so components can be tested without a server. */
export interface ChatApi {
  list(): Promise<ConversationSummary[]>;
  create(): Promise<ConversationSummary>;
  get(id: string): Promise<Conversation>;
  ask(id: string, question: string): Promise<AskResponse>;
  remove(id: string): Promise<void>;
  /** The text of one cited chunk; rejects with a 404 ApiError if the caller may no longer see it. */
  chunkText(citation: Citation): Promise<string>;
}

export const chatApi: ChatApi = {
  async list() {
    const schema = z.object({ items: z.array(conversationSummarySchema) });
    return (await bffRequest(`${BFF_API}/conversations?limit=100`, { schema })).data.items;
  },
  async create() {
    return (
      await bffRequest(`${BFF_API}/conversations`, {
        method: "POST",
        schema: conversationSummarySchema,
      })
    ).data;
  },
  async get(id) {
    return (await bffRequest(`${BFF_API}/conversations/${id}`, { schema: conversationSchema }))
      .data;
  },
  async ask(id, question) {
    return (
      await bffRequest(`${BFF_API}/conversations/${id}/messages`, {
        method: "POST",
        json: { question },
        schema: askResponseSchema,
        timeoutMs: ASK_TIMEOUT_MS,
      })
    ).data;
  },
  async remove(id) {
    await bffRequest(`${BFF_API}/conversations/${id}`, { method: "DELETE" });
  },
  async chunkText(citation) {
    const path = `${BFF_API}/documents/${citation.document_id}/chunks?offset=${citation.chunk_index}&limit=1`;
    const chunk = (await bffRequest(path, { schema: chunkListSchema })).data.items[0];
    if (!chunk || chunk.chunk_index !== citation.chunk_index) {
      throw new Error("The cited text is no longer available.");
    }
    return chunk.text;
  },
};
