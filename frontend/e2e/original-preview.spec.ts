import { test, expect } from "@playwright/test";

test("real stored DOCX uses raw bytes, not canonical JSON", async ({ page, request }) => {
  const project = "original-preview-verification";
  const response = await request.get(`/api/v1/projects/${project}/artifacts`);
  const files = await response.json();
  const docx = files.find((file: { external_id: string }) => file.external_id === "real-srs");
  expect(docx.media_type).toBe("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
  const calls: string[] = [], errors: string[] = [];
  page.on("request", request => calls.push(request.url()));
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`/#/projects/${project}/files/${docx.id}`);
  await expect(page.getByText(/docx-preview 原始文件预览 · 已渲染/)).toBeVisible({ timeout: 45000 });
  const frame = page.frameLocator('[data-renderer="docx-preview"]');
  expect(await frame.locator("section.docx").count()).toBeGreaterThan(0);
  expect(await frame.locator("table").count()).toBeGreaterThan(0);
  expect(await frame.locator("img").count()).toBeGreaterThan(0);
  expect(calls.some(url => url.includes(`/artifacts/${docx.id}/original`))).toBeTruthy();
  expect(calls.some(url => /content-tree|content-json|\/information\/nodes/.test(url))).toBeFalsy();
  expect(errors).toEqual([]);
  await page.screenshot({ path: "../artifacts/original-preview/docx-preview.png", fullPage: true });
  console.log(JSON.stringify({ renderer: "docx-preview", pages: await frame.locator("section.docx").count(),
    tables: await frame.locator("table").count(), images: await frame.locator("img").count(), rawRequest: docx.original_file_url }));
});

test("PDF.js renders the stored original even without canonical nodes", async ({ page, request }) => {
  const project = "original-preview-verification";
  const files = await (await request.get(`/api/v1/projects/${project}/artifacts`)).json();
  const pdf = files.find((file: { external_id: string }) => file.external_id === "pdf-baseline");
  expect(pdf.media_type).toBe("application/pdf");
  const calls: string[] = [], errors: string[] = [];
  page.on("request", request => calls.push(request.url()));
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`/#/projects/${project}/files/${pdf.id}`);
  await expect(page.locator('.pdfViewer canvas')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('[data-renderer="pdfjs"]')).toHaveAttribute('data-rendered-page', '1', { timeout: 30000 });
  await expect(page.locator('.pdfViewer .textLayer')).toContainText('Hello, world!', { timeout: 15000 });
  await page.locator('.pdfViewer .textLayer').getByText('Hello, world!', { exact: true }).scrollIntoViewIfNeeded();
  expect(calls.some(url => url.includes(`/artifacts/${pdf.id}/original`))).toBeTruthy();
  expect(calls.some(url => /content-tree|content-json|\/information\/nodes/.test(url))).toBeFalsy();
  expect(errors).toEqual([]);
  await page.screenshot({ path: "../artifacts/original-preview/pdf-preview.png", fullPage: true });
});
