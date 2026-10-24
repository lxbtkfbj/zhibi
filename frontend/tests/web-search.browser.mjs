/** 独立真实 API + 演示模型 + 本机假搜索；不替换业务响应，不连日常端口或外网。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = 'http://127.0.0.1:14374'
const api = 'http://127.0.0.1:18074/api'
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'data/web-search-task1/fixtures.json'), 'utf8'))
const out = path.join(root, 'docs/主编联网搜索验收')
const requestLog = path.join(root, 'data/web-search-task1/fake-search-requests.jsonl')
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
const errors = [], forbiddenRequests = []
page.on('pageerror', error => errors.push(error.message))
const allowed = new Set([base, new URL(api).origin])
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

let temporaryProfile
try {
  const roles = await json('/llm/roles')
  assert.ok(Object.values(roles).filter(Boolean).every(id => id === fixture.profile), '所有已分配角色都用演示模型')
  const initialProfiles = await json('/llm/profiles')
  assert.equal(initialProfiles.find(profile => profile.id === fixture.profile).provider, 'demo')
  const official = initialProfiles.find(profile => profile.id === fixture.search_profile)
  assert.equal(official.web_search, true)
  assert.deepEqual(initialProfiles.filter(profile => profile.web_search).map(profile => profile.id), [fixture.search_profile])

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
  const afterSearchRequests = requests().length
  const rerun = page.waitForResponse(response => response.url().endsWith(`/chat/replies/${reply.id}/again`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: '重新回答', exact: true }).click()
  assert.equal((await rerun).status(), 202)
  await expect.poll(async () => {
    const calls = await json(`/llm-calls?book_id=${fixture.book}`)
    return (await json(`/llm-calls/${calls.items[0].id}`)).request.method
  }, { timeout: 30000 }).toBe('demo_stream')
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeVisible({ timeout: 30000 })
  const againCalls = await json(`/llm-calls?book_id=${fixture.book}`)
  const again = await json(`/llm-calls/${againCalls.items[0].id}`)
  assert.ok(again.request.user.includes(result), '不给工具的重新回答携带这一轮搜到的原文')
  assert.equal(again.request.method, 'demo_stream')
  assert.equal(requests().length, afterSearchRequests, '重新回答没有再次请求假搜索服务')
  assert.ok(againCalls.items.filter(call => call.id > beforeId).every(call => call.model === 'demo'), '此轮及重新回答只调用演示模型')

  await page.goto(`${base}/settings`)
  const modal = page.getByRole('dialog', { name: '系统设置', exact: true })
  await expect(modal).toBeVisible()
  await modal.getByRole('button', { name: '＋ 添加', exact: true }).click()
  await modal.getByRole('textbox', { name: '模型配置名称' }).fill('较晚官方配置（验收后删除）')
  await modal.getByRole('textbox', { name: '接口地址', exact: true }).fill('https://api.deepseek.com/v1')
  await modal.getByLabel('API Key', { exact: true }).fill('fake-never-assigned-profile-key')
  await modal.getByRole('combobox', { name: '模型名', exact: true }).fill('deepseek-flash')
  const created = page.waitForResponse(response => response.url().endsWith('/api/llm/profiles') && response.request().method() === 'POST')
  await modal.getByRole('button', { name: '保存', exact: true }).click()
  const createResponse = await created
  assert.equal(createResponse.status(), 201)
  temporaryProfile = await createResponse.json()
  assert.equal(temporaryProfile.web_search, false, '较晚官方配置的新建响应不会抢走选中标记')
  const row = name => modal.locator('.settings-row').filter({ has: page.locator('.settings-row-label').filter({ hasText: name }) })
  await expect(row(temporaryProfile.name).locator('.settings-row-label')).toHaveText(temporaryProfile.name)
  await expect(row(temporaryProfile.name).locator('.settings-row-hint')).toHaveText('deepseek-flash · 已保存密钥')
  await row(official.name).getByRole('button', { name: '修改', exact: true }).click()
  const patched = page.waitForResponse(response => response.url().endsWith(`/api/llm/profiles/${official.id}`) && response.request().method() === 'PATCH')
  await modal.getByRole('button', { name: '保存', exact: true }).click()
  const patchResponse = await patched
  assert.equal(patchResponse.status(), 200)
  const updated = await patchResponse.json()
  assert.equal(updated.web_search, true, '选中配置修改响应仍然带 true')
  await json(`/llm/profiles/${temporaryProfile.id}`, { method: 'DELETE' })
  temporaryProfile = null
  await page.reload()
  await page.goto(`${base}/settings`)
  await expect(modal).toBeVisible()
  const suffix = 'deepseek-flash · 已保存密钥 · 联网搜索用它的密钥'
  await expect(row(official.name).locator('.settings-row-hint')).toHaveText(suffix)
  await expect(modal.getByText(suffix, { exact: true })).toHaveCount(1)
  await expect(row(initialProfiles.find(profile => profile.id === fixture.profile).name).locator('.settings-row-hint')).toHaveText('演示模式 · 内置示例内容，不联网')
  const finalProfiles = await json('/llm/profiles')
  assert.deepEqual(finalProfiles.map(profile => profile.id).sort(), initialProfiles.map(profile => profile.id).sort())
  assert.deepEqual(finalProfiles.filter(profile => profile.web_search).map(profile => profile.id), [fixture.search_profile])
  assert.deepEqual(await json('/llm/roles'), roles, '验收未改变角色分工')
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, '任务1-系统设置联网搜索密钥.png') })
  assert.deepEqual(errors, [])
  assert.deepEqual(forbiddenRequests, [])
  fs.writeFileSync(path.join(out, '任务1-浏览器验收.json'), JSON.stringify({
    base, api, book: fixture.book, realAPI: true, responseReplacement: false,
    lookupLabel: label, expandedLookupText: result, replyReceipt: '上网搜了「斗破苍穹 异火」。',
    fakeSearchRequests: requests().slice(beforeRequests), rereplyRetainsLookupText: true,
    rereplyMethod: again.request.method, rereplyDoesNotSearchAgain: true,
    createUnselectedWebSearch: false, updateSelectedWebSearch: true, settingsHint: suffix,
    selectedProfile: fixture.search_profile, temporaryProfileRemoved: true,
    pageErrors: errors, forbiddenRequests, realModelCalls: 0, realDeepSeekCalls: 0,
    snapshots: ['任务1-群聊联网搜索原文.png', '任务1-系统设置联网搜索密钥.png'],
  }, null, 2) + '\n')
  console.log('PASS 群聊真实 API 搜假网页、查了原文逐字正确；重新回答保留原文且不再搜；新建/修改 API 标记与设置行一致；0 页面错误、0 外网请求')
} catch (error) {
  await page.screenshot({ path: path.join(root, 'data/web-search-task1/browser-failure.png') }).catch(() => {})
  console.error('Browser diagnostics:', JSON.stringify({ pageErrors: errors, forbiddenRequests, pageText: await page.locator('body').innerText().catch(() => '') }))
  throw error
} finally {
  if (temporaryProfile) await json(`/llm/profiles/${temporaryProfile.id}`, { method: 'DELETE' })
  await browser.close()
}
