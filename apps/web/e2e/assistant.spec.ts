import { expect, test } from "@playwright/test";

import { POLICY, signIn } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signIn(page, "employee");
  await page.getByRole("link", { name: "Assistant" }).click();
});

async function send(page: import("@playwright/test").Page, text: string) {
  await page.getByLabel("Your request").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test("a proposed ticket is created only after Confirm", async ({ page }) => {
  await send(page, "Open a ticket: my headset does not work.");

  const proposal = page.getByRole("region", { name: "Proposed action" });
  await expect(proposal).toContainText("Nothing has been done yet");
  await expect(proposal).toContainText("my headset does not work.");
  await proposal.getByRole("button", { name: "Confirm" }).click();

  await expect(proposal.getByRole("status")).toContainText(/Done: draft ticket #\d+ created\./);
  await expect(proposal.getByRole("button", { name: "Confirm" })).toHaveCount(0);
});

test("a cancelled proposal does nothing", async ({ page }) => {
  await send(page, "Open a ticket: the projector flickers.");

  const proposal = page.getByRole("region", { name: "Proposed action" });
  await proposal.getByRole("button", { name: "Cancel" }).click();

  await expect(proposal.getByRole("status")).toHaveText("Cancelled. Nothing was done.");
});

test("ticket questions are answered from the user's tickets", async ({ page }) => {
  await send(page, "What is the status of my ticket 2?");

  await expect(page.getByText("The ticket's status is in progress.")).toBeVisible();
  await expect(page.getByText("Steps: Checked a ticket's status (done)")).toBeVisible();
});

test("document questions get a cited answer", async ({ page }) => {
  await send(page, "How many days of annual leave do employees receive?");

  await expect(page.getByText(/Cites 1 passage from your documents/)).toBeVisible();
  await page.getByRole("button", { name: `Show source S1: ${POLICY.name}` }).click();
  await expect(page.getByRole("complementary", { name: "Source S1" })).toContainText(
    "27 days of annual leave",
  );
});
