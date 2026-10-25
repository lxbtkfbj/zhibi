/** 独立真实 API + 演示模型 + 本机假搜索；不替换业务响应，不连日常端口或外网。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.WEB_SEARCH_TEST_BASE ?? 'http://127.0.0.1:14374'
const api = process.env.WEB_SEARCH_TEST_API ?? 'http://127.0.0.1:18074/api'
const fixture = JSON.parse(fs.readFileSync(process.env.WEB_SEARCH_TEST_FIXTURE ?? path.join(root, 'data/web-search-task1/fixtures.json'), 'utf8'))
const out = process.env.WEB_SEARCH_TEST_OUTPUT ?? path.join(root, 'docs/主编联网搜索验收')
const requestLog = process.env.WEB_SEARCH_TEST_REQUEST_LOG ?? path.join(root, 'data/web-search-task1/fake-search-requests.jsonl')
const allowed = new Set([new URL(base).origin, new URL(api).origin])
assert.ok([...allowed].every(origin => {
  const url = new URL(origin)
  return url.hostname === '127.0.0.1' && !['8000', '4320'].includes(url.port)
}), '仅允许独立本机环境，不得访问日常服务')
fs.mkdirSync(out, { recursive: true })
const requests = () => fs.existsSync(requestLog) ? fs.readFileSync(requestLog, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line)) : []
const json = async (suffix, options) => {
  const response = await fetch(api + suffix, { ...options, redirect: 'error' })
  assert.ok(response.ok, `${suffix}: ${response.status}`)
  return response.status === 204 ? null : response.json()
}
const browser = await chromium.launch({ executablePath: process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: 'light', serviceWorkers: 'block' })
const page = await context.newPage()
const errors = [], forbiddenRequests = [], againRequests = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => {
  if (request.method() === 'POST' && /\/chat\/replies\/\d+\/again$/u.test(new URL(request.url()).pathname)) againRequests.push(request.url())
})
await context.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && !allowed.has(url.origin)) {
    forbiddenRequests.push(url.origin + url.pathname)
    return route.abort()
  }
  return route.continue()
})
await context.routeWebSocket('**/*', socket => {
  const url = new URL(socket.url())
  if (!allowed.has(url.origin.replace(/^ws/u, 'http'))) {
    forbiddenRequests.push(url.origin + url.pathname)
    socket.close()
  } else socket.connectToServer()
})
await context.addInitScript(() => {
  localStorage.setItem('zhibi:editorial-dock', 'side')
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', reducedMotion: true }))
})

