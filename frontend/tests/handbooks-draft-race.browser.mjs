/** 真实 API 慢保存跨页面回归：只延迟原样响应的交付，不伪造业务响应。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.HANDBOOKS_TEST_BASE
const api = process.env.HANDBOOKS_TEST_API
const fixturePath = process.env.HANDBOOKS_TEST_FIXTURE
assert.ok(base && api && fixturePath, '显式指定本包独立前后端地址和合成书 fixture')
const fixture = JSON.parse(await fs.readFile(fixturePath, 'utf8'))
const out = process.env.HANDBOOKS_RACE_OUTPUT ?? path.join(root, 'data/handbooks-20261028/draft-race')
const origins = new Set([new URL(base).origin, new URL(api).origin])
for (const origin of origins) {
  const url = new URL(origin)
  assert.equal(url.hostname, '127.0.0.1')
  assert.ok(url.port && !['8000', '4320'].includes(url.port), '不得访问作者日常服务')
}
await fs.mkdir(out, { recursive: true })
const json = async (suffix, options) => {
  const response = await fetch(api + suffix, options)
  assert.ok(response.ok, `${suffix}: ${response.status}`)
  return response.status === 204 ? null : response.json()
}
const original = await json('/handbooks/opening')
const first = { name: original.name, when: original.when, body: original.body + '\n\n慢保存回归：第一份已提交的正文。' }
const second = { name: '开书新草稿', when: '慢保存回归：这是第二份尚未提交的目录说明。', body: first.body + '\n\n慢保存回归：第二份新草稿必须保留。' }
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN', timezoneId: 'Asia/Taipei', reducedMotion: 'reduce' })
const page = await context.newPage()
const pageErrors = [], forbiddenRequests = []
page.on('pageerror', error => pageErrors.push(error.message))
await context.route('**/*', route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && !origins.has(url.origin)) { forbiddenRequests.push(url.origin + url.pathname); return route.abort() }
  return route.continue()
})
await context.addInitScript(() => {
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', reducedMotion: true }))
})
let release
const gate = new Promise(resolve => { release = resolve })
let committed
const commitReached = new Promise(resolve => { committed = resolve })
let held = false
await context.route(url => url.pathname === '/api/handbooks/opening', async route => {
  if (route.request().method() !== 'PUT' || held) return route.continue()
  held = true
  // This is the actual backend response, including the actual committed save.
  const response = await route.fetch()
  committed(response.status())
  await gate
  await route.fulfill({ response })
})
const field = name => page.getByRole('textbox', { name, exact: true })
const editor = () => page.getByTestId('prompt-editor').locator('.cm-content[contenteditable="true"]')
const replaceBody = async body => { await editor().click(); await editor().press('Control+A'); await page.keyboard.insertText(body) }
const detailFields = detail => ({ name: detail.name, when: detail.when, body: detail.body })
let ok = false
try {
  const source = `/desk/${fixture.book}?tab=${encodeURIComponent('大纲')}&node=book#outline`
  await page.goto(`${base}/handbooks?key=opening&${new URLSearchParams({ returnTo: source })}`)
  await expect(field('名称')).toHaveValue(original.name)
  await replaceBody(first.body)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal(await commitReached, 200, '第一稿真的在后台提交，只扣住响应交付')
  assert.deepEqual(detailFields(await json('/handbooks/opening')), first)
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeDisabled()

  // SPA 离开原实例再返回，不能用整页goto把旧fetch直接取消。
  await page.getByRole('link', { name: '返回当前书', exact: true }).click()
  await page.getByRole('button', { name: '系统设置', exact: true }).click()
  await page.getByRole('dialog', { name: '系统设置', exact: true }).getByRole('link', { name: '手册管理', exact: true }).click()
  await expect(field('名称')).toBeEnabled()
  await field('名称').fill(second.name)
  await field('什么时候翻').fill(second.when)
  await replaceBody(second.body)
  const draftKey = 'zhibi:handbook-draft:opening'
  assert.deepEqual(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), draftKey), second)

  // 旧apply会刷新列表；等那一轮真实读取完成，证明旧响应处理已走过清草稿处。
  const invalidated = page.waitForResponse(response => new URL(response.url()).pathname === '/api/handbooks' && response.request().method() === 'GET')
  release()
  await invalidated
  assert.deepEqual(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), draftKey), second, '旧响应不能清掉新实例写的三字段草稿')
  await page.reload()
  await expect(field('名称')).toHaveValue(second.name)
  await expect(field('什么时候翻')).toHaveValue(second.when)
  await editor().click()
  await editor().press('Control+End')
  await expect(editor()).toContainText('第二份新草稿必须保留。')
  assert.deepEqual(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), draftKey), second)
  assert.deepEqual(detailFields(await json('/handbooks/opening')), first, '后台只存第一稿，不擅自提交新草稿')
  assert.deepEqual(pageErrors, [])
  assert.deepEqual(forbiddenRequests, [])
  ok = true
  console.log('PASS 真实慢保存跨页面：旧响应不清新草稿；刷新后三字段都在；后台仅提交第一稿；0页面错误/外网/真实模型调用')
} catch (error) {
  await page.screenshot({ path: path.join(out, 'FAILED.png') }).catch(() => {})
  throw error
} finally {
  release()
  await context.unrouteAll({ behavior: 'wait' })
  await json('/handbooks/opening' + (original.modified ? '' : '/use-system'), original.modified
    ? { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(detailFields(original)) }
    : { method: 'POST' })
  await fs.writeFile(path.join(out, 'report.json'), JSON.stringify({ ok, base, api, book: fixture.book, first, second, pageErrors, forbiddenRequests, realModelCalls: 0 }, null, 2) + '\n')
  await browser.close()
}
