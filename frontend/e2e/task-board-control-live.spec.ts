import {test, expect} from "@playwright/test";
import {mkdirSync, writeFileSync} from "node:fs";

// Explicitly scoped operator exercise: resume, interrupt, then resume the
// existing batch. This does not create a new TLR or a new analysis workspace.
const project = process.env.QUALITY_PROJECT || "real-srs-sds-20260929";
const batch = process.env.QUALITY_BATCH || "aa62daed-8d58-47d6-aa6c-4c12ffbbfd93";
const root = `/api/tasks/analysis/${batch}?tenant_id=local&project_id=${project}`;
test("真实原任务：界面恢复、中断确认与相同范围再次恢复", async ({page, request}) => {
  test.setTimeout(180000);
  const beforeResponse = await request.get(root);
  expect(beforeResponse.ok()).toBeTruthy();
  const before = await beforeResponse.json();
  expect(before.task.status).toBe("interrupted");
  await page.setViewportSize({width: 1672, height: 1000});
  await page.goto(`/#/projects/${project}/tasks`);
  const row = page.locator(".queue-card > .ant-table-wrapper .ant-table-row")
    .filter({hasText: before.task.name});
  await expect(row).toHaveCount(1);
  const posted = () => page.waitForResponse(r => r.request().method() === "POST"
    && r.url().includes(`/api/tasks/analysis/${batch}/action`));
  const firstRequest = posted();
  await row.getByRole("button", {name: /^恢\s*复$/}).click();
  expect((await firstRequest).status()).toBe(202);
  await expect.poll(async () => (await (await request.get(root)).json()).task.status,
    {timeout: 30000, intervals: [500, 1000, 2000]}).toBe("running");
  // Wait for the durable business claim, not a merely dequeued job.
  await expect.poll(async () => (await (await request.get(root)).json()).business.status,
    {timeout: 30000, intervals: [500, 1000, 2000]}).toBe("running");
  await page.getByRole("button", {name: /^刷\s*新$/}).click();
  await expect(row.getByRole("button", {name: /^中\s*断$/})).toBeVisible();
  await row.getByRole("button", {name: /^中\s*断$/}).click();
  const stopRequest = posted();
  await page.getByRole("dialog").getByRole("button", {name: "中断任务", exact: true}).click();
  expect((await stopRequest).status()).toBe(202);
  await expect.poll(async () => (await (await request.get(root)).json()).task.status,
    {timeout: 30000, intervals: [500, 1000, 2000]}).toBe("interrupted");
  const interrupted = await (await request.get(root)).json();
  await page.getByRole("button", {name: /^刷\s*新$/}).click();
  await expect(row.getByRole("button", {name: /^恢\s*复$/})).toBeVisible();
  const secondRequest = posted();
  await row.getByRole("button", {name: /^恢\s*复$/}).click();
  expect((await secondRequest).status()).toBe(202);
  await expect.poll(async () => (await (await request.get(root)).json()).business.status,
    {timeout: 30000, intervals: [500, 1000, 2000]}).toBe("running");
  const after = await (await request.get(root)).json();
  expect(after.task.business_id).toBe(before.task.business_id);
  expect(after.task.dependency_id).toBe(before.task.dependency_id);
  expect(after.business.review_ids).toEqual(before.business.review_ids);
  const selected = new Set(after.business.execution_plan.review_ids);
  expect(selected.size).toBeLessThan(after.business.review_ids.length);
  // A plain resume must not silently retry previously terminal model failures.
  for (const review of before.business.reviews) {
    if (review.execution && ["partial", "blocked"].includes(review.execution.status)
      && !review.execution.interrupted
      && !["worker_interrupted", "CancelledError", "LeaseLost"].includes(review.execution.error_code)) {
      expect(selected.has(review.review_id)).toBeFalsy();
    }
  }
  mkdirSync("../artifacts/task-management", {recursive: true});
  const compact = (value: typeof before) => ({task: value.task,
    execution_plan: value.business.execution_plan,
    reviews: value.business.reviews.map((r: {review_id: string; execution: unknown}) => ({review_id: r.review_id, execution: r.execution})),
    events: value.events});
  writeFileSync("../artifacts/task-management/interrupt-resume-live.json",
    JSON.stringify({before: compact(before), interrupted: compact(interrupted), after: compact(after)}, null, 2));
  await page.getByRole("button", {name: /^刷\s*新$/}).click();
  await page.screenshot({path: "../artifacts/task-management/task-queue-running.png", fullPage: true});
});
