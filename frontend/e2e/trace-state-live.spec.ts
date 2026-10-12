import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const project = process.env.QUALITY_PROJECT || "real-srs-sds-20260929";
const run = process.env.QUALITY_TLR_RUN || "55f34d70-d38d-49e3-94d1-f01fe92c00d7";
const images = process.env.QUALITY_SCREENSHOT_DIR || "../artifacts/page-design/20261003";
test.beforeAll(() => mkdirSync(images, {recursive: true}));

async function treeState(page: Page, side?: "source" | "target") {
  return page.locator(`.trace-hierarchy-row${side ? `.${side}` : ""}`).evaluateAll(rows => rows.map(row => ({
    id: row.getAttribute("data-trace-node-id"),
    side: row.classList.contains("source") ? "source" : "target",
    level: row.getAttribute("data-trace-level"),
    expanded: row.querySelector("button")?.getAttribute("aria-expanded") || null,
  })));
}

async function expand(page: Page, side: "需求" | "设计", level: number) {
  await page.getByRole("combobox", {name: `${side}侧展开层级`}).click();
  await page.locator(".ant-select-dropdown:visible").getByText(level === 1 ? "仅文档（第 1 层）" : `展开至第 ${level} 层`, {exact: true}).click();
  await expect(page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
}

test("真实双侧层级：点击与刷新保留折叠，层级下拉和快捷键独立生效", async ({page}) => {
  await page.setViewportSize({width: 1840, height: 1120});
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {if (request.url().includes("/api/") && request.method() !== "GET") mutations.push(request.url());});
  await page.goto(`/#/projects/${project}/trace/${run}`);
  await expect(page.locator(".trace-hierarchy-row.source").first()).toBeVisible();
  await expect(page.locator(".trace-hierarchy-row.target").first()).toBeVisible();

  // Change each side without touching the other. Depth uses the actual document
  // root, not chapter numbering, and includes canonical structural groups.
  const initialTarget = await treeState(page, "target");
  await expand(page, "需求", 5);
  expect(await treeState(page, "target")).toEqual(initialTarget);
  const sourceAtFive = await treeState(page, "source");
  expect(Math.max(...sourceAtFive.map(row => Number(row.level)))).toBe(5);
  await expand(page, "设计", 5);
  expect(await treeState(page, "source")).toEqual(sourceAtFive);

  // Collapsing a branch is a user state change. Selecting either side's leaves,
  // including a different source (which fetches candidates), must not reset it.
  const branch = page.locator('.trace-hierarchy-row.source.branch[data-trace-level="3"] button[aria-expanded="true"]').first();
  await branch.click();
  const collapsed = await treeState(page);
  await page.locator(".trace-hierarchy-row.source.leaf .trace-hierarchy-title").first().click();
  await expect(page.locator(".trace-hierarchy-row.source.selected")).toHaveCount(1);
  expect(await treeState(page)).toEqual(collapsed);
  await page.locator(".trace-hierarchy-row.target.leaf .trace-hierarchy-title").first().click();
  await expect(page.locator(".trace-detail h2").first()).toHaveText("设计节点详情");
  expect(await treeState(page)).toEqual(collapsed);
  await page.getByRole("button", {name: "刷新", exact: true}).click();
  await expect(page.locator(".trace-hierarchy-row.target.selected")).toHaveCount(1);
  expect(await treeState(page)).toEqual(collapsed);

  // Keyboard shortcuts are scoped to the focused side, never global hotkeys.
  await page.getByRole("group", {name: "需求侧层级快捷键"}).focus();
  const targetBeforeKey = await treeState(page, "target");
  await page.keyboard.press("Alt+2");
  expect(Math.max(...(await treeState(page, "source")).map(row => Number(row.level)))).toBe(2);
  expect(await treeState(page, "target")).toEqual(targetBeforeKey);
  await page.getByRole("group", {name: "设计侧层级快捷键"}).focus();
  await page.keyboard.press("Alt+3");
  expect(Math.max(...(await treeState(page, "target")).map(row => Number(row.level)))).toBe(3);
  expect(Math.max(...(await treeState(page, "source")).map(row => Number(row.level)))).toBe(2);

  // Selecting a section must also stay selected rather than jump to the first
  // TLR leaf. Section inspection is not itself a leaf-review launch action.
  const section = page.locator('.trace-hierarchy-row.source[data-trace-level="2"]').first();
  const sectionId = await section.getAttribute("data-trace-node-id");
  const beforeSection = await treeState(page);
  await section.locator(".trace-hierarchy-title").click();
  await expect(page.locator(".trace-hierarchy-row.source.selected")).toHaveAttribute("data-trace-node-id", sectionId!);
  expect(await treeState(page)).toEqual(beforeSection);
  await expect(page.getByRole("button", {name: "查看此需求的审核"})).toBeDisabled();

  // With only document roots visible, formal links still project onto the
  // nearest visible ancestors; no link data is removed by a collapse.
  const totalLinks = await page.locator(".trace-document-hierarchy").getAttribute("data-trace-visible-link-count");
  await expand(page, "需求", 1);
  await expand(page, "设计", 1);
  await expect(page.locator(".trace-document-hierarchy")).toHaveAttribute("data-trace-visible-link-count", totalLinks!);
  await expect(page.locator(".trace-document-flow .react-flow__edge").first()).toBeVisible();
  expect((await treeState(page)).every(row => row.level === "1")).toBe(true);
  await page.locator(".trace-depth-toolbar").scrollIntoViewIfNeeded();
  await page.screenshot({path: `${images}/trace-level-controls-collapsed.png`});
  await expand(page, "需求", 4);
  await expand(page, "设计", 4);
  await page.locator(".trace-depth-toolbar").scrollIntoViewIfNeeded();
  await page.screenshot({path: `${images}/trace-level-controls-expanded.png`});
  expect(errors).toEqual([]);
  expect(mutations).toEqual([]);
});
