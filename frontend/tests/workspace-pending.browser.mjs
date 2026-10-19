/** 第四步第二批「待处理」：在真书上点一遍，截图放进 docs/新书页验收/第四步第二批/。
 *  先起好预览（.claude/launch.json 的 zhibi-step2，网页 4322），书里要有几条待处理（改个名字会生出「别处还写着旧叫法」）。在 frontend 下运行：
 *  node tests/workspace-pending.browser.mjs <书的 id> [有改法那一条里的字] [只说了毛病那一条里的字] [挂在大纲上那一条里的字]
 *  「让编辑部改」那一步用真模型，要等一两分钟。 */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const [bookId, concreteText = '秦守拙', opinionText = '仵作还没名', outlineText = '雁回关义庄'] = process.argv.slice(2)
if (!bookId) throw new Error('要给书的 id')
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/第四步第二批')
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
  await page.goto(`${base}/desk/${bookId}`)
  const panel = page.getByRole('complementary', { name: '待处理' })
  const openPanel = async () => { if (!(await panel.isVisible().catch(() => false))) await page.getByRole('button', { name: /^待处理/ }).click() }
  await openPanel()
  await expect(panel).toBeVisible()
  await shot('1-待处理-右边一栏')

  const byId = async (locator) => page.getByTestId(await locator.getAttribute('data-testid'))
  // ONLY=opinion：只点「让编辑部改」那一步（前面几步点过一次，那几条已经处理了）
  if (process.env.ONLY !== 'opinion') {
  // 挂在大纲某一段上的：去看看，那一页最上面提醒一行；点「看看」回到待处理里那一条
    const onOutline = await byId(panel.locator('li', { hasText: outlineText }).filter({ has: page.getByRole('button', { name: '同意' }) }).first())
    await onOutline.scrollIntoViewIfNeeded()
    await onOutline.getByRole('button', { name: '去看看' }).click()
    await page.keyboard.press('Escape')
    const note = page.getByTestId('pending-note')
    await expect(note).toBeVisible({ timeout: 30_000 })
    await shot('2-那一页最上面提醒一行')
    await note.getByRole('button', { name: '看看' }).click()
    await expect(panel).toBeVisible()
    await shot('3-点看看-找到挂在这一页上的那一条')

    // 有具体改法的：同意以后当场摆出改前改后，能换回原来的
    await onOutline.getByRole('button', { name: '同意' }).click()
    await expect(onOutline).toContainText('同意了，改了', { timeout: 60_000 })
    await shot('4-同意以后-当场摆出改前改后')
    await onOutline.getByRole('button', { name: '换回原来的' }).click()
    await expect(onOutline).toContainText('已换回原来的', { timeout: 60_000 })
    await shot('5-换回原来的')
    void concreteText
  }

  // 只说了毛病的：让编辑部改，当成在聊天里说「照这条意见改」
  const opinion = await byId(panel.locator('li', { hasText: opinionText }).first())
  await opinion.scrollIntoViewIfNeeded()
  await opinion.getByRole('button', { name: '让编辑部改' }).click()
  await expect(opinion).toContainText('交给编辑部了', { timeout: 30_000 })
  await page.keyboard.press('Escape')
  await expect(panel).toHaveCount(0)
  // 盯住照这条意见说的那句话后面的那条回答
  const said = page.locator('[data-testid^="note-"]', { hasText: '照这条意见改' }).last()
  await expect(said).toBeVisible({ timeout: 30_000 })
  const noteId = Number((await said.getAttribute('data-testid')).slice(5))
  let replyId
  await expect(async () => {
    const ids = await page.locator('[data-testid^="reply-"]').evaluateAll((els) => els.map((el) => Number(el.dataset.testid.slice(6))))
    replyId = ids.find((id) => id > noteId)
    expect(replyId).toBeTruthy()
  }).toPass({ timeout: 60_000 })
  const reply = page.getByTestId(`reply-${replyId}`)
  await expect(reply).toHaveAttribute('data-state', /done|stopped|failed/, { timeout: 400_000 })
  await page.waitForTimeout(1500)
  await page.locator('[data-testid^="note-"]').last().scrollIntoViewIfNeeded()
  await shot('6-让编辑部改-聊天里照这条意见改')
  await reply.scrollIntoViewIfNeeded()
  await shot('7-让编辑部改-编辑部的回答')
  if (errors.length) console.log('页面报错：', errors)
} finally {
  await browser.close()
}
