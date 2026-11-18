import { z } from "zod";

/**
 * Server-side configuration of the web app's backend for frontend (Phase 7,
 * ADR-034). Read only in route handlers and the proxy, never in the browser:
 * the browser talks to this app (`/bff/...`), and this app talks to the API.
 */
const DEFAULT_API_URL = "http://localhost:8000";

const serverConfigSchema = z.object({
  apiUrl: z
    .url({ protocol: /^https?$/, error: "must be an http(s) URL" })
    .refine((value) => {
      // Unparseable values are already reported by .url(); Zod 4 still runs this check.
      if (!URL.canParse(value)) return true;
      const { pathname, search, hash, username, password } = new URL(value);
      return (pathname === "/" || pathname === "") && !search && !hash && !username && !password;
    }, "must not contain a path, query, fragment or credentials")
    .transform((value) => value.replace(/\/+$/, "")),
});

export type ServerConfig = z.infer<typeof serverConfigSchema>;

export function parseServerConfig(raw: { apiUrl: string | undefined }): ServerConfig {
  const result = serverConfigSchema.safeParse({
    apiUrl: raw.apiUrl || DEFAULT_API_URL,
  });
  if (!result.success) {
    throw new Error(`Invalid EASA_API_URL: ${z.prettifyError(result.error)}`);
  }
  return result.data;
}

/** The current configuration (read at request time, so tests and deployments can set it). */
export function serverConfig(): ServerConfig {
  return parseServerConfig({ apiUrl: process.env.EASA_API_URL });
}
