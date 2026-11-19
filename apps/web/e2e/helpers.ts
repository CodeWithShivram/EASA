import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, type Page } from "@playwright/test";

import { E2E_DIR } from "./config.mjs";

export type Role = "employee" | "manager" | "administrator";

interface Credentials {
  username: string;
  password: string;
}

/** The generated credentials written by e2e/stack.mjs (never printed). */
export function credentials(role: Role): Credentials {
  const all = JSON.parse(
    readFileSync(join(process.cwd(), E2E_DIR, "credentials.json"), "utf-8"),
  ) as Record<Role, Credentials>;
  return all[role];
}

export async function signIn(page: Page, role: Role): Promise<void> {
  const { username, password } = credentials(role);
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

// Synthetic documents uploaded by the setup project (documents.setup.ts).
export const POLICY = {
  name: "e2e-leave-policy.txt",
  text:
    "Full-time employees receive 27 days of annual leave per calendar year. " +
    "Leave requests are approved by the line manager.",
};
export const PLAN = {
  name: "e2e-reorganisation-plan.txt",
  // HERON-5521 occurs only here: it must never reach an employee.
  text:
    "The reorganisation of the support teams has the codename HERON-5521. " +
    "Managers announce the reorganisation in March.",
};
