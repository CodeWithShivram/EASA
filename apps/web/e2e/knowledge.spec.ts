import { expect, test } from "@playwright/test";

import { PLAN, POLICY, signIn } from "./helpers";

test("employees see only the documents their role may see", async ({ page }) => {
  await signIn(page, "employee");
  await page.getByRole("link", { name: "Documents" }).click();

  await expect(page.getByRole("link", { name: POLICY.name })).toBeVisible();
  await expect(page.getByText(PLAN.name)).toHaveCount(0);
  // Employees may not upload, so the form is not offered.
  await expect(page.getByRole("heading", { name: "Upload a document" })).toHaveCount(0);
});

test("chat answers cite their source and show it", async ({ page }) => {
  await signIn(page, "employee");
  await page.getByRole("link", { name: "Chat" }).click();
  await page.getByRole("button", { name: "New" }).click();
  await page
    .getByLabel("Your question")
    .fill("How many days of annual leave do employees receive?");
  await page.getByRole("button", { name: "Ask" }).click();

  const cite = page.getByRole("button", { name: `Show source S1: ${POLICY.name}` });
  await expect(cite).toBeVisible();
  await expect(page.getByText(/27 days of annual leave/).first()).toBeVisible();
  await cite.click();
  const panel = page.getByRole("complementary", { name: "Source S1" });
  await expect(panel).toContainText(POLICY.text.slice(0, 40));
});

test("restricted documents never reach an employee's answers", async ({ page }) => {
  await signIn(page, "employee");
  await page.getByRole("link", { name: "Chat" }).click();
  await page.getByRole("button", { name: "New" }).click();
  await page.getByLabel("Your question").fill("What is the codename of the reorganisation?");
  await page.getByRole("button", { name: "Ask" }).click();

  const conversation = page.getByRole("region", { name: "Conversation", exact: true });
  await expect(conversation).toContainText("codename of the reorganisation");
  // The reply has arrived once the "Searching your documents…" status is gone.
  await expect(conversation.getByText(/Searching your documents/)).toHaveCount(0);
  await expect(conversation).not.toContainText("HERON-5521");
  await expect(page.getByRole("button", { name: new RegExp(PLAN.name) })).toHaveCount(0);
});

test("managers get answers from documents for managers", async ({ page }) => {
  await signIn(page, "manager");
  await page.getByRole("link", { name: "Chat" }).click();
  await page.getByRole("button", { name: "New" }).click();
  await page.getByLabel("Your question").fill("What is the codename of the reorganisation?");
  await page.getByRole("button", { name: "Ask" }).click();

  await expect(page.getByRole("button", { name: `Show source S1: ${PLAN.name}` })).toBeVisible();
});
