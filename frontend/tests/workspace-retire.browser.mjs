/** 旧版书页退役：旧地址到书页、旧开书流程停在半路的书能停下开书、本书设置在书页上打开、待处理里让编辑部看看缺什么／查一遍。
 *  截图放进 docs/新书页验收/旧版退役/。先起好预览（zhibi-step2，网页 4322）；在 frontend 下运行：
 *  node tests/workspace-retire.browser.mjs <停在旧开书流程的书的 id> <普通书的 id>
 *  「把设定查一遍」用真模型，要等一两分钟。 */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const [setupBook, book] = process.argv.slice(2)
if (!setupBook || !book) throw new Error('要给两本书的 id')
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/旧版退役')
await fs.mkdir(output, { recursive: true })

const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || undefined })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
const shot = async (name) => {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(output, `${name}.jpg`), quality: 88 })
  console.log(name)
}

try {
  // 旧地址（收藏的、聊天记录里的）都到书页；ONLY=rest 跳过停下开书（停过一次就没了）
  if (process.env.ONLY !== 'rest') {
  await page.goto(`${base}/books/${setupBook}/library?cat=x`)
  await expect(page).toHaveURL(new RegExp(`/desk/${setupBook}$`))
  await expect(page.getByRole('button', { name: '回旧版' })).toHaveCount(0)
  const stop = page.getByRole('button', { name: /停下开书/ })
  await expect(stop).toBeVisible({ timeout: 30_000 })
  await shot('1-旧地址到书页-旧开书流程停在半路能停下')
  await stop.click()
  await expect(stop).toHaveCount(0, { timeout: 30_000 })
  await shot('2-停下开书以后直接在书页上写')
  }

  // 本书设置：盖在书上的一整页，Esc 关上
  await page.goto(`${base}/desk/${book}`)
  await page.getByRole('button', { name: '本书设置' }).click()
  await expect(page.getByRole('dialog', { name: '本书设置' })).toBeVisible()
  await expect(page.getByText('作者要求清单').first()).toBeVisible({ timeout: 30_000 })
  await shot('3-本书设置在书页上打开')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '本书设置' })).toHaveCount(0)

  // 待处理里让编辑部把设定查一遍（旧版的「检查」搬到这里）
  await page.getByRole('button', { name: /^待处理/ }).click()
  const panel = page.getByRole('complementary', { name: '待处理' })
  await panel.getByRole('button', { name: '把设定查一遍' }).click()
  await expect(panel.getByText(/查完了|看完了/)).toBeVisible({ timeout: 400_000 })
  await shot('4-待处理里让编辑部把设定查一遍')
  if (errors.length) console.log('页面报错：', errors)
} finally {
  await browser.close()
}
