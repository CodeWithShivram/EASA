import { expect, test as setup } from "@playwright/test";

import { PLAN, POLICY, signIn } from "./helpers";

// A manager uploads one document for everyone and one for managers through
// the documents page; the other tests use them.
setup("a manager uploads the synthetic documents", async ({ page }) => {
  await signIn(page, "manager");
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible();

  for (const [document, level] of [
    [POLICY, "Everyone"],
    [PLAN, "Managers and administrators"],
  ] as const) {
    await page.getByLabel(/^File/).setInputFiles({
      name: document.name,
      mimeType: "text/plain",
      buffer: Buffer.from(document.text),
    });
    await page.getByLabel("Visible to").selectOption({ label: level });
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("status")).toContainText(document.name);
    await expect(page.getByRole("link", { name: document.name })).toBeVisible();
  }
});
