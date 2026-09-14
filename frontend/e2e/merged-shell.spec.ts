import { test, expect } from "@playwright/test";

test.use({ baseURL: process.env.MERGED_UI_URL || "http://127.0.0.1:18010" });

test("jaleef shell retains all panels and embeds gua8gua workspace", async ({ page }) => {
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
  const child = page.frameLocator('iframe[title="项目资料库工作台"]');
  await expect(child.getByRole("heading", { name: "所有项目", exact: true })).toBeVisible();
  await child.getByRole("link", { name: "模型配置", exact: true }).first().click();
  await expect(child.locator(".qm-breadcrumb")).toContainText("模型配置");
  await page.getByRole("button", { name: "需求拆分", exact: true }).click();
  await expect(page.locator('input[type="file"]')).toBeVisible();
  await page.getByRole("button", { name: "项目资料库", exact: true }).click();
  await expect(child.locator(".qm-breadcrumb")).toContainText("模型配置");
  expect(errors).toEqual([]);
  await page.screenshot({ path: "../artifacts/merge-validation/merged-shell.png", fullPage: true });
});
