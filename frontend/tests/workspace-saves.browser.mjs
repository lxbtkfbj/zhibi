/** 第五步第二批（存档）：在真书上点一遍，截图放进 docs/新书页验收/第五步第二批/。
 *  先起好预览（.claude/launch.json 的 zhibi-step2，网页 4322），预览库里的书已经用真模型聊过；在 frontend 下运行：
 *  node tests/workspace-saves.browser.mjs <书的 id> [要回到的那一档的名字]
 *  聊天里最后一处改动：截前后对照，点「再改一版」「换回原来的」；再开存档栏存一档、点开一档；给了档名就回到那一档。 */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const [bookId, restoreTo, only] = process.argv.slice(2)
if (!bookId) throw new Error('要给书的 id')
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/第五步第二批')
await fs.mkdir(output, { recursive: true })

const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || undefined })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))

const shot = async (name) => {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(output, `${name}.jpg`), quality: 88 })
  console.log(name)
}
const savesPanel = page.getByRole('complementary', { name: '存档' })

try {
  await page.goto(`${base}/desk/${bookId}`)
  if (!only || only === 'chat') {
    await page.locator('button[title="编辑部"]').click()
    const last = page.locator('[data-testid^="outcome-"]').filter({ hasText: '换回原来的' }).last()
    await expect(last).toBeVisible({ timeout: 20_000 })
    await last.scrollIntoViewIfNeeded()
    await shot('1-聊天里改一处-当场看前后对照')

    // 再改一版：照同一句话重改，前后对照换成新的（真模型，要等一会儿）；盯住同一条消息
    const again = page.getByTestId(await last.getAttribute('data-testid'))
    await last.getByRole('button', { name: '再改一版' }).click()
    await expect(again).toContainText(/在重新改|在改/, { timeout: 20_000 })
    await shot('2-再改一版-正在重改')
    await expect(again.getByRole('button', { name: '换回原来的' })).toBeVisible({ timeout: 300_000 })
    await again.scrollIntoViewIfNeeded()
    await shot('3-再改一版-换成新的对照')

    // 换回原来的：这一处换回改之前
    await again.getByRole('button', { name: '换回原来的' }).click()
    await expect(page.getByText(/已换回原来的/).last()).toBeVisible({ timeout: 30_000 })
    await shot('4-换回原来的')
    await page.reload()
  }

  if (!only || only === 'saves') {
    // 存档栏：手动存一档（带书签），自动存的连着几条折成一行
    await page.getByRole('button', { name: '存档', exact: true }).click()
    await expect(savesPanel).toBeVisible()
    await expect(savesPanel.locator('section').first()).toBeVisible()
    await savesPanel.getByPlaceholder(/起个名字/).fill('沈九定稿')
    await savesPanel.getByRole('button', { name: '存一档' }).click()
    await expect(savesPanel.getByText('沈九定稿')).toBeVisible()
    const fold = savesPanel.locator('button', { hasText: /起 \d+ 档/ }).first()
    if (await fold.count()) await fold.click()
    await shot('5-存档栏-手动存的和自动存的')

    // 点开一档：和现在比改了哪些，展开看「那时」「现在」
    for (const fold of await savesPanel.locator('button', { hasText: /起 \d+ 档/ }).all()) await fold.click()
    await savesPanel.getByRole('button', { name: /沈九/ }).filter({ hasText: /设定师照你的话/ }).last().click()
    await expect(savesPanel.getByText(/这一档和现在比|一模一样/)).toBeVisible({ timeout: 20_000 })
    const item = savesPanel.locator('section button').first()
    if (await item.count()) await item.click()
    await shot('6-点开一档-和现在比')
    await savesPanel.getByRole('button', { name: '所有存档' }).click()
  }

  if (only === 'list') {
    // 写过章的书：存档栏里写完第几章、回到某一档的那几条
    await page.getByRole('button', { name: '存档', exact: true }).click()
    await expect(savesPanel.locator('section').first()).toBeVisible()
    for (const fold of await savesPanel.locator('button', { hasText: /起 \d+ 档/ }).all()) await fold.click()
    await shot('5b-存档栏-写过章的书')
  }

  if (restoreTo && (!only || only === 'restore')) {
    // 回到一档：确认框说清会换回几处、正文退到第几章
    if (!(await savesPanel.isVisible())) await page.getByRole('button', { name: '存档', exact: true }).click()
    await expect(savesPanel.getByText('正在读存档…')).toHaveCount(0)
    await expect(savesPanel.locator('section').first()).toBeVisible()
    // 自动存的折在一行里：先展开
    for (const fold of await savesPanel.locator('button', { hasText: /起 \d+ 档/ }).all()) await fold.click()
    await savesPanel.getByRole('button', { name: new RegExp(restoreTo) }).last().click()
    await savesPanel.getByRole('button', { name: '回到这一档' }).click()
    await shot('7-回到一档-确认框')
    await savesPanel.getByRole('button', { name: '回到这一档' }).last().click()
    await expect(savesPanel.getByText('书已经换回这一档了')).toBeVisible({ timeout: 30_000 })
    await shot('8-回到一档以后')
    await page.keyboard.press('Escape')
    // 正文跟着退回去
    const manuscript = page.getByRole('navigation').getByRole('button', { name: '正文' })
    if (await manuscript.count()) {
      await manuscript.click()
      await shot('8b-回到一档以后-正文')
    }
    await page.locator('button[title="编辑部"]').click()
    await expect(page.getByText(/你把书换回了存档/).last()).toBeVisible({ timeout: 20_000 })
    await page.getByText(/你把书换回了存档/).last().scrollIntoViewIfNeeded()
    await shot('9-回去以后聊天里的那一行')
  }
  if (errors.length) console.log('页面报错：', errors)
} finally {
  await browser.close()
}
