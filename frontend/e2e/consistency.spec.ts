import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";

test.use({ baseURL: process.env.CONSISTENCY_UI_URL || "http://127.0.0.1:15173" });

for (const mode of ["fresh", "fresh-partial", "existing", "existing-partial", "document"]) {
  test("consistency workflow: " + mode, async ({ page }) => {
    const calls: string[] = [], errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const date = "2026-09-13T08:00:00Z";
    const artifacts = [
      { id: "a1", external_id: "R1", kind: "requirement", characters: 15, structure: { title: "登录需求" } },
      { id: "a2", external_id: "C1", kind: "code", characters: 30, locator: "login.py" },
      { id: "a3", external_id: "D1", kind: "design", characters: 30 },
      { id: "a4", external_id: "D2", kind: "detailed_design", characters: 30 },
      { id: "ref", external_id: "C-ref", kind: "code", characters: 25, structure: { title: "仅路径代码", content_status: "reference_only" } },
      ...Array.from({ length: 66 }, (_, i) => ({ id: `r${i + 2}`, external_id: `R${i + 2}`, kind: "requirement", characters: 20 })),
    ];
    const sourceIds = artifacts.filter(a => a.kind === "requirement").map(a => a.external_id);
    const targetIds = mode === "document" ? ["D1", "D2"] : ["C1"];
    const run = (id: string, status = "completed", targets = ["C1"], dataset = "ds") => ({
      id, status, stage: "completed", project_id: "p", dataset_id: dataset, created_at: date,
      counts: { links: 1, classified: 1, candidates: 1 }, manifest: {},
      config: { source_ids: sourceIds, target_ids: targets, options: {} },
    });
    let report: any = null;
    await page.route("**/api/v1/**", async route => {
      const req = route.request(), path = new URL(req.url()).pathname, method = req.method();
      const reply = (data: unknown) => route.fulfill({ json: { code: 0, data } });
      const paged = (items: unknown[]) => reply({ items, total: items.length, limit: 100, offset: 0 });
      if (path.endsWith("/capabilities")) return reply({ kinds: [], embedding_configured: true, llm_configured: true });
      if (path === "/api/v1/tlr/projects/p") return reply({ id: "p", name: "一致性页面验证", description: "", tenant_id: "local" });
      if (path.endsWith("/projects/p/datasets")) return paged([{ id: "ds", version: "v1", created_at: date }]);
      if (path.endsWith("/projects/p/runs")) return paged([run("ready"), run("pending", "pending"), run("design", "completed", ["D1"]), run("other", "completed", ["C1"], "other-ds"), { ...run("partial"), stage: "completed_with_errors" }]);
      if (["/api/v1/tlr/runs/new", "/api/v1/tlr/runs/ready", "/api/v1/tlr/runs/partial"].includes(path)) return reply(run(path.split("/").at(-1)!));
      if (path.endsWith("/inventory")) return paged(artifacts);
      if (path === "/api/v1/tlr/artifacts/a1") return reply({ ...artifacts[0], content: "登录应校验密码" });
      if (path.endsWith("/layers")) return reply({ layers: [
        { id: "requirements", label: "需求", artifact_ids: sourceIds },
        { id: "design", label: "详细设计", artifact_ids: ["D1", "D2"] },
        { id: "implementation", label: "代码实现", artifact_ids: ["C1"] },
      ] });
      if (path === "/api/v1/requirements/analyses") { calls.push("hierarchy"); expect(req.postDataJSON().source_ids).toEqual(sourceIds); return reply({ id: "hierarchy", status: "completed" }); }
      if (path === "/api/v1/tlr/runs" && method === "POST") { calls.push("tlr-create"); expect(req.postDataJSON().options.requirements_run_id).toBe("hierarchy"); expect(req.postDataJSON().source_ids).toEqual(sourceIds); expect(req.postDataJSON().target_ids).toEqual(targetIds); return reply(run("new")); }
      if (path === "/api/v1/tlr/runs/new/execute") { calls.push("tlr-execute"); return reply(mode === "fresh-partial" ? { ...run("new"), stage: "completed_with_errors" } : run("new")); }
      if (path === "/api/v1/consistency/runs" && method === "POST") {
        calls.push("consistency-create");
        expect(req.postDataJSON().tlr_run_id).toBe(mode === "existing-partial" ? "partial" : mode === "existing" ? "ready" : "new");
        expect(req.postDataJSON().source_ids).toEqual(sourceIds);
        expect(req.postDataJSON().target_ids).toEqual(targetIds);
        report = { id: "analysis", status: "prepared", created_at: date, request: req.postDataJSON(), snapshot: { dataset_id: "ds", tlr_run_id: req.postDataJSON().tlr_run_id },
          results: { requirements: {} }, metrics: { selected_requirements: 1, processed_requirements: 0, outcome_counts: {} } };
        return reply(report);
      }
      if (path === "/api/v1/consistency/runs") return paged(report ? [{ id: report.id, status: report.status, created_at: date, dataset_id: "ds", tlr_run_id: report.snapshot.tlr_run_id }] : []);
      if (path === "/api/v1/consistency/runs/analysis/execute") {
        calls.push("consistency-execute");
        report.status = "completed"; report.metrics.processed_requirements = 1;
        report.metrics.outcome_counts = { conflict: 1, judgement_error: 1 };
        report.results.requirements.R1 = { outcomes: ["conflict", "judgement_error"], whole_requirement_implemented: false,
          implementations: [{ citations: [{ artifact_id: "C1", locator: "login.py", start_line: 1, quote: "return True" }],
            parts: [{ requirement_quote: "登录应校验密码", implemented_behavior: "始终返回成功", outcomes: ["conflict"], reason: "没有校验密码" }] }],
          analysis_errors: ["另一部分缺少上下文"] };
        return reply(report);
      }
      if (path === "/api/v1/consistency/runs/analysis") return reply(report);
      throw new Error("Unexpected request: " + method + " " + path);
    });
    await page.goto("/#/projects/p");
    await page.getByRole("tab", { name: "一致性分析", exact: true }).click();
    await page.getByRole("button", { name: "新建一致性分析", exact: true }).click();
    if (mode.startsWith("existing")) {
      await page.getByRole("radio", { name: "使用已有 TLR 辅助（含部分完成）" }).check();
      const select = page.getByLabel("辅助追踪", { exact: true });
      await expect(select.locator("option")).toHaveCount(3);
      await select.selectOption(mode === "existing-partial" ? "partial" : "ready");
      if (mode === "existing-partial") await expect(page.getByRole("dialog")).toContainText("未完成匹配不代表功能缺失");
    }
    if (mode === "document") await page.getByLabel("分析对象", { exact: true }).selectOption("document");
    await page.getByLabel("源文档层级", { exact: true }).selectOption("requirements");
    await expect(page.getByRole("dialog")).toContainText("已选 67 份源文档");
    await expect(page.getByRole("dialog")).not.toContainText("判断基准");
    if (mode === "document") {
      await expect(page.getByLabel("目标文档层级", { exact: true }).locator('option[value="requirements"]')).toHaveJSProperty("disabled", true);
      await page.getByLabel("目标文档层级", { exact: true }).selectOption("design");
      await expect(page.getByRole("dialog")).toContainText("已选 2 份目标");
    } else {
      await expect(page.getByRole("dialog")).toContainText("1 个代码条目缺少源码正文");
      await page.getByRole("button", { name: "选择全部目标", exact: true }).click();
      await expect(page.getByLabel("目标：C1", { exact: true })).toBeChecked();
    }
    await page.getByRole("button", { name: "开始一致性分析", exact: true }).click();
    await expect(page.getByRole("heading", { name: "一致性分析详情", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "登录需求", exact: true }).click();
    await expect(page.locator("main")).toContainText("没有校验密码");
    await expect(page.locator("main")).toContainText("冲突、判断出错");
    expect(calls).toEqual([...(!mode.startsWith("existing") ? ["hierarchy", "tlr-create", "tlr-execute"] : []), "consistency-create", "consistency-execute"]);
    await mkdir("../artifacts/consistency-ui", { recursive: true });
    await page.screenshot({ path: "../artifacts/consistency-ui/" + mode + ".png", fullPage: true });
    await page.getByRole("link", { name: "返回一致性分析列表", exact: true }).click();
    await page.reload();
    await page.getByRole("tab", { name: "一致性分析", exact: true }).click();
    await page.getByRole("link", { name: "查看分析", exact: true }).click();
    await page.getByRole("link", { name: "登录需求", exact: true }).click();
    await expect(page.locator("main")).toContainText("没有校验密码");
    expect(calls.filter(c => c === "consistency-execute")).toHaveLength(1);
    expect(errors).toEqual([]);
  });
}