try {
  const roles = await json('/llm/roles')
  assert.ok(Object.values(roles).filter(Boolean).every(id => id === fixture.profile), '所有已分配角色都用演示模型')
  const initialProfiles = await json('/llm/profiles')
  assert.equal(initialProfiles.find(profile => profile.id === fixture.profile).provider, 'demo')
  assert.ok(initialProfiles.every(profile => !('web_search' in profile)), '模型配置不再带联网搜索标记')
  assert.deepEqual(await json('/llm/web-search'), { has_key: true })

  await json(`/books/${fixture.book}/chat/conversations`, { method: 'POST' })
  const beforeId = (await json(`/llm-calls?book_id=${fixture.book}`)).items[0]?.id ?? 0
  const beforeRequests = requests().length
  await page.goto(`${base}/desk/${fixture.book}`)
  await expect(page.getByText('跟编辑部说点什么', { exact: true })).toBeVisible()
  const composer = page.getByRole('textbox', { name: '给编辑部发消息' })
  await composer.click()
  await composer.fill('上网搜 斗破苍穹 异火')
  await expect(composer).toHaveValue('上网搜 斗破苍穹 异火')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const label = '网上搜「斗破苍穹 异火」'
  const looked = page.getByRole('button', { name: `查了：${label}`, exact: true })
  await expect(looked).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('上网搜了「斗破苍穹 异火」。', { exact: false })).toBeVisible()
  await looked.click()
  await expect(looked).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('网上搜「斗破苍穹 异火」，前 3 条：', { exact: false })).toBeVisible()
  const meeting = await json(`/books/${fixture.book}/meeting?limit=2000`)
  const reply = meeting.toReversed().find(row => row.payload?.tools?.some(tool => tool.label === label))
  assert.ok(reply, '真实 API 保存了联网搜索记录')
  await expect(page.getByTestId(`reply-${reply.id}`)).toHaveAttribute('data-state', 'done')
  const note = meeting.find(row => row.id === reply.payload.reply_to[0])
  assert.equal(reply.payload.reply_to.length, 1)
  assert.ok(note?.payload?.conv, '这条回答对应有分段记号的作者原话')
  assert.ok(reply.content.includes('上网搜了「斗破苍穹 异火」。'))
  const result = reply.payload.tools.find(tool => tool.label === label).text
  const expected = '网上搜「斗破苍穹 异火」，前 3 条：\n\n'
    + '1. 验收百科《异火榜（隔离假资料）》（2026-10-24）\nhttps://baike.example.test/item/yihuo\n# 异火榜：这是独立验收的假搜索摘要，包含青莲地心火、陨落心炎等假示例 [1]。\n\n'
    + '2. 验收书评《萧炎与异火（隔离假资料）》\nhttps://review.example.test/yihuo\n第二条不同来源的假摘要。 搜索结果只用来验收，不代表原著事实。\n\n'
    + '3. fiction.example.test《异火资料整理（隔离假资料）》\nhttps://fiction.example.test/yihuo\n没有 summary 时使用 snippet；这是第三条独立验收假资料。\n\n'
    + '这些是网上的说法，不一定准：跟作者说的时候讲明是网上搜到的、出自哪个网站；几处说法对不上的，照实说。'
  assert.equal(result, expected, '假结果去重、清理、日期、网站替补和末尾提醒逐字一致')
  assert.deepEqual(requests().slice(beforeRequests), [{ path: '/v1/tools/search', request: { query: '斗破苍穹 异火', count: 10 } }])
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, '任务1-群聊联网搜索原文.png') })

  const firstCalls = await json(`/llm-calls?book_id=${fixture.book}`)
  const first = await json(`/llm-calls/${firstCalls.items.filter(call => call.id > beforeId).at(-1).id}`)
  assert.deepEqual(first.request.schema.slice(-2).map(tool => tool.function.name), ['search_web', 'read_webpage'])
  const firstDetails = await Promise.all(firstCalls.items.filter(call => call.id > beforeId).map(call => json(`/llm-calls/${call.id}`)))
  const toolCount = details => details.filter(call => call.response?.includes('【调了工具】\nsearch_web：')).length
  assert.equal(toolCount(firstDetails), 1, '第一轮确实联网搜索一次')
  const afterSearchRequests = requests().length
  const rerun = page.waitForResponse(response => new URL(response.url()).pathname === `/api/books/${fixture.book}/notes` && response.request().method() === 'POST')
  await page.getByRole('button', { name: '重新回答', exact: true }).click()
  const resent = await rerun
  assert.equal(resent.status(), 201)
  const resendBody = resent.request().postDataJSON()
  const expectedBody = { content: note.content, conv: note.payload.conv, rewind_from: note.id }
  for (const key of ['ask', 'quote', 'viewing']) if (note.payload[key] != null) expectedBody[key] = note.payload[key]
  assert.deepEqual(resendBody, expectedBody, '重新回答原样保留作者原话的全部请求字段')
  const newNote = await resent.json()
  await expect(page.getByTestId(`note-${note.id}`)).toHaveCount(0)
  await expect(page.getByTestId(`reply-${reply.id}`)).toHaveCount(0)
  await expect(page.getByTestId(`note-${newNote.id}`)).toContainText(note.content)
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeVisible({ timeout: 30000 })
  const afterMeeting = await json(`/books/${fixture.book}/meeting?limit=2000`)
  const newReply = afterMeeting.find(row => row.payload?.reply_to?.includes(newNote.id))
  assert.ok(newReply && newReply.id !== reply.id, '新的一轮产生了新回答')
  assert.equal(afterMeeting.find(row => row.id === note.id).payload.dropped, true)
  assert.equal(afterMeeting.find(row => row.id === reply.id).payload.dropped, true)
  assert.deepEqual(newReply.payload.tools, reply.payload.tools, '新的一轮查了的标签和假搜索原文逐字不变')
  const newLooked = page.getByTestId(`reply-${newReply.id}`).getByRole('button', { name: `查了：${label}`, exact: true })
  await newLooked.click()
  assert.equal(await page.getByTestId(`reply-${newReply.id}`).getByText(expected, { exact: true }).textContent(), expected)
  const againCalls = await json(`/llm-calls?book_id=${fixture.book}`)
  const again = await json(`/llm-calls/${againCalls.items[0].id}`)
  const details = await Promise.all(againCalls.items.filter(call => call.id > beforeId).map(call => json(`/llm-calls/${call.id}`)))
  assert.equal(toolCount(details), toolCount(firstDetails) + 1, '原话重发后又联网搜索一次')
  assert.ok(again.request.user.includes(result), '新的一轮工具调用携带刚搜到的全文')
  assert.equal(again.request.method, 'tools')
  assert.equal(requests().length, afterSearchRequests + 1, '重新回答再次请求假搜索服务一次')
  assert.deepEqual(requests().slice(afterSearchRequests), [{ path: '/v1/tools/search', request: { query: '斗破苍穹 异火', count: 10 } }])
  assert.ok(againCalls.items.filter(call => call.id > beforeId).every(call => call.model === 'demo'), '此轮及重新回答只调用演示模型')
  assert.deepEqual(againRequests, [], '原话重发不调用只重写的 /again')

  await page.goto(`${base}/settings`)
  const modal = page.getByRole('dialog', { name: '系统设置', exact: true })
  await expect(modal).toBeVisible()
  const searchGroup = modal.locator('.settings-group').filter({ has: page.getByRole('heading', { name: '联网搜索', exact: true }) })
  const hint = '已保存，不回显 · 群聊里编辑部拿不准时会自己上网搜；搜一次、读一页各约半分钱'
  await expect(searchGroup.locator('.settings-row-hint')).toHaveText(hint)
  await expect(modal.getByText('联网搜索用它的密钥')).toHaveCount(0)
  const beforeTest = requests().length
  await searchGroup.getByRole('button', { name: '测试', exact: true }).click()
  const testMessage = '能搜：试搜「网络小说」，第一条是验收百科《异火榜（隔离假资料）》。'
  await expect(searchGroup.getByText(testMessage, { exact: true })).toBeVisible()
  assert.deepEqual(requests().slice(beforeTest).map(item => item.request), [{ query: '网络小说', count: 1 }], '测试只搜一次')
  const row = name => modal.locator('.settings-row').filter({ has: page.locator('.settings-row-label').filter({ hasText: name }) })
  await expect(row(initialProfiles.find(profile => profile.id === fixture.profile).name).locator('.settings-row-hint')).toHaveText('演示模式 · 内置示例内容，不联网')
  assert.deepEqual(await json('/llm/roles'), roles, '验收未改变角色分工')
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, '任务1-系统设置联网搜索密钥.png') })
  assert.deepEqual(errors, [])
  assert.deepEqual(forbiddenRequests, [])
  fs.writeFileSync(path.join(out, '任务1-浏览器验收.json'), JSON.stringify({
    base, api, book: fixture.book, realAPI: true, responseReplacement: false,
    lookupLabel: label, expandedLookupText: result, replyReceipt: '上网搜了「斗破苍穹 异火」。',
    fakeSearchRequests: requests().slice(beforeRequests), rereplyRetainsLookupText: true,
    rereplyMethod: again.request.method, rereplySearchesAgain: true, resendBody,
    originalNote: note, newNoteId: newNote.id, newReplyId: newReply.id, searchCallsBefore: toolCount(firstDetails), searchCallsAfter: toolCount(details),
    webSearchHint: hint, webSearchTestMessage: testMessage,
    pageErrors: errors, forbiddenRequests, realModelCalls: 0, realDeepSeekCalls: 0,
    snapshots: ['任务1-群聊联网搜索原文.png', '任务1-系统设置联网搜索密钥.png'],
  }, null, 2) + '\n')
  console.log('PASS 群聊真实 API 搜假网页、查了原文逐字正确；重新回答原话重发、假搜索多一次；系统设置「联网搜索」显示已保存、测试只搜一次；0 页面错误、0 外网请求')
} catch (error) {
  await page.screenshot({ path: path.join(root, 'data/web-search-task1/browser-failure.png') }).catch(() => {})
  console.error('Browser diagnostics:', JSON.stringify({ pageErrors: errors, forbiddenRequests, pageText: await page.locator('body').innerText().catch(() => '') }))
  throw error
} finally {
  await browser.close()
}
