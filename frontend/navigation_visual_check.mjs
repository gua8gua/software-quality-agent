import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const base = process.env.QUALITY_UI_URL || "http://localhost:15174";
const project = "real-srs-sds-20260929";
const out = "../artifacts/navigation-layout";
await mkdir(out, {recursive: true});
const browser = await chromium.launch({headless: true, channel: "chromium"});
const page = await browser.newPage({viewport: {width: 1600, height: 1100}, deviceScaleFactor: 1});
const errors = [];
page.on("pageerror", e => errors.push(e.message));
async function visit(path, title, filename) {
  await page.goto(`${base}/#/projects/${project}${path}`);
  await page.getByRole("heading", {name: title, exact: true}).waitFor();
  await page.locator(".ant-spin-spinning").waitFor({state: "detached"}).catch(() => {});
  await page.screenshot({path: `${out}/${filename}.png`, fullPage: true, animations: "disabled"});
}
try {
  await visit("/trace/start", "新建追溯任务", "trace-start");
  const pickers = page.locator(".task-picker");
  if (await pickers.count() !== 2) throw new Error("missing artifact pickers");
  await pickers.nth(0).locator(".artifact-file-row").first().click();
  await pickers.nth(1).locator(".artifact-file-row").first().click();
  await page.getByRole("button", {name: "启动追溯", exact: true}).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").locator(".ant-modal-close").click();
  await page.screenshot({path: `${out}/trace-selected.png`, fullPage: true});
  await page.getByRole("link", {name: "一致性分析", exact: true}).click();
  await page.getByRole("heading", {name: "一致性分析", exact: true}).waitFor();
  await page.screenshot({path: `${out}/analysis-list.png`, fullPage: true});
  await page.getByRole("button", {name: "新建一致性分析", exact: true}).click();
  await page.getByRole("heading", {name: "新建一致性分析任务", exact: true}).waitFor();
  await page.locator(".task-run-picker tbody tr.ant-table-row").first().waitFor();
  await page.screenshot({path: `${out}/analysis-start.png`, fullPage: true});
  await page.locator(".task-picker").first().getByRole("button", {name: "清空", exact: true}).click();
  await page.waitForFunction(() => document.querySelector(".task-picker-count")?.textContent === "已选 0 份");
  await page.locator(".task-picker").first().locator(".artifact-file-row").first().click();
  await page.getByRole("button", {name: "启动分析", exact: true}).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").locator(".ant-modal-close").click();
  await page.getByRole("link", {name: "追溯任务", exact: true}).click();
  await page.getByRole("heading", {name: "追溯任务", exact: true}).waitFor();
  await page.locator(".task-list-table tbody tr.ant-table-row").first().waitFor();
  await page.screenshot({path: `${out}/trace-list.png`, fullPage: true});
  await page.getByRole("button", {name: "查看结果", exact: true}).first().click();
  await page.getByRole("heading", {name: "TLR 追溯链接恢复结果", exact: true}).waitFor();
  await page.getByRole("link", {name: "质量报告", exact: true}).click();
  await page.locator(".project-section-nav a[aria-current=page]").filter({hasText: "质量报告"}).waitFor();
  await page.screenshot({path: `${out}/reports.png`, fullPage: true});
  await page.getByRole("link", {name: "项目资料库", exact: true}).click();
  await page.locator(".library-file-toolbar").waitFor();
  await page.screenshot({path: `${out}/library.png`, fullPage: true});
  if (errors.length) throw new Error(errors.join("\n"));
  console.log("Navigation, artifact selection and confirmation checks passed. No task was submitted.");
} finally {await browser.close();}
