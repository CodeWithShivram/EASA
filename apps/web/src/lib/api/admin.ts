import { z } from "zod";

import { BFF_API, bffRequest } from "./bff";
import { LEVELS } from "./documents";

/** User administration and the audit log (API sections 3.11 and 3.12) for administrators. */

export const ROLES = LEVELS; // employee, manager, administrator
export type Role = (typeof ROLES)[number];
export const AUDIT_PAGE_SIZE = 50;
export const AUDIT_OUTCOMES = [
  "succeeded",
  "failed",
  "denied",
  "confirmation_required",
  "invalid_arguments",
  "unknown_tool",
  "timeout",
] as const;

export const userSchema = z.object({
  id: z.string(),
  username: z.string(),
  role: z.enum(ROLES),
  is_active: z.boolean(),
  locked: z.boolean(),
  created_at: z.string(),
});

export type User = z.infer<typeof userSchema>;

export const auditRecordSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  user_id: z.string(),
  action: z.string(),
  target: z.string(),
  outcome: z.string(),
  detail: z.string().nullable(),
  correlation_id: z.string().nullable(),
});

export type AuditRecord = z.infer<typeof auditRecordSchema>;

export interface AuditFilters {
  action?: string;
  outcome?: string;
  userId?: string;
}

export interface AdminApi {
  listUsers(): Promise<User[]>;
  createUser(username: string, password: string, role: Role): Promise<User>;
  updateUser(id: string, change: { role?: Role; is_active?: boolean }): Promise<User>;
  resetPassword(id: string, password: string): Promise<void>;
  audit(filters: AuditFilters, offset: number): Promise<AuditRecord[]>;
}

export const adminApi: AdminApi = {
  async listUsers() {
    const schema = z.object({ items: z.array(userSchema) });
    return (await bffRequest(`${BFF_API}/users`, { schema })).data.items;
  },
  async createUser(username, password, role) {
    return (
      await bffRequest(`${BFF_API}/users`, {
        method: "POST",
        json: { username, password, role },
        schema: userSchema,
      })
    ).data;
  },
  async updateUser(id, change) {
    return (
      await bffRequest(`${BFF_API}/users/${id}`, {
        method: "PATCH",
        json: change,
        schema: userSchema,
      })
    ).data;
  },
  async resetPassword(id, password) {
    await bffRequest(`${BFF_API}/users/${id}/password`, { method: "POST", json: { password } });
  },
  async audit(filters, offset) {
    const params = new URLSearchParams({ limit: String(AUDIT_PAGE_SIZE), offset: String(offset) });
    if (filters.action) params.set("action", filters.action);
    if (filters.outcome) params.set("outcome", filters.outcome);
    if (filters.userId) params.set("user_id", filters.userId);
    const schema = z.object({ items: z.array(auditRecordSchema) });
    return (await bffRequest(`${BFF_API}/audit?${params.toString()}`, { schema })).data.items;
  },
};
