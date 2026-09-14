import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";

test.use({ baseURL: process.env.CONSISTENCY_UI_URL || "http://127.0.0.1:5173" });
const created = "2026-09-14T08:00:00Z";
const requirement = "校验密码。创建会话。";
const code = "def login():\n    return True\n";
const artifacts = [
  { id: "ar", external_id: "R1", kind: "requirement", content: requirement, characters: requirement.length, locator: "requirements.md", structure: { title: "登录要求" } },
  { id: "ac", external_id: "C1", kind: "code", content: code, characters: code.length, locator: "src/auth/login.py", structure: { title: "登录代码" } },
];
const nodes = [
  { id: "root", parent_id: null, kind: "requirement", title: "登录需求根", text: requirement, start: 0, end: 10 },
  { id: "u1", parent_id: "root", kind: "unit", title: "密码校验任务", text: "校验密码。", start: 0, end: 5, categories: [{ category: "auth", subcategory: "login", title: "身份认证 / 登录控制" }] },
  { id: "u2", parent_id: "root", kind: "unit", title: "会话创建任务", text: "创建会话。", start: 5, end: 10, categories: [{ category: "auth", subcategory: "login", title: "身份认证 / 登录控制" }] },
];
function run(id: string, plan?: string, index = 0) { return { id, dataset_id: "ds", project_id: "p", created_at: created, status: "completed", stage: id === "r2" ? "completed_with_errors" : "completed", counts: { classified: 1, candidates: 2, links: 1 }, manifest: {}, config: { plan_id: plan, batch_label: plan ? "生命周期批次" : undefined, batch_index: index, layer_pair: index ? ["design", "implementation"] : ["requirements", "implementation"], source_ids: ["R1"], target_ids: ["C1"], options: {} } }; }
const runs = [run("r1", "plan1"), run("r2", "plan1", 1), run("solo")];
const report = {
  id: "analysis", status: "completed", created_at: created, analysis_kind: "code", request: { source_ids: ["R1"], target_ids: ["C1"] },
  snapshot: {
    dataset_id: "ds", tlr_run_id: "r1", target_ids: ["C1"], requirement_structure: { R1: { nodes } },
    packets: { R1: { requirement: { text: requirement }, requirement_units: nodes.slice(1), semantic_categories: { categories: [{ key: "auth", title: "身份认证", summary: "认证相关要求", subcategories: [{ key: "login", title: "登录控制", summary: "校验与会话" }] }] } } },
    document_structure: { R1: [{ id: "section1", kind: "document_section", title: "原文第一章", start: 0, end: 10 }] },
    code_structure: { C1: { nodes: [{ id: "file", kind: "file", name: "login.py 文件结构", start: 0, end: code.length }, { id: "func", parent_id: "file", kind: "function", name: "login 函数", start: 0, end: code.length }] } },
    tlr_elements: [{ id: "e1", role: "source", artifact_id: "R1", start: 0, end: 5, content: "校验密码。", processing: { unit_id: "u1" } }, { id: "e2", role: "target", artifact_id: "C1", start: 0, end: code.length, content: code }],
    links: [{ requirement_id: "R1", artifact_id: "C1", source_unit_id: "u1", source_element_id: "e1", element_id: "e2", target_start: 0, target_end: code.length }],
  },
  results: { requirements: { R1: { outcomes: ["conflict", "judgement_error"], whole_requirement_implemented: false, judgement: { summary: "校验存在冲突，会话尚未判明", missing_context: [] }, implementations: [
    { citations: [{ artifact_id: "C1", artifact_start: 0, quote: code, locator: "login.py", start_line: 1 }], parts: [{ unit_id: "u1", requirement_quote: "校验密码。", implemented_behavior: "直接返回成功", outcomes: ["conflict"], reason: "未校验密码即返回" }] },
    { citations: [], parts: [{ unit_id: "u2", requirement_quote: "创建会话。", implemented_behavior: "", outcomes: ["judgement_error"], reason: "缺少会话实现证据" }] },
  ] } } }, metrics: { selected_requirements: 1, processed_requirements: 1, outcome_counts: { conflict: 1, judgement_error: 1 } },
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") throw new Error("Browse-only test attempted a mutation");
    const reply = (data: unknown) => route.fulfill({ json: { code: 0, data } });
    const paged = (items: unknown[]) => reply({ items, total: items.length, offset: 0, limit: 100 });
    if (path.endsWith("/capabilities")) return reply({ kinds: [], embedding_configured: true, llm_configured: true });
    if (path === "/api/v1/tlr/projects/p") return reply({ id: "p", name: "质量分析导航", tenant_id: "local" });
    if (path.endsWith("/projects/p/datasets")) return paged([{ id: "ds", version: "v1", created_at: created }]);
    if (path.endsWith("/projects/p/runs")) return paged(runs);
    if (path.endsWith("/plans/plan1/runs")) return reply({ runs: runs.slice(0, 2) });
    if (path.endsWith("/inventory")) return paged(artifacts);
    if (path.endsWith("/artifacts/ar")) return reply(artifacts[0]);
    if (path.endsWith("/artifacts/ac")) return reply(artifacts[1]);
    if (path.endsWith("/visualization")) return reply({ elements: [], candidates: [], links: [], hierarchy: [], failures: [], projection: { nodes: [], links: [] } });
    if (path === "/api/v1/tlr/runs/r1") return reply(runs[0]);
    if (path === "/api/v1/consistency/runs") return paged([{ id: "analysis", status: "completed", created_at: created, dataset_id: "ds", tlr_run_id: "r1" }]);
    if (path === "/api/v1/consistency/runs/analysis") return reply(report);
    throw new Error("Unexpected request " + path);
  });
});

