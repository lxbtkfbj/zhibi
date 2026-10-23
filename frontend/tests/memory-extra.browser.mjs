/** Additional genuine UI flows: tools, stale undo, live global edits, working and rewind. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'
const ROOT = path.resolve(import.meta.dirname, '../..')
const OUT = path.join(ROOT, 'data/chat-improvements-task2')
const fixture = JSON.parse(await fs.readFile(path.join(OUT, 'fixture.json'), 'utf8'))
const BASE = 'http://127.0.0.1:4386', ROUTE = 'http://127.0.0.1:4384'
const allowed = new Set([BASE, ROUTE])
const report = { checks: [], errors: [], externalRequests: [], requests: [], demoOnly: true, workingFixture: 'synthetic running job; no worker task was queued' }
const expect = baseExpect.configure({ timeout: 15000 })
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
await context.route('**/*', route => {
 const url = new URL(route.request().url())
 if (['http:', 'https:'].includes(url.protocol) && !allowed.has(url.origin)) { report.externalRequests.push(url.href); return route.abort() }
 return route.continue()
})
context.on('page', page => { page.on('pageerror', e => report.errors.push(e.message)); page.on('request', r => { if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(r.method())) report.requests.push({ method: r.method(), url: r.url(), body: r.postDataJSON() }) }) })
const page = await context.newPage(), watcher = await context.newPage()
const pass = name => { report.checks.push(name); console.log(`PASS ${name}`) }
const panel = p => p.locator('[data-testid="editorial-floating"], [data-testid="editorial-docked"]')
const memory = p => panel(p).getByRole('region', { name: '记忆', exact: true })
const editor = p => memory(p).getByRole('form', { name: '编辑记忆' })
const composer = p => p.getByLabel('给编辑部发消息', { exact: true })
const get = async suffix => { const r = await context.request.get(`${BASE}/api${suffix}`); assert.equal(r.status(), 200, suffix); return r.json() }
async function open(p, id, base = BASE) { await p.goto(`${base}/desk/${id}`); const ball = p.locator('[role="button"][title="编辑部"]'); await expect(ball.or(composer(p))).toBeVisible(); if (await ball.isVisible()) await ball.click(); await expect(composer(p)).toBeVisible() }
async function type(input, text) { await input.click(); await input.press('ControlOrMeta+A'); await input.pressSequentially(text) }
async function show(p) { await panel(p).getByRole('button', { name: '记忆', exact: true }).click(); await expect(memory(p)).toBeVisible() }
async function back(p) { await memory(p).getByRole('button', { name: '回到聊天', exact: true }).click(); await expect(composer(p)).toBeVisible() }
async function save(p) { await editor(p).getByRole('button', { name: '保存', exact: true }).click(); await expect(editor(p)).toHaveCount(0) }
async function send(p, id, text) {
 await type(composer(p), text)
 const result = p.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === `/api/books/${id}/notes`)
 await composer(p).press('Enter'); const response = await result; assert.equal(response.status(), 201)
 const note = await response.json()
 let final
 await expect.poll(async () => { final = (await get(`/books/${id}/meeting?limit=2000`)).find(row => row.id === note.id); return final?.payload?.steps?.find(row => row.memory)?.memory?.id }, { timeout: 90000 }).toBeTruthy()
 const receipt = final.payload.steps.find(row => row.memory).memory
 await expect(p.getByTestId(`memory-notice-${receipt.id}`)).toContainText(`记住了：${receipt.summary}`)
 return { note: final, receipt }
}
try {
 const bid = fixture.new_book_id
 await open(page, bid)
 const before = await get(`/books/${bid}/saves?limit=100`)
 const { note, receipt } = await send(page, bid, '记住：以后每卷都要有因果闭环')
 const notice = page.getByTestId(`memory-notice-${receipt.id}`)
 await expect(notice).toContainText('写书时照做 · 这本书 · 一直有效')
 const saved = (await get(`/books/${bid}/memories`)).find(row => row.id === receipt.id)
 assert.equal(saved.source, '聊天里记的'); assert.equal(saved.summary, saved.detail)
 await expect.poll(async () => (await get(`/books/${bid}/meeting?limit=2000`)).findLast(row => row.payload?.reply_to?.includes(note.id))?.payload?.state ?? 'done', { timeout: 90000 }).toBe('done')
 pass('make_changes 真 demo 工具调用记成统一记忆行，摘要/详细/来源正确')
 await notice.getByRole('button', { name: /^记住了：/ }).click()
 let row = memory(page).getByTestId(`memory-${receipt.id}`)
 await row.getByRole('button', { name: '改', exact: true }).click()
 await type(editor(page).getByLabel('简述', { exact: true }), '后来改过的记忆')
 await save(page); await back(page)
 await expect(notice.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
 await expect(notice.locator('span[title]')).toHaveAttribute('title', '这条后来又改过，去「记忆」里改')
 await notice.getByRole('button', { name: /^记住了：/ }).click()
 row = memory(page).getByTestId(`memory-${receipt.id}`)
 await expect(row).toContainText('后来改过的记忆')
 await row.getByRole('button', { name: '删', exact: true }).click(); await back(page)
 await expect(notice.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
 await expect(notice.locator('span[title]')).toHaveAttribute('title', '这条后来删掉了')
 pass('记忆后来改过/删掉时，旧聊天行撤销变灰并逐字提示')
 await show(page)
 const expired = (await get(`/books/${bid}/memories`)).find(row => !row.active)
 let expiredRow = memory(page).getByTestId(`memory-${expired.id}`)
 await expiredRow.getByRole('button').first().click(); await expiredRow.getByRole('button', { name: '改', exact: true }).click()
 await type(editor(page).getByLabel('简述', { exact: true }), '过期的也能改')
 await save(page)
 assert.equal((await get(`/books/${bid}/memories`)).find(row => row.id === expired.id).chapter_index, 1)
 await expect(memory(page).getByTestId(`memory-${expired.id}`)).toContainText('已过期 · 只管第 1 章')
 await memory(page).getByTestId(`memory-${expired.id}`).getByRole('button', { name: '删', exact: true }).click()
 await expect(memory(page).getByText('删掉了：过期的也能改', { exact: false })).toBeVisible()
 pass('过期记忆可改可删，未重选管多久时不会挪到下一章')
 await open(watcher, fixture.empty_book_id, ROUTE); await show(watcher)
 await memory(watcher).getByRole('tab', { name: '全局', exact: true }).click()
 await memory(page).getByRole('tab', { name: '全局', exact: true }).click()
 await memory(page).getByRole('button', { name: '加一条', exact: true }).click()
 await type(editor(page).getByLabel('简述', { exact: true }), '跨书实时刷新的全局喜好')
 await editor(page).getByLabel('种类', { exact: true }).selectOption('chat')
 await save(page)
 await expect(memory(watcher).getByText('跨书实时刷新的全局喜好', { exact: false })).toBeVisible()
 const global = (await get(`/books/${bid}/memories`)).find(row => row.summary === '跨书实时刷新的全局喜好')
 await memory(page).getByTestId(`memory-${global.id}`).getByRole('button', { name: '删', exact: true }).click()
 await expect(memory(watcher).getByTestId(`memory-${global.id}`)).toHaveCount(0)
 pass('另一书开着的全局记忆页随新增、删除实时刷新')
 await back(page)
 // A memory-only conversation never produces the book-change warning when editing the author's words.
 const bubble = page.getByTestId(`note-${note.id}`)
 await bubble.scrollIntoViewIfNeeded(); await bubble.hover()
 await bubble.getByRole('button', { name: '修改', exact: true }).click()
 await expect(page.getByTestId('chat-inline-edit')).toBeVisible()
 await expect(page.getByText(/这句和后面的话改过书（/)).toHaveCount(0)
 await page.getByTestId('chat-inline-edit').getByRole('button', { name: '取消', exact: true }).click()
 const after = await get(`/books/${bid}/saves?limit=100`)
 assert.equal(after.items.length, before.items.length)
 pass('修改提醒不数记忆；纯记忆新增、编辑、删除、工具执行不添自动存档')
 await open(page, fixture.working_book_id)
 const working = await send(page, fixture.working_book_id, '记住：下一章要有一个明确的选择')
 assert.equal(working.receipt.working, true)
 await expect(page.getByTestId(`memory-notice-${working.receipt.id}`)).toContainText('写书时照做 · 这本书 · 只管第 1 章 · 正在写的从下一步起照办')
 await page.getByTestId(`memory-notice-${working.receipt.id}`).getByRole('button', { name: '撤销', exact: true }).click()
 await expect(page.getByTestId(`memory-notice-${working.receipt.id}`)).toContainText('没记：')
 pass('运行中工具路径显示从下一步照办，撤销不等待写作结束、不进待处理')
 assert.deepEqual(report.errors, []); assert.deepEqual(report.externalRequests, [])
} finally { await fs.writeFile(path.join(OUT, 'memory-browser-extra-results.json'), JSON.stringify(report, null, 2)); await context.close(); await browser.close() }
