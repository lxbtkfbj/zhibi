/** 独立真实 API + 演示模型；不拦截业务响应，不连日常端口或外网。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.HANDBOOK_TEST_BASE ?? 'http://127.0.0.1:4377'
const api = process.env.HANDBOOK_TEST_API ?? 'http://127.0.0.1:8077/api'
const fixture = JSON.parse(fs.readFileSync(process.env.HANDBOOK_TEST_FIXTURE ?? path.join(root, 'data/handbook-task1/fixtures.json'), 'utf8'))
const out = process.env.HANDBOOK_TEST_OUTPUT ?? path.join(root, 'docs/主编手册验收')
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
const original = await json('/prompts/skills.opening')
const marker = '手册任务1独立验收全文标记'
const customized = original.content.replace('什么时候翻：', '什么时候翻：独立验收目录标记；') + '\n' + marker + '\n'
const executablePath = process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: 'light' })
const page = await context.newPage()
const errors = [], forbiddenRequests = []
page.on('pageerror', error => errors.push(error.message))
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
  await page.goto(`${base}/prompts?template=skills.opening`)
  await expect(page.locator('[data-prompt-group="手册"] .prompt-group-toggle')).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('.template-toolbar h2')).toHaveText('开书')
  await page.getByRole('button', { name: '修改', exact: true }).click()
  const editor = page.locator('.cm-content[contenteditable="true"]')
  await editor.click()
  await page.keyboard.press('Control+A')
  await page.keyboard.insertText(customized)
  const saved = page.waitForResponse(response => response.url().endsWith('/api/prompts/skills.opening') && response.request().method() === 'PUT')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal((await saved).status(), 200)
  await expect(page.getByText('已保存，从下一步调用起对所有书生效。')).toBeVisible()
  assert.equal((await json('/prompts/skills.opening')).content, customized)
  const entries = await json('/prompts')
  assert.ok(entries.find(row => row.name === 'skills.opening').when.includes('独立验收目录标记'))

  await json(`/books/${fixture.book}/chat/conversations`, { method: 'POST' })
  const beforeCalls = await json(`/llm-calls?book_id=${fixture.book}`)
  const beforeId = beforeCalls.items[0]?.id ?? 0
  const conversationsReady = page.waitForResponse(response => new URL(response.url()).pathname === `/api/books/${fixture.book}/chat/conversations` && response.request().method() === 'GET' && response.status() === 200)
  await page.goto(`${base}/desk/${fixture.book}`)
  await conversationsReady
  await expect(async () => {
    await page.getByRole('textbox', { name: '给编辑部发消息' }).fill('开书先定什么')
    await expect(page.getByRole('textbox', { name: '给编辑部发消息' })).toHaveValue('开书先定什么')
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled({ timeout: 1000 })
  }).toPass({ timeout: 10000 })
  const sent = page.waitForResponse(response => new URL(response.url()).pathname === `/api/books/${fixture.book}/notes` && response.request().method() === 'POST')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  assert.equal((await sent).status(), 201)
  await expect(page.getByRole('button', { name: '查了：手册《开书》', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.getByText(/翻了开书手册。/)).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, '任务1-群聊翻开书手册.png') })
  const meeting = await json(`/books/${fixture.book}/meeting?limit=2000`)
  const reply = meeting.toReversed().find(row => row.payload?.tools?.some(tool => tool.label === '手册《开书》'))
  assert.equal(reply.payload.tools[0].text, customized, '手册全文（含末尾标记）不截断')
  const rerun = page.waitForResponse(response => response.url().endsWith(`/chat/replies/${reply.id}/again`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: '重新回答', exact: true }).click()
  assert.equal((await rerun).status(), 202)
  await expect.poll(async () => {
    const rows = await json(`/llm-calls?book_id=${fixture.book}`)
    return (await json(`/llm-calls/${rows.items[0].id}`)).request.method
  }, { timeout: 30000 }).toBe('demo_stream')
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeVisible({ timeout: 30000 })
  const calls = await json(`/llm-calls?book_id=${fixture.book}`)
  const again = await json(`/llm-calls/${calls.items[0].id}`)
  assert.ok(again.request.user.includes(customized), '重新回答仍携带这轮的手册全文')
  assert.equal(again.request.method, 'demo_stream')
  const first = await json(`/llm-calls/${calls.items.filter(call => call.id > beforeId).at(-1).id}`)
  const spec = first.request.schema.find(tool => tool.function.name === 'read_skill').function
  assert.ok(spec.description.includes('独立验收目录标记'))
  assert.deepEqual(spec.parameters.properties.name.enum, ['开书'])

  await page.goto(`${base}/settings`)
  const modal = page.getByRole('dialog', { name: '系统设置', exact: true })
  await expect(modal).toBeVisible()
  const warning = '这个接口在群聊里调工具被拒过：编辑部不会自己查资料、翻手册、动手，先判断要做什么，再一件件做。点「测试」可以重新试。'
  const auto = '这个接口不认强制调工具，出结构化结果已自动改用 JSON 模式；不影响群聊里调工具。'
  await expect(modal.getByText(warning, { exact: true })).toBeVisible()
  await expect(modal.getByText(auto, { exact: true })).toBeVisible()
  const profiles = await json('/llm/profiles')
  assert.equal(profiles.find(row => row.id === fixture.rejected_profile).structured_method, 'json_mode')
  assert.equal(profiles.find(row => row.id === fixture.rejected_profile).chat_tools, false)
  await page.screenshot({ path: path.join(out, '任务1-JSON模式群聊工具提示.png') })
  assert.deepEqual(errors, [])
  assert.deepEqual(forbiddenRequests, [])
  fs.writeFileSync(path.join(out, '任务1-浏览器验收.json'), JSON.stringify({
    base, api, book: fixture.book, promptPageVisibleAndEditable: true, customCatalogAndFullText: true,
    readSkillEnum: spec.parameters.properties.name.enum, rereplyRetainsFullText: true,
    jsonModeRejectedHint: true, pageErrors: errors, forbiddenRequests, realModelCalls: 0,
    snapshots: ['任务1-群聊翻开书手册.png', '任务1-JSON模式群聊工具提示.png'],
  }, null, 2) + '\n')
  console.log('PASS 手册页可见可改；目录和全文用自定义版；新书群聊翻手册；重新回答带全文；JSON 模式独立提示；0 页面错误、0 真实模型调用')
} finally {
  await json('/prompts/skills.opening', original.customized
    ? { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ content: original.content }) }
    : { method: 'DELETE' })
  await browser.close()
}
