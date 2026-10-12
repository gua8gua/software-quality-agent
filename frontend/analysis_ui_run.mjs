import { chromium } from "@playwright/test";
const browser = await chromium.launch({headless: true, channel: "chromium"});
const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
page.setDefaultTimeout(60000);
page.on("response", response => { if (response.status() >= 400) console.log("HTTP", response.status(), response.url()); });
await page.goto("http://10.71.29.93:18003/#/projects/real-srs-sds-20260929/analysis/start");
const button = page.locator(".task-start-actions .ant-btn-primary");
await button.waitFor({timeout: 30000});
const enabledUntil = Date.now() + 90000;
while (await button.isDisabled() && Date.now() < enabledUntil) await new Promise(resolve => setTimeout(resolve, 2000));
if (await button.isDisabled()) throw new Error("analysis start button remains disabled after loading completed");
console.log("START", new Date().toISOString()); await button.click();
const started = Date.now();
while (Date.now() - started < 720000) {
  if (page.url().includes("/analysis/55f34d70-d38d-49e3-94d1-f01fe92c00d7/")) break;
  await new Promise(resolve => setTimeout(resolve, 10000));
  console.log("PROGRESS", Math.round((Date.now() - started) / 1000) + "s", (await page.locator("body").innerText()).slice(-500).replaceAll("\n", " | "));
}
console.log("END", new Date().toISOString(), "URL", page.url());
console.log("BODYTAIL", (await page.locator("body").innerText()).slice(-1500).replaceAll("\n", " | "));
await page.screenshot({path: "../../../../artifacts/analysis-real-run-result.png", fullPage: false}); await browser.close();
