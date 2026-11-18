import { z } from "zod";

import { BFF_API, bffRequest } from "./bff";

/** The support assistant (API section 3.9) through the backend for frontend. */

export const MAX_MESSAGE_CHARS = 1000;
const RUN_TIMEOUT_MS = 340_000; // up to four model calls on the CPU

export const pendingActionSchema = z.object({
  id: z.string(),
  tool: z.string(),
  arguments: z.record(z.string(), z.unknown()),
  status: z.enum(["pending", "confirmed", "failed", "cancelled"]),
  result: z.record(z.string(), z.unknown()).nullable(),
  created_at: z.string(),
  expires_at: z.string(),
  decided_at: z.string().nullable(),
});

export type PendingAction = z.infer<typeof pendingActionSchema>;

export const agentResultSchema = z.object({
  status: z.enum(["answered", "confirmation_required", "failed"]),
  answer: z.string().nullable(),
  reason: z.string().nullable(),
  steps: z.array(
    z.object({ tool: z.string(), outcome: z.string(), detail: z.string().nullable() }),
  ),
  pending_action: pendingActionSchema.nullable(),
  model_id: z.string().nullable(),
});

export type AgentResult = z.infer<typeof agentResultSchema>;

export const confirmResultSchema = z.object({
  action: pendingActionSchema,
  result: z.object({
    tool: z.string(),
    outcome: z.string(),
    output: z.record(z.string(), z.unknown()).nullable(),
    message: z.string().nullable(),
  }),
});

export type ConfirmResult = z.infer<typeof confirmResultSchema>;

export interface AgentApi {
  run(message: string): Promise<AgentResult>;
  confirm(actionId: string): Promise<ConfirmResult>;
  cancel(actionId: string): Promise<PendingAction>;
}

export const agentApi: AgentApi = {
  async run(message) {
    return (
      await bffRequest(`${BFF_API}/agent`, {
        method: "POST",
        json: { message },
        schema: agentResultSchema,
        timeoutMs: RUN_TIMEOUT_MS,
      })
    ).data;
  },
  async confirm(actionId) {
    return (
      await bffRequest(`${BFF_API}/agent/actions/${actionId}/confirm`, {
        method: "POST",
        schema: confirmResultSchema,
      })
    ).data;
  },
  async cancel(actionId) {
    return (
      await bffRequest(`${BFF_API}/agent/actions/${actionId}/cancel`, {
        method: "POST",
        schema: pendingActionSchema,
      })
    ).data;
  },
};
