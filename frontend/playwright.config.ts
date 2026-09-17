import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', timeout: 60000, workers: 1,
  outputDir: '../artifacts/console-qa/test-results',
  use: { channel: 'chromium', baseURL: 'http://127.0.0.1:15173', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
});
