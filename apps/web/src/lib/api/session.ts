import { z } from "zod";

import { bffRequest } from "./bff";

/** The signed-in user, as returned by the API's /auth/me (role and permissions decide the UI only). */
export const currentUserSchema = z.object({
  user_id: z.string(),
  username: z.string(),
  role: z.enum(["employee", "manager", "administrator"]),
  tenant_id: z.string(),
  permissions: z.array(z.string()),
});

export type CurrentUser = z.infer<typeof currentUserSchema>;

const signInSchema = z.object({
  user: currentUserSchema,
  expires_at: z.string(),
});

export const SESSION_PATH = "/bff/session";

export async function getCurrentUser(fetchImpl?: typeof fetch): Promise<CurrentUser> {
  return (await bffRequest(SESSION_PATH, { schema: currentUserSchema, fetchImpl })).data;
}

export async function signIn(
  username: string,
  password: string,
  fetchImpl?: typeof fetch,
): Promise<CurrentUser> {
  const result = await bffRequest(SESSION_PATH, {
    method: "POST",
    json: { username, password },
    schema: signInSchema,
    fetchImpl,
  });
  return result.data.user;
}

export async function signOut(fetchImpl?: typeof fetch): Promise<void> {
  await bffRequest(SESSION_PATH, { method: "DELETE", fetchImpl });
}
