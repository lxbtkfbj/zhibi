/** 本书设置精简（2026-10-19）：书页上居中的弹窗、背景糊掉，只剩写正文、写作要求、编辑部写得多仔细；
 *  开写页「一章重写几次」跟着档位走；全局「新书默认」也跟着精简。截图放进 docs/新书页验收/本书设置/。
 *  先起好预览（网页 4321＋后台 8001，库 zhibi_preview）；在 frontend 下运行（会在那本书里加一条写作要求、试完删掉）：
 *  node tests/workspace-settings.browser.mjs <书的 id> */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4321'
const [bookId] = process.argv.slice(2)
if (!bookId) throw new Error('要给书的 id')
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/本书设置')
await fs.mkdir(output, { recursive: true })

const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || undefined })
// 和作者截图的屏幕一样宽：2000 宽时书页放大 1.1 倍，弹窗跟着放大
const page = await browser.newPage({ viewport: { width: 2000, height: 1025 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
const shot = async (file) => {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(600)
  await page.screenshot({ path: path.join(output, `${file}.jpg`), quality: 88 })
  console.log(file)
}
const api = (p) => `${base}/api${p}`
const before = (await (await page.request.get(api(`/books/${bookId}/settings`))).json()).settings
const added = '别写「嘴角勾起一抹弧度」这种套话'

const dialog = page.getByRole('dialog', { name: '本书设置' })
const open = async () => {
  await page.getByRole('button', { name: '本书设置', exact: true }).click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('编辑部以后排大纲、写正文都照着做', { exact: false }).or(dialog.getByText('还没有。', { exact: false }))).toBeVisible({ timeout: 15_000 })
}
const scrollDialog = (to) => dialog.locator('.overflow-y-auto').evaluate((el, y) => { el.scrollTop = y === 'end' ? el.scrollHeight : y }, to)

try {
  // 亲密戏存着自己写的话、选的却是点到为止：那一行下面说一声
  await page.request.patch(api(`/books/${bookId}/settings`), { data: { intimacy: 'fade', intimacy_custom: '详细描写床戏' } })
  await page.goto(`${base}/desk/${bookId}`)
  await expect(page.getByRole('button', { name: '本书设置', exact: true })).toBeVisible({ timeout: 30_000 })
  await open()
  await expect(dialog.getByText('你写过「详细描写床戏」，选「自己写」才按这句来。')).toBeVisible()
  await shot('1-打开本书设置')

  // 加一条写作要求，点了能改
  await dialog.getByRole('button', { name: '加一条', exact: true }).click()
  await dialog.getByRole('textbox', { name: '新的写作要求' }).fill(added)
  await dialog.getByRole('button', { name: '记下', exact: true }).click()
  const row = dialog.getByRole('button', { name: new RegExp(`^${added}`) })
  await expect(row).toBeVisible({ timeout: 15_000 })
  await scrollDialog('end')
  await shot('2-翻到底：写作要求和编辑部写得多仔细')
  await row.click()
  await expect(dialog.getByRole('textbox', { name: '改这条写作要求' })).toBeVisible()
  await shot('3-点一条就能改字、改范围、删掉')
  // Esc 先收起正在改的那一条，弹窗不关
  await page.keyboard.press('Escape')
  await expect(dialog.getByRole('textbox', { name: '改这条写作要求' })).toHaveCount(0)
  await expect(dialog).toBeVisible()

  // 换成省时：说明当场跟着变；开写页那句跟着说「重写一次」
  await dialog.getByRole('button', { name: '省时', exact: true }).click()
  await expect(dialog.getByText('最多重写 1 次', { exact: false })).toBeVisible()
  await shot('4-换成省时')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: '正文', exact: true }).first().click()
  const stuck = page.getByText('一章重写一次还过不了审稿，总会停下来请你定。')
  await expect(stuck).toBeVisible({ timeout: 15_000 })
  await stuck.scrollIntoViewIfNeeded()
  await shot('5-开写页：省时就说重写一次')

  // 小一点的屏幕
  await page.setViewportSize({ width: 1366, height: 768 })
  await open()
  await shot('6-1366 宽的屏幕')
  await page.setViewportSize({ width: 2000, height: 1025 })

  // 暗色
  await page.keyboard.press('Escape')
  await page.evaluate(() => {
    const key = 'zhibi:appearance'
    const saved = JSON.parse(localStorage.getItem(key) || '{}')
    localStorage.setItem('zhibi:appearance:before-test', JSON.stringify(saved))
    localStorage.setItem(key, JSON.stringify({ ...saved, theme: 'ink' }))
  })
  await page.reload()
  await expect(page.getByRole('button', { name: '本书设置', exact: true })).toBeVisible({ timeout: 30_000 })
  await open()
  await shot('7-暗色')
  await page.evaluate(() => localStorage.setItem('zhibi:appearance', localStorage.getItem('zhibi:appearance:before-test') || '{}'))
  await page.reload()

  // 全局设置「新书默认」：只剩起书名、写正文、编辑部写得多仔细
  await page.goto(`${base}/`)
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('tab', { name: '新书默认' }).click()
  await expect(page.getByText('只管之后新开的书', { exact: false })).toBeVisible()
  await shot('8-全局设置的新书默认')

  if (errors.length) console.log('页面报错：', errors)
} finally {
  // 试完收拾：删掉加的那一条，设置换回原来的
  const rows = await (await page.request.get(api(`/books/${bookId}/requirements`))).json()
  for (const r of rows.filter((r) => r.text === added)) await page.request.delete(api(`/requirements/${r.id}`))
  const { intimacy, intimacy_custom, effort_preset } = before
  await page.request.patch(api(`/books/${bookId}/settings`), { data: { intimacy, intimacy_custom, effort_preset } })
  await browser.close()
}