test("batch list opens only its own child tasks and preserves back navigation", async ({ page }) => {
  await page.goto("/quality.html#/projects/p/tlr");
  await expect(page.getByRole("heading", { name: "TLR 批次记录 · 2 个批次" })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看子任务", exact: true })).toHaveCount(2);
  await expect(page.getByRole("link", { name: "查看子任务结果", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "生命周期批次", exact: true }).click();
  await expect(page.getByRole("heading", { name: "批次子任务", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看子任务结果", exact: true })).toHaveCount(2);
  await expect(page.locator("main")).not.toContainText("solo");
  await page.reload();
  await page.getByRole("link", { name: "查看子任务结果", exact: true }).first().click();
  await expect(page).toHaveURL(/\/runs\/r1$/);
  await page.getByRole("link", { name: "返回所属批次", exact: true }).click();
  await page.getByRole("link", { name: "返回 TLR 批次列表", exact: true }).click();
  await page.getByRole("link", { name: "单任务批次 solo", exact: true }).click();
  await expect(page.getByRole("link", { name: "查看子任务结果", exact: true })).toHaveCount(1);
});

test("original artifacts, intermediate units, groups and reverse implementation navigation", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/quality.html#/projects/p/analyses");
  await page.getByRole("link", { name: "查看分析", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "一致性分析详情", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "登录要求", exact: true }).click();
  await expect(page.locator("main")).toContainText("登录控制");
  await expect(page.locator("main")).toContainText("未校验密码即返回");
  await expect(page.locator("main")).toContainText("缺少会话实现证据");
  await page.getByRole("link", { name: "构建结构", exact: true }).click();
  const layer = page.getByLabel("构建结构展示层", { exact: true });
  const kind = page.getByLabel("构建结构类型", { exact: true });
  const search = () => page.getByLabel("搜索构建结构节点", { exact: true });
  await expect(kind).toHaveValue("semantic");
  await search().fill("密码校验任务");
  await page.getByRole("link", { name: "密码校验任务", exact: true }).click();
  await expect(page.locator("main")).toContainText("匹配片段 · 字符 0–5");
  await expect(page.locator("main")).toContainText("未校验密码即返回");
  await expect(page.locator("main")).not.toContainText("缺少会话实现证据");
  await page.getByRole("link", { name: "login 函数", exact: true }).click();
  await expect(page.getByRole("heading", { name: "此单元承担的上层任务", exact: true })).toBeVisible();
  await expect(page.locator("main")).toContainText("校验密码。");
  await expect(page.locator("main")).toContainText("def login()");
  await page.reload();
  await expect(page.locator("main")).toContainText("未校验密码即返回");
  await page.getByRole("link", { name: "构建结构", exact: true }).click();
  await kind.selectOption("sections");
  await search().fill("原文第一章");
  await expect(page.getByRole("link", { name: "原文第一章", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "密码校验任务", exact: true })).toHaveCount(0);
  await kind.selectOption("groups");
  await search().fill("会话创建任务");
  await expect(page.getByRole("link", { name: "身份认证", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "会话创建任务", exact: true }).click();
  await expect(page.locator("main")).toContainText("未定位有效下层单元");
  await expect(page.locator("main")).toContainText("判断出错");
  await page.getByRole("link", { name: "构建结构", exact: true }).click();
  await layer.selectOption("target");
  await kind.selectOption("project");
  await page.getByRole("button", { name: "展开 src", exact: true }).click();
  await page.getByRole("button", { name: "展开 auth", exact: true }).click();
  await expect(page.getByRole("link", { name: "登录代码", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "登录要求", exact: true })).toHaveCount(0);
  await mkdir("../artifacts/consistency-ui", { recursive: true });
  await page.screenshot({ path: "../artifacts/consistency-ui/code-project-tree.png", fullPage: true });
  await kind.selectOption("syntax");
  await search().fill("login 函数");
  await expect(page.getByRole("link", { name: "login 函数", exact: true })).toBeVisible();
  await kind.selectOption("match");
  await search().fill("匹配片段");
  await expect(page.getByRole("link", { name: /匹配片段/ })).toHaveCount(1);
  expect(errors).toEqual([]);
});
