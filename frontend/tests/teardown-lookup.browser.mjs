/** 独立真实 API + 演示模型；不替换业务响应，不连日常端口或外网。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = 'http://127.0.0.1:4383'
const api = 'http://127.0.0.1:8083/api'
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'data/teardown-lookup/fixtures.json'), 'utf8'))
const out = path.join(root, 'docs/主编查拆过的书验收')
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
const errors = [], forbiddenRequests = []
page.on('pageerror', error => errors.push(error.message))
await context.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && (url.hostname !== '127.0.0.1' || !['4383', '8083'].includes(url.port))) {
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

  const rerun = page.waitForResponse(response => response.url().endsWith(`/chat/replies/${reply.id}/again`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: '重新回答', exact: true }).click()
  assert.equal((await rerun).status(), 202)
  await expect.poll(async () => {
    const rows = await json(`/llm-calls?book_id=${fixture.book}`)
    return (await json(`/llm-calls/${rows.items[0].id}`)).request.method
  }, { timeout: 30000 }).toBe('demo_stream')
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeVisible({ timeout: 30000 })
  const rerunCalls = await json(`/llm-calls?book_id=${fixture.book}`)
  const again = await json(`/llm-calls/${rerunCalls.items[0].id}`)
  assert.ok(again.request.user.includes(result), '不给工具的重新回答仍携带这一轮翻到的精髓原文')
  assert.equal(again.request.method, 'demo_stream')
  assert.deepEqual(errors, [])
  assert.deepEqual(forbiddenRequests, [])
  fs.writeFileSync(path.join(out, '任务1-浏览器验收.json'), JSON.stringify({
    base, api, book: fixture.book, sourceBook: fixture.source_book, sourceTitle: fixture.source_title,
    realAPI: true, responseReplacement: false, lookupLabel: label, expandedLookupText: result,
    bookEnum: spec.parameters.properties.book.enum, toolDescriptionLength: spec.description.length,
    rereplyRetainsLookupText: true, rereplyMethod: again.request.method,
    pageErrors: errors, forbiddenRequests, realModelCalls: 0,
    snapshots: ['任务1-群聊查拆书精髓.png'],
  }, null, 2) + '\n')
  console.log('PASS 新书群聊先查拆书精髓；查了标签逐字正确；点开可见精髓原文；重新回答保留全文；0 页面错误、0 真实模型调用')
} finally {
  await browser.close()
}
