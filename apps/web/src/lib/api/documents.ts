import { z } from "zod";

import { BFF_API, bffRequest } from "./bff";

/** Documents (API section 3.4) through the backend for frontend. */

export const LEVELS = ["employee", "manager", "administrator"] as const;
export type Level = (typeof LEVELS)[number];
export const PAGE_SIZE = 50;
export const CHUNK_PAGE_SIZE = 100;
// The API's limit (EASA_MAX_UPLOAD_BYTES default); checked here only to fail early.
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const UPLOAD_TIMEOUT_MS = 120_000; // parsing and embedding run during the upload

export const documentSchema = z.object({
  id: z.string(),
  filename: z.string(),
  min_role: z.enum(LEVELS),
  media_type: z.string(),
  size_bytes: z.number().int(),
  status: z.enum(["uploaded", "processing", "processed", "failed"]),
  error_code: z.string().nullable(),
  page_count: z.number().int().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type DocumentItem = z.infer<typeof documentSchema>;

export const chunkSchema = z.object({
  chunk_index: z.number().int(),
  text: z.string(),
  page_number: z.number().int().nullable(),
  section: z.string().nullable(),
});

export type Chunk = z.infer<typeof chunkSchema>;

const chunkPageSchema = z.object({ items: z.array(chunkSchema), total: z.number().int() });

export interface UploadResult {
  document: DocumentItem;
  /** False when the same content was already uploaded (the existing document is returned). */
  created: boolean;
}

/** Levels a role may see and assign: its own and the ones below (the API enforces this). */
export function levelsUpTo(role: Level): Level[] {
  return LEVELS.slice(0, LEVELS.indexOf(role) + 1);
}

export interface DocumentsApi {
  list(offset: number): Promise<DocumentItem[]>;
  get(id: string): Promise<DocumentItem>;
  chunks(id: string, offset: number): Promise<{ items: Chunk[]; total: number }>;
  upload(file: File, level: Level): Promise<UploadResult>;
  setLevel(id: string, level: Level): Promise<DocumentItem>;
}

export const documentsApi: DocumentsApi = {
  async list(offset) {
    const schema = z.object({ items: z.array(documentSchema) });
    const path = `${BFF_API}/documents?limit=${PAGE_SIZE}&offset=${offset}`;
    return (await bffRequest(path, { schema })).data.items;
  },
  async get(id) {
    return (await bffRequest(`${BFF_API}/documents/${id}`, { schema: documentSchema })).data;
  },
  async chunks(id, offset) {
    const path = `${BFF_API}/documents/${id}/chunks?limit=${CHUNK_PAGE_SIZE}&offset=${offset}`;
    return (await bffRequest(path, { schema: chunkPageSchema })).data;
  },
  async upload(file, level) {
    const form = new FormData();
    form.append("file", file);
    form.append("min_role", level);
    const result = await bffRequest(`${BFF_API}/documents`, {
      method: "POST",
      formData: form,
      schema: documentSchema,
      timeoutMs: UPLOAD_TIMEOUT_MS,
    });
    return { document: result.data, created: result.status === 201 };
  },
  async setLevel(id, level) {
    return (
      await bffRequest(`${BFF_API}/documents/${id}`, {
        method: "PATCH",
        json: { min_role: level },
        schema: documentSchema,
      })
    ).data;
  },
};
