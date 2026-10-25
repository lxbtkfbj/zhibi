/** 第五步第四批（新对话、从这里重来、编辑部的进度压成一行）：在真书上用真模型点一遍，截图放进 docs/新书页验收/第五步第四批/。
 *  先起好预览（.claude/launch.json 的 zhibi-step2，网页 4322）；在 frontend 下运行：
 *  node tests/workspace-convs.browser.mjs <书的 id> [lines,new,ask,list,old,rewind,live 里挑几个，逗号隔开]
 *  lines 看写过章的书（编辑部干活的消息多）；live 要先另起 worker，会让编辑部真写一章。 */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const api = process.env.TEST_API_URL ?? 'http://127.0.0.1:8003/api'
const [bookId, steps] = process.argv.slice(2)
if (!bookId) throw new Error('要给书的 id')
const wanted = new Set((steps ?? 'new,ask,list,old,rewind').split(','))
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/第五步第四批')
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
  // 从这里重来时旧的回答会收起来，条数不一定变多：等一条没见过的回答
  const before = new Set(await page.locator('[data-testid^="reply-"]').evaluateAll((els) => els.map((el) => el.dataset.testid)))
  const box = page.getByLabel('给编辑部发消息')
  await box.fill(text)
  await box.press('Enter')
  let id
  await expect(async () => {
    const ids = await page.locator('[data-testid^="reply-"]').evaluateAll((els) => els.map((el) => el.dataset.testid))
    id = ids.findLast((one) => !before.has(one))
    expect(id).toBeTruthy()
  }).toPass({ timeout: 30_000 })
  return page.getByTestId(id)
}
const done = (reply, timeout = 400_000) => expect(reply).toHaveAttribute('data-state', /done|stopped|failed/, { timeout })

