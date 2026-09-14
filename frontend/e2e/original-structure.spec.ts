import { test, expect } from "@playwright/test";
test.use({ baseURL: process.env.CONSISTENCY_UI_URL || "http://127.0.0.1:5173" });

test("project structure uses original layer endpoint and switches one layer at a time", async ({ page }) => {
  const queried: string[] = [];
  await page.route("**/api/v1/**", route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const reply = (data: unknown) => route.fulfill({ json: { code: 0, data } });
    const paged = (items: unknown[]) => reply({ items, total: items.length, offset: 0, limit: 100 });
    if (path.endsWith("/capabilities")) return reply({ kinds: [], embedding_configured: true, llm_configured: true });
    if (path.endsWith("/projects/p")) return reply({ id: "p", name: "原始层级验证", tenant_id: "local" });
    if (path.endsWith("/datasets")) return paged([{ id: "ds", version: "v1", created_at: "2026-09-14T08:00:00Z" }]);
    if (path.endsWith("/runs") || path.endsWith("/inventory")) return paged([]);
    if (path.endsWith("/original-structure")) {
      const layer = url.searchParams.get("layer")!; queried.push(layer);
      expect(url.searchParams.get("tenant_id")).toBe("local");
      expect(url.searchParams.get("project_id")).toBe("p");
      const code = layer === "implementation";
      return reply({ layer, layers: [{ id: "requirements", label: "需求", count: 1 }, { id: "implementation", label: "代码实现", count: 1 }], artifact_count: 1, unstructured_count: 0, warnings: [], semantics: [], nodes: [
        { id: "group", parent_id: null, artifact_id: null, title: code ? "原始代码包" : "原始需求分组", node_type: "原始容器", metadata_json: { source: "input.hierarchy", container: true } },
        { id: "child", parent_id: "group", artifact_id: code ? "ac" : "ar", title: code ? "代码引用" : "原始需求", node_type: code ? "Code" : "Requirement", metadata_json: { source: "artifact.structure.tree_paths", content_status: code ? "reference_only" : "full_text" } },
      ] });
    }
    throw new Error("Unexpected request; legacy hierarchy must not be used: " + path);
  });
  await page.goto("/quality.html#/projects/p");
  await page.getByRole("tab", { name: "结构关系", exact: true }).click();
  await page.getByRole("button", { name: "展开 原始需求分组", exact: true }).click();
  await expect(page.getByRole("link", { name: "原始需求", exact: true })).toBeVisible();
  await page.getByLabel("结构关系数据层级", { exact: true }).selectOption("implementation");
  await page.getByRole("button", { name: "展开 原始代码包", exact: true }).click();
  await expect(page.getByRole("link", { name: "代码引用", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "原始需求", exact: true })).toHaveCount(0);
  await expect(page.locator("main")).toContainText("仅有引用");
  expect([...new Set(queried)]).toEqual(["requirements", "implementation"]);
});
