import { test, expect } from "@playwright/test";

test.use({ baseURL: process.env.MERGED_UI_URL || "http://127.0.0.1:18010" });

test("shared shell keeps hash history, drafts and quality navigation", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    const data = path.endsWith("/capabilities") ? { kinds: [] }
      : path.endsWith("/model-config") ? { connections: [], tasks: [], bindings: [], providers: [] }
      : { items: [], total: 0, offset: 0, limit: 100 };
    return route.fulfill({ json: { code: 0, msg: "ok", data } });
  });
  await page.goto("/");
  for (const name of ["对话", "报告生成", "需求拆分", "数据库读写"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.locator(".workspace")).toBeVisible();
  }
  await page.getByRole("button", { name: "项目资料库", exact: true }).click();
  const child = page.locator(".quality-panel");
  await expect(page.locator("iframe")).toHaveCount(0);
  await expect(page.locator(".sidebar")).toHaveCount(1);
  await expect(child.getByRole("heading", { name: "所有项目", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "模型配置", exact: true }).click();
  await expect(page).toHaveURL(/#\/models$/);
  await expect(child.locator(".qm-breadcrumb")).toContainText("模型配置");
  await page.getByRole("button", { name: "需求拆分", exact: true }).click();
  await expect(page.locator('input[type="file"]')).toBeVisible();
  await page.getByRole("button", { name: "模型配置", exact: true }).click();
  await expect(child.locator(".qm-breadcrumb")).toContainText("模型配置");
  await page.goBack();
  await expect(page).toHaveURL(/#\/requirements$/);
  await page.goForward();
  await expect(page).toHaveURL(/#\/models$/);
  await page.reload();
  await expect(child.locator(".qm-breadcrumb")).toContainText("模型配置");
  await page.getByRole("button", { name: "对话", exact: true }).click();
  await page.getByPlaceholder("输入质量问题、追踪关系分析、覆盖分析或报告要求").fill("保留对话草稿");
  await page.getByRole("button", { name: "项目资料库", exact: true }).click();
  await child.getByLabel("工作空间").fill("draft-tenant");
  await page.getByRole("button", { name: "对话", exact: true }).click();
  await expect(page.getByPlaceholder("输入质量问题、追踪关系分析、覆盖分析或报告要求")).toHaveValue("保留对话草稿");
  await page.getByRole("button", { name: "项目资料库", exact: true }).click();
  await expect(child.getByLabel("工作空间")).toHaveValue("draft-tenant");
  expect(errors).toEqual([]);
  await page.screenshot({ path: "../artifacts/migration-validation/shared-shell.png", fullPage: true });
});
