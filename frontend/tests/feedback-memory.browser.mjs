/** Task 4: real isolated demo API/worker; every mutation uses mouse/keyboard, no response stubs. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '../..')
const OUT = path.resolve(process.env.ZHIBI_FEEDBACK_OUT || path.join(ROOT, 'data/chat-improvements-task4'))
const BASE = process.env.ZHIBI_FEEDBACK_BASE || 'http://127.0.0.1:4389'
const baseURL = new URL(BASE)
assert.equal(baseURL.hostname, '127.0.0.1', '只允许独立本机演示环境')
assert.ok(baseURL.port && !['8000', '4320', '5433', '6380'].includes(baseURL.port), '不能操作日常端口')
const fixture = JSON.parse(await fs.readFile(process.env.ZHIBI_FEEDBACK_FIXTURE || path.join(OUT, 'fixture.json'), 'utf8'))
assert.equal(fixture.demo_only, true)
assert.deepEqual(fixture.feedback_seed, { actual_graph: true, model_calls: 0, source: 'synthetic' })
await fs.mkdir(OUT, { recursive: true })
const report = { checks: [], errors: [], externalRequests: [], requests: [], screenshots: [], demoOnly: true }
const expect = baseExpect.configure({ timeout: 20000 })
const browser = await chromium.launch({ executablePath: process.env.ZHIBI_CHROMIUM || ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync) })
const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
await context.route('**/*', route => {
  const url = new URL(route.request().url())
  if (['http:', 'https:'].includes(url.protocol) && url.origin !== BASE) { report.externalRequests.push(url.href); return route.abort() }
  return route.continue()
})
const page = await context.newPage()
page.on('pageerror', error => report.errors.push(error.message))
page.on('request', request => {
  if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) report.requests.push({ method: request.method(), url: request.url(), body: request.postDataJSON() })
})
const pass = name => { report.checks.push(name); console.log(`PASS ${name}`) }
const get = async suffix => { const response = await context.request.get(`${BASE}/api${suffix}`); assert.equal(response.status(), 200, suffix); return response.json() }
const meeting = id => get(`/books/${id}/meeting?limit=2000`)
const memories = id => get(`/books/${id}/memories`)
const panel = () => page.locator('[data-testid="editorial-floating"], [data-testid="editorial-docked"]')
const composer = () => page.getByLabel('给编辑部发消息', { exact: true })
async function type(input, text) { await input.click(); await input.press('ControlOrMeta+A'); await page.keyboard.insertText(text) }
async function openChat() {
  if (await composer().isVisible()) return
  await page.locator('[role="button"][title="编辑部"]').click()
  await expect(composer()).toBeVisible()
}
async function openGate(id, label) {
  await page.goto(`${BASE}/desk/${id}`)
  await page.locator('header nav a').filter({ hasText: /^正文$/u }).click()
  const waiting = page.locator('main .state').filter({ hasText: '编辑部在等你拍板' })
  await expect(waiting).toContainText(label)
  await waiting.getByText('去看看', { exact: true }).click()
}
async function shot(name) {
  await page.evaluate(async () => { await document.fonts.ready; await Promise.allSettled(document.getAnimations().filter(animation => Number.isFinite(animation.effect?.getComputedTiming().endTime)).map(animation => animation.finished)) })
  await page.screenshot({ path: path.join(ROOT, 'docs/聊天改进验收', name) })
  report.screenshots.push(name)
}
async function submit(id, jobId, text, trial = false) {
  if (await panel().isVisible()) await panel().getByRole('button', { name: '收起', exact: true }).click()
  const previous = await meeting(id), after = previous.at(-1)?.id ?? 0
  await page.getByRole('button', { name: trial ? '说说哪里不对' : '让主编改', exact: true }).click()
  const input = page.getByPlaceholder(trial ? '比如：对话太多，节奏再快一点；主角说话再狠一些。说了以后，之后每一章都照这个写' : '比如：单元三放宽到 5 章；讲经堂加一个能说话的女弟子', { exact: true })
  await type(input, text)
  const [response] = await Promise.all([
    page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/jobs/${jobId}/decision`),
    page.getByRole('button', { name: trial ? '交给编辑部' : '交给主编', exact: true }).click(),
  ])
  assert.equal(response.status(), 200, await response.text())
  if (trial) {
    await expect(page.getByText('好，交给主编：要后面每章照着写的，会记进记忆', { exact: true })).toBeVisible()
    await shot('任务4-02-试读意见交给主编.png')
  }
  await expect.poll(async () => {
    const messages = await meeting(id)
    const author = messages.find(message => message.id > after && message.speaker === 'author' && message.payload?.feedback_memory?.feedback === text)
    return !!author && messages.some(message => message.payload?.feedback_to === author.id && !!message.content)
  }, { timeout: 120000 }).toBe(true)
  const messages = await meeting(id)
  const author = messages.find(message => message.id > after && message.speaker === 'author' && message.payload?.feedback_memory?.feedback === text)
  const reply = messages.find(message => message.payload?.feedback_to === author.id)
  assert.equal(author.payload.feedback_memory.state, 'done')
  assert.equal(reply.speaker, 'chief')
  assert.equal(reply.kind, 'speech')
  assert.equal(reply.job_id, jobId)
  assert.ok(!reply.payload.reply_to?.length, '看稿判断不是聊天工具回答，不能重新回答')
  await openChat()
  const box = page.getByTestId(`reply-${reply.id}`)
  await expect(box).toContainText(reply.content)
  await expect(box.getByRole('button', { name: '重新回答', exact: true })).toHaveCount(0)
  return { after, author, reply, box }
}
async function revised(id, jobId, after) {
  await expect.poll(async () => {
    const job = await get(`/jobs/${jobId}`)
    if (job.status === 'failed') throw new Error(job.error)
    const artifact = (await meeting(id)).some(message => message.id > after && message.job_id === jobId && message.payload?.type === 'volume_plan')
    return artifact && job.status === 'waiting_author' && job.pending?.kind === 'volume_review'
  }, { timeout: 180000 }).toBe(true)
  const messages = await meeting(id)
  assert.ok(messages.some(message => message.id > after && message.content.includes('按你的意见修改第1卷卷纲')))
}
try {
  const profiles = await get('/llm/profiles')
  assert.ok(profiles.length > 0 && profiles.every(profile => profile.provider === 'demo'))
  const id = fixture.feedback_volume_book_id, jobId = fixture.feedback_volume_job_id
  await openGate(id, '卷纲')
  const before = await get(`/books/${id}/outline`)
  const beforeMemory = await memories(id)
  const short = await submit(id, jobId, '这一卷打斗多一点')
  await revised(id, jobId, short.after)
  await expect(short.box.locator('[data-testid^="memory-notice-"]')).toHaveCount(0)
  assert.ok(!short.reply.payload.memories?.length)
  assert.deepEqual(await memories(id), beforeMemory)
  const current = await get(`/books/${id}/outline`)
  assert.notDeepEqual(current.volumes[0].units.map(unit => unit.key_events), before.volumes[0].units.map(unit => unit.key_events), '卷纲经过真实改稿已更新')
  pass('卷纲短期意见真实改稿，主编在群聊回话，不自动记忆')

  // Keep the same live gate: a second real revision tests lasting rules separately.
  const lasting = await submit(id, jobId, '以后每章打斗都多一点')
  await revised(id, jobId, lasting.after)
  const receipt = lasting.reply.payload.memories?.[0]?.memory
  assert.ok(receipt)
  assert.equal(receipt.action, 'create')
  assert.equal(receipt.book_id, id)
  assert.equal(receipt.kind, 'writing')
  const notice = lasting.box.getByTestId(`memory-notice-${receipt.id}`)
  await expect(notice.getByRole('button', { name: `记住了：${receipt.summary}`, exact: true })).toBeVisible()
  await expect(notice.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
  const remembered = (await memories(id)).find(row => row.id === receipt.id)
  assert.equal(remembered.source, '看稿时说的')
  assert.equal(remembered.detail, '以后每章打斗都多一点')
  await shot('任务4-01-主编判断记住了.png')
  await notice.getByRole('button', { name: `记住了：${receipt.summary}`, exact: true }).click()
  const memoryPage = panel().getByRole('region', { name: '记忆', exact: true })
  const memoryRow = memoryPage.getByTestId(`memory-${receipt.id}`)
  await expect(memoryRow).toHaveClass(/bg-chief-soft/u)
  await memoryRow.getByRole('button').first().click()
  await expect(memoryRow).toContainText('看稿时说的')
  await expect(memoryPage.getByRole('region', { name: '写书时照做', exact: true }).getByTestId(`memory-${receipt.id}`)).toBeVisible()
  await memoryPage.getByRole('button', { name: '回到聊天', exact: true }).click()
  await notice.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(notice).toContainText(`没记：${receipt.summary}`)
  await expect.poll(async () => (await memories(id)).some(row => row.id === receipt.id)).toBe(false)
  pass('卷纲长期意见真实改稿，主编回话下有记住行，记忆页来源正确，可撤销')

  const trialId = fixture.feedback_trial_book_id, trialJobId = fixture.feedback_trial_job_id
  await openGate(trialId, '试读前 3 章')
  const trialBefore = await memories(trialId)
  const trial = await submit(trialId, trialJobId, '第三章对话太多，节奏再快一点', true)
  assert.ok(trial.reply.content.includes('正文') && trial.reply.content.includes('重写'))
  await expect(trial.box.locator('[data-testid^="memory-notice-"]')).toHaveCount(0)
  assert.deepEqual(await memories(trialId), trialBefore)
  await expect.poll(async () => (await get(`/books/${trialId}`)).trial_read_done).toBe(true)
  pass('试读交意见出现逐字新提示，主编异步回话，眼前单章意见不记为长期规矩')

  assert.deepEqual(report.errors, [])
  assert.deepEqual(report.externalRequests, [])
} catch (error) {
  report.failure = { message: String(error), body: await page.locator('body').innerText() }
  throw error
} finally {
  await fs.writeFile(path.join(OUT, 'feedback-browser-results.json'), JSON.stringify(report, null, 2))
  await context.close(); await browser.close()
}
