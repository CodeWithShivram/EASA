import { expect, test } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test("administrators see the users and the audit log", async ({ page }) => {
  await signIn(page, "administrator");
  await page.getByRole("link", { name: "Admin" }).click();

  await expect(page.getByRole("heading", { name: "Administration", level: 1 })).toBeVisible();
  const users = page.getByRole("region", { name: "Users" });
  await expect(users).toContainText(credentials("employee").username);
  await expect(users).toContainText(credentials("manager").username);
  const audit = page.getByRole("region", { name: "Audit log" });
  await expect(audit.getByRole("table")).toContainText("Sign-in");
  await expect(audit.getByRole("table")).toContainText("Document uploaded");
});

test("other roles have no administration", async ({ page }) => {
  await signIn(page, "manager");

  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Admin" }),
  ).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByText("Only administrators can manage users")).toBeVisible();
});
