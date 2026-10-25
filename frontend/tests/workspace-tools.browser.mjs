/** 第五步第三批（主编自己查、自己动手）：在真书上用真模型点一遍，截图放进 docs/新书页验收/第五步第三批/。
 *  先起好预览（.claude/launch.json 的 zhibi-step2，网页 4322）；在 frontend 下运行：
 *  node tests/workspace-tools.browser.mjs <书的 id> [edit,ask,card,delete,stop,again 里挑几个，逗号隔开]
 *  每一步发一句话，盯住编辑部回的那一条（data-testid=reply-…）等它做完再截图。真模型要等，一步一两分钟。 */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const [bookId, steps] = process.argv.slice(2)
if (!bookId) throw new Error('要给书的 id')
const wanted = new Set((steps ?? 'edit,ask,card,delete,stop,again').split(','))
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/第五步第三批')
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

/** 发一句话，返回编辑部回的那一条（盯住它，别按文字消失来判断做完没有） */
async function send(text) {
  const before = await page.locator('[data-testid^="reply-"]').count()
  const box = page.getByLabel('给编辑部发消息')
  await box.fill(text)
  await box.press('Enter')
  await expect(page.locator('[data-testid^="reply-"]')).toHaveCount(before + 1, { timeout: 30_000 })
  const id = await page.locator('[data-testid^="reply-"]').last().getAttribute('data-testid')
  return page.getByTestId(id)
}
const done = (reply, timeout = 400_000) => expect(reply).toHaveAttribute('data-state', /done|stopped|failed/, { timeout })

try {
  await page.goto(`${base}/desk/${bookId}`)
  await page.locator('button[title="编辑部"]').click()
  await expect(page.getByLabel('给编辑部发消息')).toBeVisible()

  if (wanted.has('edit')) {
    const reply = await send('沈九的外貌加一句：左手腕上常年缠着一圈褪了色的红绳，是义父给的')
    await expect(reply).toContainText(/在(查|改|看|新建|写|记|补)/, { timeout: 60_000 })
    await shot('1-一处直接改-干活时回答框里那一行')
    await done(reply)
    await page.locator('[data-testid^="outcome-"]').last().scrollIntoViewIfNeeded()
    await shot('2-一处直接改-改完的前后对照和回答')
  }

  if (wanted.has('ask')) {
    // 书小的时候设定都在资料里，不用查；问正文里的事才会查（换一本写过章的书，用 ASK 换一句）
    const reply = await send(process.env.ASK ?? '沈九听骨的代价有几条？分别会在什么时候用上？')
    await done(reply)
    const looked = reply.getByRole('button', { name: /查了：/ })
    if (await looked.count()) {
      await looked.click()
      // 点开的查到的原文放到聊天框底下看得见的地方
      await looked.evaluate((el) => el.scrollIntoView({ block: 'start' }))
    } else await reply.scrollIntoViewIfNeeded()
    await shot('3-只问不改-下面查了什么')
  }

  if (wanted.has('card')) {
    const reply = await send('第 1 篇里衙门那位仵作起个名字叫秦守拙，沈九的身世里提一句他小时候被秦守拙打过，简介结尾也带上秦守拙')
    await done(reply)
    const card = page.locator('[data-testid^="plan-"]').last()
    await card.scrollIntoViewIfNeeded()
    await shot('4-一次动三处-整理成方案卡')
    await card.getByRole('button', { name: '按这个来' }).click()
    await expect(card.getByText('已照办')).toBeVisible({ timeout: 600_000 })
    await card.locator('[data-testid^="outcome-"]').first().scrollIntoViewIfNeeded()
    await shot('5-按这个来-每一条都有前后对照')
  }

  if (wanted.has('delete')) {
    const reply = await send('秦守拙这张卡先删掉吧，我再想想')
    await done(reply)
    await page.locator('[data-testid^="plan-"]').last().scrollIntoViewIfNeeded()
    await shot('6-要删东西-先出方案卡')
  }

  if (wanted.has('stop')) {
    const reply = await send('沈九的性格再加一句：怕黑，夜里收尸要点三盏灯；然后年龄改成十九')
    await expect(reply).toContainText(/在改|在补/, { timeout: 120_000 })
    await page.getByRole('button', { name: '停下' }).click()
    await done(reply)
    await reply.scrollIntoViewIfNeeded()
    await shot('7-停下-正在改的那一处改完再停')
  }

  if (wanted.has('again')) {
    const reply = page.locator('[data-testid^="reply-"]').last()
    const before = new Set(await page.locator('[data-testid^="reply-"]').evaluateAll(els => els.map(el => el.dataset.testid)))
    await reply.getByRole('button', { name: '重新回答', exact: true }).click()
    const warn = reply.getByRole('alertdialog')
    if (await warn.isVisible().catch(() => false)) await warn.getByRole('button', { name: '重新回答', exact: true }).click()
    let id
    await expect(async () => {
      id = (await page.locator('[data-testid^="reply-"]').evaluateAll(els => els.map(el => el.dataset.testid))).findLast(one => !before.has(one))
      expect(id).toBeTruthy()
    }).toPass({ timeout: 30_000 })
    const resent = page.getByTestId(id)
    await done(resent)
    await resent.scrollIntoViewIfNeeded()
    await shot('8-重新回答-原话重发')
  }
  if (wanted.has('retry')) {
    // 先用别的办法让一句话做到一半断掉（比如做完第一处就重启后台），这里点「重试」接着做没做完的
    const reply = page.locator('[data-testid^="reply-"][data-state="failed"]').last()
    await reply.scrollIntoViewIfNeeded()
    await shot('9-中途断了-做完的留着')
    const id = await reply.getAttribute('data-testid')
    await reply.getByRole('button', { name: '重试' }).click()
    const again = page.getByTestId(id)
    await expect(again).toHaveAttribute('data-state', /thinking|streaming/, { timeout: 30_000 })
    await done(again)
    await again.scrollIntoViewIfNeeded()
    await shot('10-重试-接着做没做完的')
  }
  if (errors.length) console.log('页面报错：', errors)
} finally {
  await browser.close()
}
