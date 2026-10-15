/** All API calls are intercepted: never edits a user's model configuration. */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4332'
const artifacts = resolve(process.env.TEST_ARTIFACT_DIR || '../data/loop-fix-evidence')
await mkdir(artifacts, { recursive: true })
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const errors = []
const unexpected = []
page.on('pageerror', error => errors.push(error.message))
const common = {
  provider: 'openai_compatible', base_url: 'https://model.example/v1', model: 'fake-chat',
  temperature: 0.8, max_tokens: null, timeout_s: 300, reasoning_effort: null,
  structured_method: 'json_mode', has_key: true,
}
const profiles = [
  { ...common, id: 'auto', name: '自动协商的模型', structured_method_auto: true },
  { ...common, id: 'manual', name: '手动选择的模型', structured_method_auto: false },
]
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  if (!path.startsWith('/api/')) return route.continue()
  if (route.request().method() !== 'GET') unexpected.push(`${route.request().method()} ${path}`)
  if (path === '/api/llm/profiles') return route.fulfill({ json: profiles })
  if (path === '/api/llm/roles') return route.fulfill({ json: { default: 'auto' } })
  if (path === '/api/books') return route.fulfill({ json: [] })
  if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
  unexpected.push(path)
  return route.fulfill({ status: 404, json: { detail: 'Unexpected test request' } })
})
try {
  await page.goto(`${baseURL}/settings`)
  const modal = page.getByRole('dialog', { name: '设置', exact: true })
  await expect(modal).toBeVisible()
  await expect(modal.getByText('已自动改用 json_mode', { exact: true })).toHaveCount(1)
  const auto = modal.locator('.settings-row').filter({ hasText: '自动协商的模型' })
  const manual = modal.locator('.settings-row').filter({ hasText: '手动选择的模型' })
  await expect(auto.getByText('已自动改用 json_mode')).toBeVisible()
  await expect(manual.getByText('已自动改用 json_mode')).toHaveCount(0)
  await page.screenshot({ path: resolve(artifacts, 'model-fallback-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(auto.getByText('已自动改用 json_mode')).toBeVisible()
  assert.equal(await modal.evaluate(element => element.scrollWidth <= element.clientWidth), true)
  await page.screenshot({ path: resolve(artifacts, 'model-fallback-mobile.png') })
  await auto.getByRole('button', { name: '修改', exact: true }).click()
  await expect(modal.getByLabel('结构化输出方式')).toHaveValue('json_mode')
  await expect(modal.getByLabel('API Key', { exact: true })).toHaveValue('')
  assert.deepEqual(unexpected, [])
  assert.deepEqual(errors, [])
  console.log('PASS automatic fallback hint appears only for auto-negotiated profiles, desktop and mobile')
  console.log('PASS edit form shows persisted json_mode without exposing the saved key; no writes or page errors')
} finally {
  await browser.close()
}