try {
  await page.goto(`${base}/desk/${bookId}`)
  await page.locator('button[title="编辑部"]').click()
  await expect(page.getByLabel('给编辑部发消息')).toBeVisible()

  if (wanted.has('lines')) {
    // 写过章的书：编辑部干活的进度不再一步一条，做完的一行小字带「去看」
    await page.getByRole('button', { name: '去看' }).last().scrollIntoViewIfNeeded()
    await shot('1-进度压成一行-做完的一行小字带去看')
  }

  if (wanted.has('new')) {
    await page.getByRole('button', { name: '新对话' }).click()
    const remind = page.getByRole('dialog', { name: '开新对话前' })
    if (await remind.isVisible().catch(() => false)) {
      await shot('2-开新对话前-还没落实的先提醒总结一下')
      await remind.getByRole('button', { name: '直接开新的' }).click()
    }
    await expect(page.getByText('跟编辑部说点什么')).toBeVisible()
    await shot('3-新对话-空的一段')
  }

  if (wanted.has('ask')) {
    const reply = await send(process.env.ASK ?? '沈九的外貌加一句：左手腕上常年缠着一圈褪了色的红绳，是义父给的')
    await done(reply)
    await reply.scrollIntoViewIfNeeded()
    await shot('4-新对话里说一句-只带这一段')
  }

  if (wanted.has('list')) {
    await page.getByRole('button', { name: '以前的对话' }).click()
    await expect(page.getByRole('listbox', { name: '以前的对话' })).toBeVisible()
    await shot('5-以前的对话-按第一句话起名带日期')
  }

  if (wanted.has('old')) {
    const list = page.getByRole('listbox', { name: '以前的对话' })
    if (!(await list.isVisible().catch(() => false))) await page.getByRole('button', { name: '以前的对话' }).click()
    await list.getByRole('option').nth(1).click()
    await expect(page.getByRole('button', { name: '回到最近的' })).toBeVisible()
    await shot('6-点开以前的一段-接着说就在这一段里聊')
    await page.getByRole('button', { name: '回到最近的' }).click()
  }

  if (wanted.has('rewind')) {
    // 先说一句会改书的，再从这句重来：先提醒书不跟着退
    await done(await send(process.env.CHANGE ?? '柳三爷的外貌加一句：右耳缺了半块，是年轻时被人咬掉的'))
    const note = page.locator('[data-testid^="note-"]').last()
    await note.scrollIntoViewIfNeeded()
    await note.hover()
    await note.getByRole('button', { name: '修改', exact: true }).click()
    const warn = note.getByRole('alertdialog')
    if (await warn.isVisible().catch(() => false)) {
      await shot('7-修改-改过书的先提醒书不跟着退')
      await warn.getByRole('button', { name: '接着改', exact: true }).click()
    }
    const edit = note.getByRole('textbox')
    await expect(edit).toBeVisible()
    await expect(page.getByLabel('给编辑部发消息')).toHaveValue('')
    await expect(note.getByText('改好了点发送，不改直接发就是原话重来：这句和后面的聊天会收起来，从这句重新回答；书里改过的不跟着退', { exact: true })).toBeVisible()
    await shot('8-修改-那句话在气泡里编辑')
    const before = new Set(await page.locator('[data-testid^="reply-"]').evaluateAll(els => els.map(el => el.dataset.testid)))
    await edit.fill(process.env.REWIND ?? '柳三爷的右耳是怎么回事？')
    await edit.press('Enter')
    let id
    await expect(async () => {
      id = (await page.locator('[data-testid^="reply-"]').evaluateAll(els => els.map(el => el.dataset.testid))).findLast(one => !before.has(one))
      expect(id).toBeTruthy()
    }).toPass({ timeout: 30_000 })
    const reply = page.getByTestId(id)
    await done(reply)
    await reply.scrollIntoViewIfNeeded()
    await shot('9-重来以后-后面的聊天收起来了')
  }

  if (wanted.has('remind')) {
    // 这一段聊了几句只是商量、没改书的：开新对话前先提醒「总结一下」
    for (const text of ['我在想第二篇要不要让柳三爷提前露面，你先别改，我再想想', '还有秦守拙，我想让他后面变成沈九的师父，也先别动']) await done(await send(text))
    await page.getByRole('button', { name: '新对话' }).click()
    await expect(page.getByRole('dialog', { name: '开新对话前' })).toBeVisible()
    await shot('2-开新对话前-还没落实的先提醒总结一下')
    await page.getByRole('button', { name: '先总结一下' }).click()
    await expect(page.locator('[data-testid^="plan-"]').last()).toBeVisible({ timeout: 300_000 })
    await page.locator('[data-testid^="plan-"]').last().scrollIntoViewIfNeeded()
    await shot('2b-先总结一下-出了方案卡')
  }

  if (wanted.has('live')) {
    // 让编辑部真写：最底下一行跟着进度变；停下来等拍板时那一行变成「……等你看 · 去看」（截了图就替作者点「就这样」）；
    // 写完一章，那一章是一行小字带「去看」
    const now = page.getByTestId('work-now')
    if (!(await now.isVisible().catch(() => false))) {
      const res = await fetch(`${api}/books/${bookId}/write`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ until: 'count', count: 1 }) })
      if (!res.ok) throw new Error(`开写没成：${res.status} ${await res.text()}`)
    }
    const finals = async () => page.getByText(/定稿，\d+ 字/).count()
    const before = await finals()
    const shots = new Set()
    const started = Date.now()
    while (Date.now() - started < 1_500_000) {
      const text = (await now.textContent().catch(() => '')) ?? ''
      if (/已用 \d+ (秒|分钟)/.test(text) && !shots.has('run') && /已用 ([1-9]\d|\d+ 分钟)/.test(text)) {
        await now.scrollIntoViewIfNeeded()
        await shot('10-编辑部在干活-最底下一行跟着变')
        shots.add('run')
      }
      if (text.includes('等你看')) {
        if (!shots.has('wait')) {
          await now.scrollIntoViewIfNeeded()
          await shot('11-等你拍板-聊天里一行等你看')
          shots.add('wait')
        }
        await now.getByRole('button', { name: '去看' }).click()
        await page.getByRole('button', { name: /^(就这样|读完了|就用这一版)/ }).first().click()
        await page.waitForTimeout(3000)
      }
      if ((await finals()) > before) break
      await page.waitForTimeout(1000)
    }
    await page.getByText(/定稿，\d+ 字/).last().scrollIntoViewIfNeeded()
    await shot('12-写完一章-一行小字带去看')
  }

  if (errors.length) console.log('页面报错：', errors)
} finally {
  await browser.close()
}
