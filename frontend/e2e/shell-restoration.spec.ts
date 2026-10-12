import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

const project = "real-srs-sds-20260929";
const images = "../artifacts/shell-restoration/screenshots";
test.beforeAll(() => mkdirSync(images, {recursive: true}));

test("全局导航、模型配置、项目、对话及同伴页面均保留", async ({page}) => {
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && request.method() !== "GET") mutations.push(request.url()); });
  await page.goto("/#/projects");
  await expect(page.locator(".project-card")).toContainText(project);
  await expect(page.locator(".sidebar .nav-item")).toHaveCount(5);
  await page.screenshot({path: `${images}/projects.png`, fullPage: true});
  await page.getByRole("button", {name: "模型配置", exact: true}).click();
  await expect(page.getByRole("heading", {name: /TLR 向量编码/})).toBeVisible();
  await page.locator(".qm-task-group").filter({hasText: "面向用户的项目质量问答"}).locator("summary").click();
  await expect(page.getByRole("heading", {name: /项目对话/})).toBeVisible();
  await page.screenshot({path: `${images}/models.png`, fullPage: true});
  await page.getByRole("button", {name: "对话", exact: true}).click();
  await expect(page.getByRole("heading", {name: "项目质量问答"})).toBeVisible();
  await expect(page.locator(".inline-controls select").last()).toHaveValue(project);
  await page.screenshot({path: `${images}/chat.png`, fullPage: true});
  await page.locator(".sidebar").getByRole("button", {name: "报告生成", exact: true}).click();
  await expect(page.locator(".workspace-grid")).toBeVisible();
  await page.screenshot({path: `${images}/report.png`, fullPage: true});
  await page.locator(".sidebar").getByRole("button", {name: "需求拆分", exact: true}).click();
  await expect(page.locator('input[type="file"]')).toBeAttached();
  await expect(page.locator('input[value="test_codes/LeKV"]')).toBeAttached();
  await page.screenshot({path: `${images}/requirements.png`, fullPage: true});
  expect(errors).toEqual([]);
  expect(mutations).toEqual([]);
});

test("具体项目保留目录、文本代码及原始 DOCX 详情", async ({page, request}) => {
  const artifacts = await (await request.get(`/api/v1/projects/${project}/artifacts?tenant_id=local`)).json();
  const docx = artifacts.find((item: {media_type: string}) => item.media_type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
  expect(docx).toBeTruthy();
  const calls: string[] = [], errors: string[] = [];
  page.on("request", request => calls.push(request.url()));
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`/#/projects/${project}`);
  await expect(page.locator(".project-library")).toBeVisible();
  const originalSidebar = await page.locator(".sidebar").evaluate(element => ({width: element.getBoundingClientRect().width, shadow: getComputedStyle(element).boxShadow, radius: getComputedStyle(element).borderRadius}));
  await page.goto(`/#/projects/${project}/files/${docx.id}`);
  await expect(page.getByRole("navigation", {name: "数据类型"})).toBeVisible();
  await expect(page.getByRole("navigation", {name: "当前目录"})).toBeVisible();
  await expect(page.getByText(/docx-preview 原始文件预览 · 已渲染/)).toBeVisible({timeout: 45000});
  const frame = page.frameLocator('[data-renderer="docx-preview"]');
  expect(await frame.locator("section.docx").count()).toBeGreaterThan(0);
  expect(await frame.locator("table").count()).toBeGreaterThan(0);
  expect(calls.some(url => url.includes(`/artifacts/${docx.id}/original`))).toBe(true);
  expect(calls.some(url => /content-tree|content-json|\/information\/nodes/.test(url))).toBe(false);
  await page.screenshot({path: `${images}/artifact.png`, fullPage: true});
  expect(await page.locator(".sidebar").evaluate(element => ({width: element.getBoundingClientRect().width, shadow: getComputedStyle(element).boxShadow, radius: getComputedStyle(element).borderRadius}))).toEqual(originalSidebar);
  expect(errors).toEqual([]);
});
