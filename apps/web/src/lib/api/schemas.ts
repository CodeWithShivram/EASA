import { z } from "zod";

/** Runtime schemas for API responses. Mirrors apps/api/app/schemas and core/errors.py. */

export const readinessSchema = z.object({
  status: z.enum(["ready", "not_ready"]),
  checks: z.object({
    database: z.enum(["ok", "unavailable"]),
  }),
});

export type Readiness = z.infer<typeof readinessSchema>;

export const apiErrorBodySchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    correlation_id: z.string().nullable(),
    details: z
      .array(
        z.object({
          location: z.array(z.union([z.string(), z.number()])),
          message: z.string(),
          type: z.string(),
        }),
      )
      .optional(),
  }),
});

export type ApiErrorBody = z.infer<typeof apiErrorBodySchema>;
