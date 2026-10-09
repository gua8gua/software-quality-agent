import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

const project = "real-srs-sds-20260929";
const images = "../artifacts/project-library";
test.beforeAll(() => mkdirSync(images, {recursive: true}));

test("真实文件目录、分类筛选、详情和两个分析入口", async ({page, request}) => {
  await page.setViewportSize({width: 1672, height: 1000});
  const files = await (await request.get(`/api/v1/projects/${project}/artifacts?tenant_id=local`)).json();
  const folders = await (await request.get(`/api/v1/projects/${project}/folders?tenant_id=local`)).json();
  const document = files.find((file: {engineering_role: string}) => file.engineering_role === "design");
  expect(document.size_bytes).toBeGreaterThan(0);
  expect(document.uploaded_at).toBeTruthy();
  expect((await (await request.get(document.original_file_url)).body()).byteLength).toBe(document.size_bytes);
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && request.method() !== "GET") mutations.push(request.url()); });
  await page.goto(`/#/projects/${project}`);
  await expect(page.getByRole("heading", {name: "项目资料库", exact: true})).toBeVisible();
  await expect(page.locator(".library-stat").first().locator("strong")).toHaveText(String(files.filter((file: {modality: string}) => file.modality === "text").length));
  await expect(page.locator(".library-table .ant-table-row")).toHaveCount(files.length + folders.filter((folder: {parent_id: string | null}) => folder.parent_id === null).length);
  await page.locator(".library-filename").filter({hasText: document.filename}).click();
  await expect(page.locator(".library-file-detail h3")).toHaveText(document.filename);
  await expect(page.locator(".library-file-detail .ant-btn-primary")).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(page.locator(".library-selected-row td").first()).toHaveCSS("background-color", "rgb(237, 243, 255)");
  await expect(page.locator(".library-file-detail")).toContainText("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
  await page.screenshot({path: `${images}/library-desktop.png`, fullPage: true});
  await page.getByRole("navigation", {name: "文本子类"}).getByRole("button", {name: /需求说明文档/}).click();
  await expect(page.locator(".library-table .ant-table-row").filter({has: page.locator(".ant-tag")})).toHaveCount(files.filter((file: {engineering_role: string}) => file.engineering_role === "requirement").length);
  await page.getByRole("navigation", {name: "数据类型"}).getByRole("button", {name: "代码", exact: true}).click();
  await expect(page.getByRole("navigation", {name: "文本子类"})).toHaveCount(0);
  await page.getByRole("navigation", {name: "数据类型"}).getByRole("button", {name: "文本", exact: true}).click();
  await page.getByRole("textbox", {name: "搜索文件名"}).fill(document.filename);
  await expect(page.locator(".library-table .ant-table-row")).toHaveCount(1);
  await page.getByRole("textbox", {name: "搜索文件名"}).fill("");
  await page.getByRole("navigation", {name: "项目分析入口"}).getByRole("button", {name: "追溯结果"}).click();
  await expect(page.locator(".result-title h1")).toHaveText("TLR 追溯链接恢复结果");
  await page.getByRole("navigation", {name: "项目子页面"}).getByRole("button", {name: "项目数据"}).click();
  await page.getByRole("navigation", {name: "项目分析入口"}).getByRole("button", {name: "一致性分析"}).click();
  await expect(page.locator(".result-title h1")).toHaveText("一致性分析与修改建议");
  expect(errors).toEqual([]);
  expect(mutations).toEqual([]);
});

test("目录层级与窄屏文件表格只在自身容器内滚动", async ({page}) => {
  await page.setViewportSize({width: 760, height: 1050});
  // A read-only UI fixture exercises hierarchy without adding test folders to
  // the real project. Real document rows remain unmodified.
  await page.route(`**/api/v1/projects/${project}/folders?*`, route => route.fulfill({json: [
    {id: "docs", project_id: project, parent_id: null, name: "docs"},
    {id: "requirements", project_id: project, parent_id: "docs", name: "requirements"},
  ]}));
  await page.goto(`/#/projects/${project}`);
  await page.locator(".library-filename").filter({hasText: "docs"}).click();
  await expect(page.getByRole("navigation", {name: "当前目录"})).toContainText("docs");
  await page.locator(".library-filename").filter({hasText: "requirements"}).click();
  await expect(page.getByRole("navigation", {name: "当前目录"})).toContainText("requirements");
  await page.getByRole("navigation", {name: "当前目录"}).getByRole("button", {name: "根目录"}).click();
  await expect(page.locator(".library-table .ant-table-row")).toHaveCount(3);
  await page.locator(".library-filename").filter({hasText: ".docx"}).first().click();
  await page.screenshot({path: `${images}/library-narrow.png`, fullPage: true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
