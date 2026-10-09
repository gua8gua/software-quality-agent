import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { projectWorkflow } from "../src/quality/results/workflowRecords";

test("公开记录保留真实调用、缺失结果与尝试边界，重复角色不构成环", () => {
  const raw = {attempts: 2, workflow_status: "blocked", attempt_history: [{attempt: 1, workflow_status: "completed", model_calls: []}],
    sdk_tool_results: {"call-1": {output: '{"check_id":"real-check"}'}},
    model_calls: [
      {agent: "review manager agent", at: "2026-10-04T08:00:00Z", status: "completed", output: [{type: "function_call", call_id: "call-1", name: "get_review_progress", arguments: "{}"}]},
      {agent: "review analysis agent", at: "2026-10-04T08:00:01Z", status: "completed", output: [{type: "reasoning", content: "must not display"}, {type: "function_call", call_id: "missing", name: "get_review_segment", arguments: "{}"}]},
      {agent: "review manager agent", at: "2026-10-04T08:00:02Z", status: "blocked", output: []},
    ]};
  const {view, details} = projectWorkflow(raw);
  expect(view.nodes).toHaveLength(3);
  expect(new Set(view.nodes.map(n => n.id)).size).toBe(3);
  expect(view.edges.every(e => view.nodes.findIndex(n => n.id === e.source) < view.nodes.findIndex(n => n.id === e.target))).toBe(true);
  expect(view.steps.find(s => s.callId === "missing")?.status).toBe("not_recorded");
  expect(JSON.stringify([...details.values()])).not.toContain("must not display");
  expect([...details.values()].find(s => s.callId === "call-1")?.output).toEqual({check_id: "real-check"});
  expect(projectWorkflow(raw, 1).view.nodes).toHaveLength(0);
  const wrapperOnly = projectWorkflow({...raw, tool_calls: [{name: "read_review_passage", at: "2026-10-04T08:00:04Z", succeeded: false}],
    tool_errors: [{name: "read_review_passage", at: "2026-10-04T08:00:05Z", message: "read failed"}]}).view.steps;
  expect(wrapperOnly.find(s => s.id.includes("wrapper"))).toMatchObject({agent: "", nodeId: "", status: "blocked"});
  expect(projectWorkflow({workflow_status: "blocked", errors: [{stage: "review_analysis", error_code: "context_budget", message: "blocked before request"}]}).view.steps).toHaveLength(1);
  const running = projectWorkflow({...raw, workflow_status: "running", model_calls: [raw.model_calls[1]]}).view;
  expect(running.nodes[0]).toMatchObject({status: "running"});
  expect(running.nodes[0].phase).toContain("等待工具结果");
});

test("真实语段的流程图、节点详情、全流程与历史尝试（只读）", async ({page}) => {
  const images = "../artifacts/page-design/20261004-workflow";
  mkdirSync(images, {recursive: true});
  const errors: string[] = [], writes: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", r => {if (r.url().includes("/api/") && r.method() !== "GET") writes.push(r.url());});
  await page.setViewportSize({width: 1720, height: 1150});
  await page.goto("/#/projects/real-srs-sds-20260929/analysis/55f34d70-d38d-49e3-94d1-f01fe92c00d7/84769a00-0275-4d15-bbec-07f4381ef100?review=b4528efc-ae7c-4507-95f1-229700879570&view=workflow");
  await expect(page.locator(".workflow-agent-card").first()).toBeVisible({timeout: 45000});
  await expect(page.getByText("读取已取消", {exact: true})).toHaveCount(0);
  await expect(page.getByRole("tab", {name: "LLM 工作过程", exact: true})).toHaveAttribute("aria-selected", "true");
  await page.locator(".workflow-agent-card").filter({hasText: "Review Analysis"}).first().click();
  await expect(page.locator(".workflow-node-heading")).toContainText("Review Analysis");
  await page.locator(".workflow-record-header").first().click();
  await expect(page.locator(".workflow-record-body").first()).toContainText("公开输出");
  await page.locator(".review-page-tabs").scrollIntoViewIfNeeded();
  await page.screenshot({path: `${images}/workflow-node-desktop.png`, fullPage: true, animations: "disabled"});
  await page.getByRole("tab", {name: "全流程执行面板", exact: true}).click();
  await page.getByRole("checkbox", {name: "工具调用", exact: true}).check();
  const count = await page.locator(".workflow-record-header:visible").count();
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThanOrEqual(20);
  await page.locator(".workflow-record-header:visible").first().click();
  await expect(page.locator(".workflow-record-body:visible")).toContainText("工具参数");
  await expect(page.locator(".workflow-record-body:visible")).toContainText("工具结果");
  await page.screenshot({path: `${images}/workflow-timeline-desktop.png`, fullPage: true, animations: "disabled"});
  await page.getByRole("checkbox", {name: "工具调用", exact: true}).uncheck();
  await page.getByRole("combobox", {name: "选择执行尝试"}).click();
  await page.locator(".ant-select-dropdown:visible .ant-select-item-option").last().click();
  await expect(page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
  await expect(page.locator(".workflow-agent-card").first()).toBeVisible();
  await page.getByRole("button", {name: "刷新记录", exact: true}).click();
  await expect(page.locator(".workflow-agent-card").first()).toBeVisible();
  await page.setViewportSize({width: 760, height: 1050});
  await expect.poll(async () => {
    const canvas = await page.locator(".workflow-canvas").boundingBox();
    const node = await page.locator(".workflow-agent-card").first().boundingBox();
    return !!canvas && !!node && node.x >= canvas.x && node.x + node.width <= canvas.x + canvas.width;
  }).toBe(true);
  const narrowShot = await page.screenshot({path: `${images}/workflow-narrow.png`, fullPage: true, animations: "disabled"});
  expect(narrowShot.readUInt32BE(16)).toBe(760);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.getByRole("tab", {name: "评审结果", exact: true}).click();
  await expect(page.locator(".analysis-grid")).toBeVisible();
  await page.setViewportSize({width: 1720, height: 1150});
  await page.goto("/#/projects/real-srs-sds-20260929/analysis/batch/aa62daed-8d58-47d6-aa6c-4c12ffbbfd93");
  await page.getByRole("button", {name: "查看 LLM 工作过程 →", exact: true}).click();
  await expect(page.getByRole("tab", {name: "LLM 工作过程", exact: true})).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".workflow-agent-card").first()).toBeVisible({timeout: 45000});
  expect(errors).toEqual([]); expect(writes).toEqual([]);
});
