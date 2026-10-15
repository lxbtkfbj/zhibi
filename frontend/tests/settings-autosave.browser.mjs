/** Isolated UI regression: settings writes are intercepted, never sent to the database. */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4332'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const artifacts = resolve(process.env.TEST_ARTIFACT_DIR || '../data/settings-revision')
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
let response = await (await fetch(`${baseURL}/api/settings/new-book-defaults`)).json()
let nextFailure = false
let delayNext = false
const writes = []
await page.route('**/api/settings/new-book-defaults', async route => {
  if (route.request().method() === 'GET') return route.fulfill({ json: response })
  const body = route.request().postDataJSON()
  writes.push(body)
  if (delayNext) { delayNext = false; await new Promise(resolve => setTimeout(resolve, 250)) }
  if (nextFailure) { nextFailure = false; return route.fulfill({ status: 503, json: { detail: '测试保存失败，请重试' } }) }
  response = { settings: { ...response.settings, ...body }, rules_text: `【这本书的写作规矩】\n- 测试预览：${body.title_custom ?? body.title_style ?? response.settings.title_style}` }
  return route.fulfill({ json: response })
})
const modal = page.getByRole('dialog', { name: '设置', exact: true })
const title = () => modal.getByRole('group', { name: '书名风格', exact: true })
try {
  await page.goto(`${baseURL}/settings`)
  await expect(modal).toBeVisible()
  await expect(page).toHaveURL(`${baseURL}/`)
  await modal.getByRole('button', { name: '＋ 添加', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await expect(modal.getByRole('textbox', { name: '模型配置名称' })).toBeVisible()
  await modal.getByRole('button', { name: '返回', exact: true }).click()
  console.log('PASS modal redirects from /settings, edits models without nested dialog')

  await modal.getByRole('tab', { name: '外观', exact: true }).click()
  await modal.getByRole('button', { name: '墨色·暗', exact: true }).click()
  await modal.getByRole('button', { name: '楷体', exact: true }).click()
  await modal.getByRole('button', { name: '正文字号增加', exact: true }).click()
  await modal.getByRole('switch', { name: '减少动效' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ink')
  await expect(page.locator('html')).toHaveAttribute('data-font', 'kai')
  const appearance = await page.evaluate(() => JSON.parse(localStorage.getItem('zhibi:appearance')))
  assert.equal(appearance.readingSize, 18)
  assert.equal(appearance.reducedMotion, true)
  await page.screenshot({ path: resolve(artifacts, 'settings-appearance-dark.png') })
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ink')
  assert.equal(await page.locator('html').evaluate(element => element.style.getPropertyValue('--reading-size')), '18px')
  console.log('PASS appearance changes apply immediately and persist on reload')

  await page.goto(`${baseURL}/settings`)
  await modal.getByRole('tab', { name: '新书默认', exact: true }).click()
  delayNext = true
  await title().getByRole('button', { name: '番茄长书名', exact: true }).click()
  await title().getByRole('button', { name: '交给主编', exact: true }).click()
  await title().getByRole('button', { name: '经典短书名', exact: true }).click()
  await expect.poll(() => response.settings.title_style).toBe('short')
  await expect.poll(() => writes.length).toBe(3)
  await expect(title().getByRole('button', { name: '经典短书名' })).toHaveAttribute('aria-pressed', 'true')
  assert.deepEqual(writes.map(body => body.title_style), ['tomato', 'chief', 'short'])
  console.log('PASS slow earlier response cannot overwrite rapid subsequent settings')

  nextFailure = true
  await title().getByRole('button', { name: '自己写', exact: true }).click()
  await expect(modal.getByText('测试保存失败，请重试', { exact: true })).toBeVisible()
  await expect(modal.getByRole('textbox', { name: '自己写的书名规矩' })).toBeVisible()
  await modal.getByRole('textbox', { name: '自己写的书名规矩' }).fill('失败后保留的作者原文')
  await expect.poll(() => response.settings.title_custom).toBe('失败后保留的作者原文')
  assert.equal(response.settings.title_style, 'custom')
  await expect(modal.getByText('测试保存失败，请重试', { exact: true })).toHaveCount(0)
  await modal.getByRole('tab', { name: '模型', exact: true }).click()
  await modal.getByRole('tab', { name: '新书默认', exact: true }).click()
  await expect(modal.getByRole('textbox', { name: '自己写的书名规矩' })).toHaveValue('失败后保留的作者原文')
  console.log('PASS failed settings remain editable, next save retries them, cache reopen stays current')

  await modal.getByRole('textbox', { name: '自己写的书名规矩' }).fill('切换分页也保存未到时的输入')
  await modal.getByRole('tab', { name: '模型', exact: true }).click()
  await expect.poll(() => response.settings.title_custom).toBe('切换分页也保存未到时的输入')
  response.settings = { ...response.settings, title_custom: '另一窗口的最新原文' }
  await modal.getByRole('tab', { name: '新书默认', exact: true }).click()
  await expect(modal.getByRole('textbox', { name: '自己写的书名规矩' })).toHaveValue('另一窗口的最新原文')
  console.log('PASS tab change flushes pending typing and clean editor accepts refreshed server state')

  await modal.getByRole('group', { name: '力度', exact: true }).getByRole('button', { name: '自定义', exact: true }).click()
  await expect(modal.getByRole('switch', { name: '卷纲专项审稿' })).toBeVisible()
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect.poll(() => modal.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
    const box = await modal.boundingBox()
    assert.ok(box.x >= 0 && box.x + box.width <= width)
    await page.screenshot({ path: resolve(artifacts, `settings-defaults-${width}.png`) })
  }
  assert.deepEqual(errors, [])
  console.log('PASS custom effort shows four subrows; dark settings fit desktop and 390px screens')
} finally { await browser.close() }
