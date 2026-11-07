import { z } from "zod";

/**
 * Public (browser-visible) configuration. Only NEXT_PUBLIC_* values belong
 * here: they are embedded in the client bundle, so they must never be secret.
 */
const DEFAULT_API_BASE_URL = "http://localhost:8000";

const publicConfigSchema = z.object({
  apiBaseUrl: z
    .url({ protocol: /^https?$/, error: "must be an http(s) URL" })
    .refine((value) => {
      // Unparseable values are already reported by .url(); Zod 4 still runs this check.
      if (!URL.canParse(value)) return true;
      const { pathname, search, hash } = new URL(value);
      return (pathname === "/" || pathname === "") && !search && !hash;
    }, "must not contain a path, query or fragment")
    .transform((value) => value.replace(/\/+$/, "")),
});

export type PublicConfig = z.infer<typeof publicConfigSchema>;

export function parsePublicConfig(raw: { apiBaseUrl: string | undefined }): PublicConfig {
  const result = publicConfigSchema.safeParse({
    apiBaseUrl: raw.apiBaseUrl ?? DEFAULT_API_BASE_URL,
  });
  if (!result.success) {
    throw new Error(`Invalid NEXT_PUBLIC_API_BASE_URL: ${z.prettifyError(result.error)}`);
  }
  return result.data;
}

// Next.js inlines NEXT_PUBLIC_* only when referenced literally like this.
export const publicConfig: PublicConfig = parsePublicConfig({
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL,
});
