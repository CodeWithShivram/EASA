import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// Runs in the "phone" project (Pixel 7 viewport, touch).
test("every page fits a phone screen without sideways scrolling", async ({ page }) => {
  await signIn(page, "manager");

  for (const path of ["/", "/chat", "/documents", "/assistant"]) {
    await page.goto(path);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
});

test("the navigation is reachable on a phone", async ({ page }) => {
  await signIn(page, "employee");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Chat" }).tap();
  await expect(page).toHaveURL(/\/chat$/);
});
