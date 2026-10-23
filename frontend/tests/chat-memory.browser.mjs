/** Task 3: real isolated demo tools/API and mouse/keyboard; no response stubs. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '../..')
const OUT = path.join(ROOT, 'data/chat-improvements-task3')
const BASE = 'http://127.0.0.1:4387'
const fixture = JSON.parse(await fs.readFile(path.join(OUT, 'fixture.json'), 'utf8'))
const report = { checks: [], errors: [], externalRequests: [], requests: [], screenshots: [], demoOnly: true }
const expect = baseExpect.configure({ timeout: 15000 })
const browser = await chromium.launch({ executablePath: ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync) })
const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
await context.route('**/*', route => {
  const url = new URL(route.request().url())
  if (['http:', 'https:'].includes(url.protocol) && url.origin !== BASE) { report.externalRequests.push(url.href); return route.abort() }
  return route.continue()
})
const page = await context.newPage()
page.on('pageerror', error => report.errors.push(error.message))
page.on('request', request => { if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) report.requests.push({ method: request.method(), url: request.url(), body: request.postDataJSON() }) })
const pass = name => { report.checks.push(name); console.log(`PASS ${name}`) }
const composer = () => page.getByLabel('给编辑部发消息', { exact: true })
const panel = () => page.locator('[data-testid="editorial-floating"], [data-testid="editorial-docked"]')
const memories = () => panel().getByRole('region', { name: '记忆', exact: true })
const get = async suffix => { const r = await context.request.get(`${BASE}/api${suffix}`); assert.equal(r.status(), 200, suffix); return r.json() }
const rows = id => get(`/books/${id}/memories`)
const meeting = id => get(`/books/${id}/meeting?limit=2000`)
async function type(input, text) { await input.click(); await input.press('ControlOrMeta+A'); await page.keyboard.insertText(text) }
async function open(id) {
  await page.goto(`${BASE}/desk/${id}`)
  const ball = page.locator('[role="button"][title="编辑部"]')
  await expect(ball.or(composer())).toBeVisible()
  if (await ball.isVisible()) await ball.click()
  await expect(composer()).toBeVisible()
}
async function send(id, text) {
  await type(composer(), text)
  const response = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === `/api/books/${id}/notes`)
  await composer().press('Enter')
  const result = await response; assert.equal(result.status(), 201, await result.text())
  const note = await result.json()
  await expect.poll(async () => (await meeting(id)).find(row => row.payload?.reply_to?.includes(note.id))?.payload?.state ?? 'done', { timeout: 90000 }).toBe('done')
  await expect.poll(async () => (await meeting(id)).some(row => row.payload?.reply_to?.includes(note.id) && !!row.content), { timeout: 90000 }).toBe(true)
  const reply = (await meeting(id)).find(row => row.payload?.reply_to?.includes(note.id))
  const box = page.getByTestId(`reply-${reply.id}`)
  await expect(box).toBeVisible()
  await expect(box).toHaveAttribute('data-state', 'done', { timeout: 90000 })
  return { note, reply, box }
}
function notice(result) { return result.box.locator('[data-testid^="memory-notice-"]') }
async function back() { await memories().getByRole('button', { name: '回到聊天', exact: true }).click(); await expect(composer()).toBeVisible() }
async function shot(name) {
  await page.evaluate(async () => { await document.fonts.ready; await Promise.allSettled(document.getAnimations().filter(animation => Number.isFinite(animation.effect?.getComputedTiming().endTime)).map(animation => animation.finished)) })
  await page.screenshot({ path: path.join(ROOT, 'docs/聊天改进验收', name) }); report.screenshots.push(name)
}
try {
  const bid = fixture.new_book_id
  await open(bid)
  const first = await send(bid, '记住，以后每章结尾都留个钩子')
  const firstReceipt = first.reply.payload.memories[0].memory
  await expect(notice(first).getByRole('button', { name: `记住了：${firstReceipt.summary}`, exact: true })).toBeVisible()
  assert.equal(first.note.payload.turn, 'tools')
  assert.ok(!first.note.payload.steps?.length)
  await notice(first).getByRole('button', { name: `记住了：${firstReceipt.summary}`, exact: true }).click()
  await expect(memories().getByTestId(`memory-${firstReceipt.id}`)).toHaveClass(/bg-chief-soft/u)
  await back()
  await notice(first).getByRole('button', { name: '撤销', exact: true }).click()
  await expect(notice(first).getByRole('button', { name: `没记：${firstReceipt.summary}`, exact: true })).toBeVisible()
  await expect.poll(async () => (await rows(bid)).some(row => row.id === firstReceipt.id)).toBe(false)
  pass('remember 真工具回执在回答下，点字跳记忆并高亮；撤销变没记，作者步骤不重复回执')

  const second = await send(bid, '你记得我说过什么吗？记住，以后每章结尾都留个钩子')
  const original = second.reply.payload.memories[0].memory
  assert.notEqual(original.id, firstReceipt.id)
  await expect(second.box.getByRole('button', { name: /查了：记忆「/u })).toBeVisible()
  const bounds = await second.box.evaluate(el => ({ query: [...el.querySelectorAll('button')].find(node => node.textContent.startsWith('查了：')).getBoundingClientRect().top, receipt: el.querySelector('[data-testid^="memory-notice-"]').getBoundingClientRect().top }))
  assert.ok(bounds.receipt > bounds.query)
  await second.box.getByRole('button', { name: /查了：记忆「/u }).click()
  await expect(second.box.getByText(second.reply.payload.tools[0].text, { exact: true })).toBeVisible()
  await second.box.getByRole('button', { name: /查了：记忆「/u }).click()
  await shot('任务3-01-查了和记住了.png')
  pass('read_memory 查了每条简述，点开原样模型资料；查了在上、记忆行在下，删除号不重用')

  const before = (await rows(bid)).find(row => row.id === original.id)
  const changed = await send(bid, `把记${original.id}改成我喜欢先给两个选项`)
  await expect(notice(changed).getByRole('button', { name: '改了一条记忆：我喜欢先给两个选项', exact: true })).toBeVisible()
  await notice(changed).getByRole('button', { name: '改了一条记忆：我喜欢先给两个选项', exact: true }).click()
  await expect(memories().getByRole('tab', { name: '全局', exact: true })).toHaveAttribute('aria-selected', 'true')
  await back()
  await notice(changed).getByRole('button', { name: '撤销', exact: true }).click()
  await expect(notice(changed).getByRole('button', { name: `换回了原来的：${original.summary}`, exact: true })).toBeVisible()
  await expect.poll(async () => (await rows(bid)).find(row => row.id === original.id)?.summary).toBe(before.summary)
  const restored = (await rows(bid)).find(row => row.id === original.id)
  for (const key of ['id', 'book_id', 'summary', 'detail', 'kind', 'scope', 'chapter_index', 'volume_index', 'source']) assert.deepEqual(restored[key], before[key], key)
  await shot('任务3-02-换回原来的.png')
  pass('remember 带编号改库和种类，跳全局；撤销换回完整旧值和原简述，编号不变')

  const forgotten = await send(bid, `记${original.id}这条不用记了`)
  await expect(notice(forgotten).getByText(`忘掉了：${original.summary}`, { exact: true })).toBeVisible()
  await expect(notice(forgotten).getByRole('button', { name: `忘掉了：${original.summary}`, exact: true })).toHaveCount(0)
  await expect(notice(forgotten).getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
  await expect.poll(async () => (await rows(bid)).some(row => row.id === original.id)).toBe(false)
  await shot('任务3-03-忘掉了.png')
  await notice(forgotten).getByRole('button', { name: '撤销', exact: true }).click()
  await expect(notice(forgotten).getByText(`找回来了：${original.summary}`, { exact: true })).toBeVisible()
  await expect.poll(async () => (await rows(bid)).some(row => row.id === original.id)).toBe(true)
  pass('forget 忘掉行不跳转，自己的软删可撤销，找回原编号')

  const newConversation = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === `/api/books/${bid}/chat/conversations`)
  await panel().getByRole('button', { name: '新对话', exact: true }).click()
  assert.equal((await newConversation).status(), 201)
  await expect(forgotten.box).toHaveCount(0)
  const recalled = await send(bid, '你记得我说过什么吗？')
  assert.ok(recalled.reply.content.includes(`详细：${before.detail}`))
  await expect(recalled.box.getByText(recalled.reply.content, { exact: true })).toBeVisible()
  assert.equal(recalled.note.payload.ask_only, true)
  pass('点新对话后，read_memory 真翻到上一段记忆并用详细内容回答')

  const asked = await send(bid, '我喜欢传统爽文，你觉得这本书适合吗？')
  assert.equal(asked.note.payload.ask_only, true)
  await expect(notice(asked)).toContainText('记住了：')
  const oldReceipt = asked.reply.payload.memories[0].memory
  await asked.box.getByRole('button', { name: '重新回答', exact: true }).click()
  await expect.poll(async () => (await meeting(bid)).find(row => row.id === asked.reply.id)?.payload?.memories?.[0]?.memory?.version, { timeout: 90000 }).toBeGreaterThan(oldReceipt.version)
  await expect(asked.box).toHaveAttribute('data-state', 'done', { timeout: 90000 })
  const newReceipt = (await meeting(bid)).find(row => row.id === asked.reply.id).payload.memories
  assert.equal(newReceipt.length, 1); assert.equal(newReceipt[0].memory.id, oldReceipt.id)
  assert.equal(newReceipt[0].memory.action, 'update')
  await expect(notice(asked)).toContainText('改了一条记忆：')
  pass('只查只答也能记；重新回答不回退记忆，旧行换掉，新答照目录改同一条')

  // Later changes disable old receipts, without using a mocked server response.
  await panel().getByRole('button', { name: '记忆', exact: true }).click()
  await memories().getByRole('tab', { name: '全局', exact: true }).click()
  const row = memories().getByTestId(`memory-${newReceipt[0].memory.id}`)
  await row.getByRole('button').first().click(); await row.getByRole('button', { name: '改', exact: true }).click()
  await type(memories().getByRole('form', { name: '编辑记忆' }).getByLabel('简述', { exact: true }), '后来手动改的简述')
  await memories().getByRole('form', { name: '编辑记忆' }).getByRole('button', { name: '保存', exact: true }).click()
  await expect(memories().getByRole('form', { name: '编辑记忆' })).toHaveCount(0); await back()
  await expect(notice(asked).getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
  await expect(notice(asked).locator('span[title]')).toHaveAttribute('title', '这条后来又改过，去「记忆」里改')
  pass('记忆页后改使旧回执撤销变灰，提示逐字一致')
  await panel().getByRole('button', { name: '记忆', exact: true }).click()
  await memories().getByRole('tab', { name: '全局', exact: true }).click()
  const laterRow = memories().getByTestId(`memory-${newReceipt[0].memory.id}`)
  await laterRow.getByRole('button').first().click()
  await laterRow.getByRole('button', { name: '删', exact: true }).click()
  await back()
  await expect(notice(asked).getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
  await expect(notice(asked).locator('span[title]')).toHaveAttribute('title', '这条后来删掉了')
  pass('记忆页后删使旧回执撤销变灰，删除提示逐字一致')

  await send(bid, '记住，以后都用短句')
  const beforeRewind = await rows(bid)
  const author = page.getByTestId(`note-${asked.note.id}`)
  await author.hover(); await author.getByRole('button', { name: '修改', exact: true }).click()
  await expect(panel().getByRole('alertdialog')).toHaveCount(0)
  const inline = panel().getByLabel('修改这句话', { exact: true })
  await type(inline, '这本书适合什么读者？')
  const rewindResponse = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === `/api/books/${bid}/notes`)
  await inline.press('Enter')
  const rewindResult = await rewindResponse; assert.equal(rewindResult.status(), 201)
  const rewindNote = await rewindResult.json()
  await expect.poll(async () => (await meeting(bid)).some(row => row.payload?.reply_to?.includes(rewindNote.id) && !!row.content), { timeout: 90000 }).toBe(true)
  assert.deepEqual(await rows(bid), beforeRewind)
  assert.equal((await get(`/books/${bid}/saves`)).items.length, 1)
  assert.deepEqual(await get(`/books/${bid}/note-changes`), {})
  pass('工具记忆不数改书处数，修改退回聊天后新记和已删状态都不退，纯记忆不添自动存档')


  for (const label of ['working', 'waiting']) {
    const id = fixture[`${label}_book_id`]
    await open(id)
    const result = await send(id, '记住，以后每章结尾都留个钩子')
    await expect(notice(result)).toContainText('记住了：')
    if (label === 'working') await expect(notice(result)).toContainText('正在写的从下一步起照办')
    else assert.equal(result.note.payload.ask_only, true)
    await notice(result).getByRole('button', { name: '撤销', exact: true }).click()
    await expect(notice(result)).toContainText('没记：')
  }
  pass('合成运行中和等拍板两种状态都能记/撤销，不进待处理')
  await open(fixture.teardown_book_id)
  const teardown = await send(fixture.teardown_book_id, '记住，以后每章结尾都留个钩子')
  await expect(notice(teardown)).toHaveCount(0)
  await expect(panel().getByRole('button', { name: '记忆', exact: true })).toHaveCount(0)
  assert.ok(!teardown.reply.payload.memories?.length)
  pass('拆的书没有三个工具的记忆结果，也没有记忆页按钮')
  assert.deepEqual(report.errors, []); assert.deepEqual(report.externalRequests, [])
} finally {
  await fs.writeFile(path.join(OUT, 'browser-results.json'), JSON.stringify(report, null, 2))
  await context.close(); await browser.close()
}
