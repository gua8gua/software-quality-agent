import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

const project = "real-srs-sds-20260929";
const run = "55f34d70-d38d-49e3-94d1-f01fe92c00d7";
const node = "3b470435-ea9c-477d-b391-1741fd3bce73";
const images = process.env.QUALITY_SCREENSHOT_DIR || "../artifacts/page-design";
test.beforeAll(() => mkdirSync(images, {recursive: true}));

test("已有真实 TLR 的树、连线、候选表与详情联动", async ({page}) => {
  await page.setViewportSize({width: 1672, height: 1040});
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto(`/#/projects/${project}/trace/${run}/${node}`);
  await expect(page.locator(".trace-canvas-reference .react-flow__edge").first()).toBeVisible();
  await expect(page.locator(".trace-detail .node-body")).toContainText("SAF-1");
  // The restored global header precedes the project view. Bring its selected
  // hierarchy row into the page viewport, without altering tree selection.
  await page.locator(".trace-tree-reference .ant-tree-node-selected").scrollIntoViewIfNeeded();
  await expect(page.locator(".trace-tree-reference .ant-tree-node-selected")).toBeInViewport();
  await expect(page.locator(".result-metrics")).toContainText("694");
  const endpointGap = await page.evaluate(() => {
    const path = document.querySelector<SVGPathElement>(".react-flow__edge-path")!;
    const point = path.getPointAtLength(0).matrixTransform(path.getScreenCTM()!);
    const handle = document.querySelector(".react-flow__handle.source")!.getBoundingClientRect();
    return Math.abs(point.y - (handle.top + handle.height / 2));
  });
  expect(endpointGap).toBeLessThan(2);
  // Chromium full-document capture can blank composited virtual lists; inspect
  // the actual viewport, including the selected hierarchy row, instead.
  await page.setViewportSize({width: 1672, height: 1200});
  await expect(page.locator(".trace-tree-reference .ant-tree-node-selected")).toBeInViewport();
  await page.screenshot({path: `${images}/trace-desktop.png`});
  await page.locator(".trace-passage.is-target").first().click();
  await expect(page.locator(".trace-detail h2").first()).toHaveText("设计节点详情");
  await expect(page.locator(".trace-detail .node-id")).not.toHaveText(node);
  await page.getByRole("tab", {name: /候选诊断/}).click();
  await expect(page.locator(".result-table")).toContainText("RRF 分数");
  await page.getByRole("button", {name: "查看此需求的审核"}).click();
  await expect(page.locator(".result-title h1")).toHaveText("一致性分析与修改建议");
  expect(errors).toEqual([]);
});

test("真实审核检查点与逐字证据，不把阻断显示为通过", async ({page}) => {
  await page.setViewportSize({width: 1672, height: 1040});
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  const mutations: string[] = []; page.on("request", r => {if (r.url().includes("/api/") && r.method() !== "GET") mutations.push(r.url());});
  await page.goto(`/#/projects/${project}/analysis/${run}/${node}`);
  await expect(page.locator(".analysis-grid")).toBeVisible();
  await page.getByRole("combobox", {name: "选择审核记录"}).click();
  await page.locator(".ant-select-dropdown").getByText(/24f3e03c/).click();
  await expect(page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
  await expect(page.locator(".analysis-grid .ant-table-row").first()).toBeVisible();
  await expect(page.locator(".summary-run")).toContainText("执行阻断");
  await expect(page.locator(".evidence-card").first()).toBeVisible();
  const panelHeights = await page.locator(".analysis-grid > .result-card").evaluateAll(cards => cards.map(card => Math.round(card.getBoundingClientRect().height)));
  expect(new Set(panelHeights).size).toBe(1);
  await expect(page.locator(".sentence-progress")).toBeVisible();
  // This review is execution-blocked, so suggestion UI is intentionally absent.
  // Suggestions are only rendered after a validated business assessment.
  await expect(page.locator(".suggestion-section")).toHaveCount(0);
  const verticalGap = await page.evaluate(() => {
    const sentence = document.querySelector<HTMLElement>(".sentence-progress")?.getBoundingClientRect();
    const summary = document.querySelector<HTMLElement>(".analysis-summary")?.getBoundingClientRect();
    return sentence && summary ? summary.top - sentence.bottom : -1;
  });
  expect(verticalGap).toBeGreaterThanOrEqual(0);
  expect(verticalGap).toBeLessThan(32);
  await page.screenshot({path: `${images}/analysis-desktop.png`, fullPage: true});
  await page.getByRole("button", {name: "查看设计原文与位置 →"}).first().click();
  await expect(page.locator(".ant-drawer .node-body")).toBeVisible();
  await page.getByRole("button", {name: "关闭"}).click();
  await page.getByRole("button", {name: "查看错误"}).click();
  await expect(page.locator(".ant-drawer-open")).toContainText("verifier");
  expect(mutations).toEqual([]); expect(errors).toEqual([]);
});

test("窄屏布局没有页面级横向溢出", async ({page}) => {
  await page.setViewportSize({width: 760, height: 1050});
  await page.goto(`/#/projects/${project}/analysis/${run}/${node}`);
  await expect(page.locator(".analysis-grid")).toBeVisible();
  await page.getByRole("combobox", {name: "选择审核记录"}).click();
  await page.locator(".ant-select-dropdown").getByText(/24f3e03c/).click();
  await expect(page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
  await expect(page.locator(".requirement-card .node-body")).toContainText("SAF-1");
  await expect(page.locator(".suggestion-section")).toHaveCount(0);
  await page.screenshot({path: `${images}/analysis-narrow.png`, fullPage: true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
