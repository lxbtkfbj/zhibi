/** 独立真实 API + 演示模型；不替换业务响应，不连日常端口或外网。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.TEARDOWN_LOOKUP_TEST_BASE ?? 'http://127.0.0.1:4383'
const api = process.env.TEARDOWN_LOOKUP_TEST_API ?? 'http://127.0.0.1:8083/api'
const fixture = JSON.parse(fs.readFileSync(process.env.TEARDOWN_LOOKUP_TEST_FIXTURE ?? path.join(root, 'data/teardown-lookup/fixtures.json'), 'utf8'))
const out = process.env.TEARDOWN_LOOKUP_TEST_OUTPUT ?? path.join(root, 'docs/主编查拆过的书验收')
const allowedOrigins = new Set([new URL(base).origin, new URL(api).origin])
assert.ok([...allowedOrigins].every(origin => {
  const url = new URL(origin)
  return url.hostname === '127.0.0.1' && !['8000', '4320'].includes(url.port)
}), '仅允许独立本机环境，不得访问日常服务')
fs.mkdirSync(out, { recursive: true })
const json = async (suffix, options) => {
  const response = await fetch(api + suffix, options)
  assert.ok(response.ok, `${suffix}: ${response.status}`)
  return response.json()
}
const executablePath = process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: 'light' })
const page = await context.newPage()
const errors = [], forbiddenRequests = [], againRequests = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => {
  if (request.method() === 'POST' && /\/chat\/replies\/\d+\/again$/u.test(new URL(request.url()).pathname)) againRequests.push(request.url())
})
await context.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && !allowedOrigins.has(url.origin)) {
    forbiddenRequests.push(url.origin + url.pathname)
    return route.abort()
  }
  return route.continue()
})
await context.addInitScript(() => {
  localStorage.setItem('zhibi:editorial-dock', 'side')
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', reducedMotion: true }))
})
try {
  const roles = await json('/llm/roles')
  assert.ok(Object.values(roles).filter(Boolean).every(id => id === fixture.profile), '所有已分配角色都用演示模型')
  assert.equal((await json('/llm/profiles')).find(profile => profile.id === fixture.profile).provider, 'demo')
  await json(`/books/${fixture.book}/chat/conversations`, { method: 'POST' })
  const beforeCalls = await json(`/llm-calls?book_id=${fixture.book}`)
  const beforeId = beforeCalls.items[0]?.id ?? 0
  await page.goto(`${base}/desk/${fixture.book}`)
  await page.getByRole('textbox', { name: '给编辑部发消息' }).fill(`《${fixture.source_title}》开局怎么写的`)
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const label = `《${fixture.source_title}》精髓「核心要点」`
  const looked = page.getByRole('button', { name: `查了：${label}`, exact: true })
  await expect(looked).toBeVisible({ timeout: 30000 })
  await expect(page.getByText(`翻了《${fixture.source_title}》的精髓。`, { exact: false })).toBeVisible()
  await looked.click()
  await expect(looked).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('这是一本什么书：', { exact: false })).toBeVisible()
  const meeting = await json(`/books/${fixture.book}/meeting?limit=2000`)
  const reply = meeting.toReversed().find(row => row.payload?.tools?.some(tool => tool.label === label))
  assert.ok(reply, '真实 API 保存了查拆过的书记录')
  await expect(page.getByTestId(`reply-${reply.id}`)).toHaveAttribute('data-state', 'done')
  const note = meeting.find(row => row.id === reply.payload.reply_to[0])
  assert.equal(reply.payload.reply_to.length, 1)
  assert.ok(note?.payload?.conv, '这条回答对应有分段记号的作者原话')
  const result = reply.payload.tools.find(tool => tool.label === label).text
  assert.ok(result.startsWith(`《${fixture.source_title}》精髓：拆书时从前 100 章整理的，章号是原书的。`))
  assert.ok(result.includes('【核心要点】'))
  assert.ok(result.includes('余波生事：把前事的报复后果做成下阶段新危机'))
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, '任务1-群聊查拆书精髓.png') })

  const calls = await json(`/llm-calls?book_id=${fixture.book}`)
  const first = await json(`/llm-calls/${calls.items.filter(call => call.id > beforeId).at(-1).id}`)
  const spec = first.request.schema.find(tool => tool.function.name === 'look_up_teardown')?.function
  assert.ok(spec, '群聊第一次调用实际发送了工具定义')
  assert.deepEqual(spec.parameters.properties.book.enum, [fixture.source_title])
  assert.ok(spec.description.includes(`《${fixture.source_title}》498 章，精髓只整理到第 100 章。`))
  assert.ok(spec.description.includes('- 核心要点：「余波生事：'))

  const firstDetails = await Promise.all(calls.items.filter(call => call.id > beforeId).map(call => json(`/llm-calls/${call.id}`)))
  const toolCount = details => details.filter(call => call.response?.includes('【调了工具】\nlook_up_teardown：')).length
  assert.equal(toolCount(firstDetails), 1, '第一轮确实查了一次拆书')
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
  assert.deepEqual(newReply.payload.tools, reply.payload.tools, '新的一轮查了的标签和精髓原文逐字不变')
  const newLooked = page.getByTestId(`reply-${newReply.id}`).getByRole('button', { name: `查了：${label}`, exact: true })
  await newLooked.click()
  assert.equal(await page.getByTestId(`reply-${newReply.id}`).getByText(result, { exact: true }).textContent(), result)
  const rerunCalls = await json(`/llm-calls?book_id=${fixture.book}`)
  const again = await json(`/llm-calls/${rerunCalls.items[0].id}`)
  const details = await Promise.all(rerunCalls.items.filter(call => call.id > beforeId).map(call => json(`/llm-calls/${call.id}`)))
  assert.equal(toolCount(details), toolCount(firstDetails) + 1, '原话重发后又查了一次拆书')
  assert.ok(again.request.user.includes(result), '新的一轮工具调用携带刚查到的精髓全文')
  assert.equal(again.request.method, 'tools')
  assert.ok(details.every(call => call.model === 'demo'), '此轮及重新回答只调用演示模型')
  assert.deepEqual(againRequests, [], '原话重发不调用只重写的 /again')
  assert.deepEqual(errors, [])
  assert.deepEqual(forbiddenRequests, [])
  fs.writeFileSync(path.join(out, '任务1-浏览器验收.json'), JSON.stringify({
    base, api, book: fixture.book, sourceBook: fixture.source_book, sourceTitle: fixture.source_title,
    realAPI: true, responseReplacement: false, lookupLabel: label, expandedLookupText: result,
    bookEnum: spec.parameters.properties.book.enum, toolDescriptionLength: spec.description.length,
    rereplyRetainsLookupText: true, rereplyMethod: again.request.method, resendBody,
    originalNote: note, newNoteId: newNote.id, newReplyId: newReply.id, lookupCallsBefore: toolCount(firstDetails), lookupCallsAfter: toolCount(details),
    pageErrors: errors, forbiddenRequests, realModelCalls: 0,
    snapshots: ['任务1-群聊查拆书精髓.png'],
  }, null, 2) + '\n')
  console.log('PASS 新书群聊查拆书精髓；重新回答原话重发、又查一次；旧原话和回答收起，查了标签及原文逐字正确；0 页面错误、0 真实模型调用')
} finally {
  await browser.close()
}
