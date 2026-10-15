import { defineConfig } from '@playwright/test'

// Deliberately separate from the normal 4320 instance and its author database.
const baseURL = process.env.ZHIBI_PREVIEW_URL || 'http://127.0.0.1:4332'
if (new URL(baseURL).port === '4320') throw new Error('Use an isolated preview database/server, never the normal author instance.')
export default defineConfig({
  testDir: './e2e', workers: 1, fullyParallel: false, timeout: 180_000,
  expect: { timeout: 15_000 },
  outputDir: '../data/settings-revision/playwright',
  reporter: [['list'], ['html', { outputFolder: '../data/settings-revision/report', open: 'never' }]],
  use: {
    baseURL, viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'retain-on-failure',
    launchOptions: process.env.ZHIBI_CHROMIUM ? { executablePath: process.env.ZHIBI_CHROMIUM } : {},
  },
})
