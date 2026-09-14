import { test, expect } from "@playwright/test";

test.use({ baseURL: process.env.CONSISTENCY_UI_URL || "http://127.0.0.1:5173" });
test.skip(!process.env.CONSISTENCY_LOCAL_DATA, "Opt-in read-only verification of local datasets");

for (const project of ["dronology-safa", "smos"]) {
  test("local consistency selection: " + project, async ({ page }) => {
    await page.route("**/api/v1/**", route => {
      if (route.request().method() !== "GET") throw new Error("Read-only check attempted a mutation");
      return route.continue();
    });
    await page.goto("/quality.html#/projects/" + project);
    await page.getByRole("tab", { name: "一致性分析", exact: true }).click();
    await page.getByRole("button", { name: "新建一致性分析", exact: true }).click();
    await page.getByLabel("源文档层级", { exact: true }).selectOption("requirements");
    const dialog = page.getByRole("dialog");
    await expect(dialog).not.toContainText("判断基准");
    if (project === "dronology-safa") {
      await expect(dialog).toContainText("155 个代码条目缺少源码正文");
      await page.getByText("查看缺少正文的代码条目（155）", { exact: true }).click();
      await expect(dialog.locator('input[type="checkbox"]:disabled')).toHaveCount(155);
      await expect(page.getByRole("button", { name: "开始一致性分析", exact: true })).toBeDisabled();
      await page.getByLabel("分析对象", { exact: true }).selectOption("document");
      await page.getByLabel("源文档层级", { exact: true }).selectOption("requirements");
      await page.getByLabel("目标文档层级", { exact: true }).selectOption("design");
      await expect(dialog).toContainText("已选 25 份源文档");
      await expect(dialog).toContainText("已选 32 份目标");
    } else {
      await expect(dialog).toContainText("已选 67 份源文档");
      await page.getByRole("button", { name: "选择全部目标", exact: true }).click();
      await expect(dialog).toContainText("已选 100 份目标");
    }
    await expect(page.getByRole("button", { name: "开始一致性分析", exact: true })).toBeEnabled();
    await page.screenshot({ path: `../artifacts/consistency-ui/local-${project}.png`, fullPage: true });
  });
}

test("local historical analysis and batch pages remain readable", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.route("**/api/v1/**", route => {
    if (route.request().method() !== "GET") throw new Error("Read-only check attempted a mutation");
    return route.continue();
  });
  await page.goto("/quality.html#/projects/dronology-safa/tlr");
  await page.getByRole("link", { name: "查看子任务", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "批次子任务", exact: true })).toBeVisible();
  await page.screenshot({ path: "../artifacts/consistency-ui/local-batch.png", fullPage: true });
  await page.goto("/quality.html#/projects/dronology-safa/analyses");
  const history = page.getByRole("link", { name: "查看分析", exact: true });
  await expect(history.first()).toBeVisible();
  await history.first().click();
  await expect(page.getByRole("heading", { name: "上层单元", exact: false })).toBeVisible();
  await page.screenshot({ path: "../artifacts/consistency-ui/local-originals.png", fullPage: true });
  await page.getByRole("link", { name: "构建结构", exact: true }).click();
  await expect(page.getByLabel("构建结构展示层", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("local original hierarchy keeps code references and selects a single layer", async ({ page }) => {
  await page.route("**/api/v1/**", route => {
    if (route.request().method() !== "GET") throw new Error("Read-only check attempted a mutation");
    return route.continue();
  });
  await page.goto("/quality.html#/projects/dronology-safa");
  await page.getByRole("tab", { name: "结构关系", exact: true }).click();
  await expect(page.locator("main")).toContainText("本层 25 份工件");
  await page.getByLabel("结构关系数据层级", { exact: true }).selectOption("implementation");
  await expect(page.locator("main")).toContainText("本层 155 份工件");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.screenshot({ path: "../artifacts/consistency-ui/local-original-code-structure.png", fullPage: true });
});
