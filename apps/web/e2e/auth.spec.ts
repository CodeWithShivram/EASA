import { expect, test } from "@playwright/test";

import { credentials } from "./helpers";

test("pages need a session and send the browser to sign in", async ({ page }) => {
  await page.goto("/chat");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in to EASA" })).toBeVisible();
});

test("a wrong password shows one message for every failure", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(credentials("employee").username);
  await page.getByLabel("Password").fill("not the right password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("signing in and out works with the keyboard alone", async ({ page, context }) => {
  const { username, password } = credentials("employee");
  await page.goto("/login");

  await page.getByLabel("Username").focus();
  await page.keyboard.type(username);
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.keyboard.type(password);
  await page.keyboard.press("Enter");

  await expect(page.getByText(`${username}`, { exact: true })).toBeVisible();
  await expect(page.getByText("(Employee)")).toBeVisible();
  // The session token stays in an HttpOnly cookie that page scripts cannot read.
  const cookie = (await context.cookies()).find((c) => c.name === "easa_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
  expect(await page.evaluate(() => document.cookie)).not.toContain("easa_session");

  const signOut = page.getByRole("button", { name: "Sign out" });
  await signOut.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/login$/);
});
