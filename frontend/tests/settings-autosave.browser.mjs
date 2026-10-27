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
const modal = page.getByRole('dialog', { name: '系统设置', exact: true })
const title = () => modal.getByRole('group', { name: '书名风格', exact: true })
try {
  await page.goto(`${baseURL}/settings`)
  await expect(modal).toBeVisible()
  assert.deepEqual(await modal.locator('.settings-tools-link').evaluateAll(items => items.map(item => item.getAttribute('aria-label'))), ['预设管理', '提示词与调用记录'])
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

  // 用户批准：旧自定义/专项审稿开关已由 HEAD 移除，等价检查当前精品档，
  // 保存字段和精确说明都不能放宽；后面的六视口几何边界保持完整。
  const premium = { effort_preset: 'premium', max_rewrites: 3, pitches: 3, volume_audit: true, review_strictness: 'strict' }
  const effort = modal.getByRole('group', { name: '编辑部写得多仔细', exact: true })
  await effort.getByRole('button', { name: '精品', exact: true }).click()
  await expect(effort.getByRole('button', { name: '精品', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => Object.fromEntries(Object.keys(premium).map(key => [key, response.settings[key]]))).toEqual(premium)
  assert.deepEqual(writes.at(-1), premium, '精品档必须一次完整保存这五个字段')
  await expect(modal.getByText('审稿更严，中等毛病也退回，最多重写 3 次；卷纲出三版挑好的，再专门查一遍。最慢，最费额度。', { exact: true })).toBeVisible()
  console.log('PASS 当前精品档精确保存五个字段，选中态和完整白话说明同步更新')
  for (const [width, height] of [[1440, 1000], [1127, 886], [1366, 768], [1024, 600], [686, 993], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await expect.poll(() => modal.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
    const box = await modal.boundingBox()
    const margin = width <= 600 ? 10 : 18
    // 开工 HEAD: width 940px；desktop height 780px；mobile 640px；
    // max-width = 100vw - 36px，max-height = 88dvh（这六种视口 desk zoom 都为 1）。
    assert.ok(Math.abs(box.width - Math.min(940, width - 36)) < 1)
    assert.ok(Math.abs(box.height - Math.min(width <= 600 ? 640 : 780, height * .88)) < 1)
    assert.ok(Math.abs(box.x + box.width / 2 - width / 2) < 1, 'Dialog stays horizontally centered')
    assert.ok(Math.abs(box.y + box.height / 2 - height / 2) < 1, 'Dialog stays vertically centered')
    const close = await modal.getByRole('button', { name: '关闭设置' }).boundingBox()
    assert.ok(close.x >= margin && close.x + close.width <= width - margin)
    assert.ok(close.y >= margin && close.y + close.height <= height - margin, 'Close button remains on screen')
    await page.screenshot({ path: resolve(artifacts, `settings-defaults-${width}x${height}.png`) })
  }
  assert.deepEqual(errors, [])
  console.log('PASS 开工 HEAD 的 940x780（手机高640）弹窗按88dvh上限居中，六种桌面/矮屏/手机视口均可用')
} finally { await browser.close() }
