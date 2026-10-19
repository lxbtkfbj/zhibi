/** 角色置顶（代替「定位」）：卡上没有定位了，右上角点图钉置顶；置顶的排在目录最上面，后置顶的在上。
 *  截图放进 docs/新书页验收/角色置顶/。先起好预览（zhibi-step2，网页 4322）；在 frontend 下运行：
 *  node tests/workspace-pin.browser.mjs <书的 id> <要置顶的人名，按先后，几个都行> */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const [bookId, ...names] = process.argv.slice(2)
if (!bookId || !names.length) throw new Error('要给书的 id 和要置顶的几个人名（按先后）')
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/角色置顶')
await fs.mkdir(output, { recursive: true })

const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || undefined })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
const shot = async (file) => {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(output, `${file}.jpg`), quality: 88 })
  console.log(file)
}

try {
  await page.goto(`${base}/desk/${bookId}`)
  const dir = page.locator('aside, nav').first()
  await expect(page.getByRole('button', { name: names[0], exact: true }).first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('定位', { exact: true })).toHaveCount(0)
  // 一个一个置顶：后置顶的排在目录最上面
  for (const [i, name] of names.entries()) {
    await page.getByRole('button', { name, exact: true }).first().click()
    const id = await page.locator('section[data-entry]').filter({ has: page.getByText(name, { exact: true }) }).first().getAttribute('data-entry')
    const card = page.locator(`section[data-entry="${id}"]`)
    await card.hover()
    const pin = card.getByRole('button', { name: '置顶', exact: true })
    if (await pin.count()) await pin.click()
    await expect(card.getByRole('button', { name: '取消置顶', exact: true })).toBeVisible({ timeout: 30_000 })
    await card.hover()
    await shot(`${i + 1}-置顶「${name}」`)
  }
  void dir
  if (errors.length) console.log('页面报错：', errors)
} finally {
  await browser.close()
}
