// Submit exactly one real artifact-level task through the deployed UI.
import { chromium } from "@playwright/test";
import { access, mkdir, writeFile } from "node:fs/promises";

const output = "../artifacts/navigation-layout";
const receipt = `${output}/real-analysis-submission.json`;
await mkdir(output, {recursive: true});
try {await access(receipt); throw new Error("Submission receipt exists; inspect or resume it, never submit a duplicate.");}
catch (e) {if (e.code !== "ENOENT") throw e;}
const browser = await chromium.launch({headless: true, channel: "chromium"});
const page = await browser.newPage({viewport: {width: 1600, height: 1100}});
try {
  await page.goto("http://10.71.29.93:18003/#/projects/real-srs-sds-20260929/analysis/start");
  await page.locator(".task-run-picker tr.ant-table-row").first().waitFor();
  await page.getByRole("textbox", {name: "任务名称", exact: true}).fill("完整工件一致性分析 · 界面验证");
  await page.getByRole("textbox", {name: "任务描述", exact: true}).fill("基于已有已完成追溯，分析所选需求与设计工件的全部受支持内容；独立语块错误持久化且继续处理后续语块。不重新运行追溯或 embedding。");
  await page.getByRole("button", {name: "启动分析", exact: true}).click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  const creation = page.waitForResponse(response => response.request().method() === "POST" && /\/reviews\/batch\?/.test(response.url()));
  const execution = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/agent/review-suggestions/batch"));
  await dialog.locator(".ant-btn-primary").click();
  const created = await creation;
  const body = await created.json();
  // A created task is already durable, even if execution submission fails.
  const record = {at: new Date().toISOString(), creation_status: created.status(), selected_scope: created.request().postDataJSON(), task: body};
  await writeFile(receipt, JSON.stringify(record, null, 2));
  if (!created.ok()) throw new Error(`Creation failed ${created.status()}: ${JSON.stringify(body)}`);
  const started = await execution;
  record.execution_status = started.status(); record.execution = await started.json();
  await writeFile(receipt, JSON.stringify(record, null, 2));
  if (!started.ok()) throw new Error(`Execution submission failed ${started.status()}`);
  await page.waitForURL(/\/analysis\/batch\//);
  await page.getByRole("heading", {name: "完整工件一致性分析 · 界面验证", exact: true}).waitFor();
  await page.locator(".batch-overview").waitFor();
  await page.screenshot({path: `${output}/analysis-batch-started.png`, fullPage: true, animations: "disabled"});
  console.log(JSON.stringify({batch_id: body.batch_id, source_node_count: body.source_node_count, status: record.execution.status}));
} finally {await browser.close();}
