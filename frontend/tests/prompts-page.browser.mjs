/** 提示词页任务 1：独立真实 API + 演示模型验收与四张截图。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.PROMPTS_PAGE_TEST_BASE ?? 'http://127.0.0.1:4395'
const api = process.env.PROMPTS_PAGE_TEST_API ?? 'http://127.0.0.1:8095/api'
const fixture = JSON.parse(await fs.readFile(process.env.PROMPTS_PAGE_TEST_FIXTURE ?? path.join(root, 'data/prompts-page/fixtures.json'), 'utf8'))
const out = process.env.PROMPTS_PAGE_TEST_OUTPUT ?? path.join(root, 'docs/提示词页验收')
const fingerprint = async () => Object.fromEntries(await Promise.all(['frontend/src/pages/PromptsPage.tsx', 'frontend/src/pages/PromptCallDetail.tsx', 'frontend/src/pages/prompts.css', 'frontend/src/api/prompts.ts', 'frontend/src/components/UsedPrompts.tsx', 'frontend/src/lib/promptDirectory.ts'].map(async file => [file, createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex')])))
const sourceSha256 = await fingerprint()
const allowedOrigins = new Set([new URL(base).origin, new URL(api).origin])
assert.ok([...allowedOrigins].every(origin => {
  const url = new URL(origin)
  return url.hostname === '127.0.0.1' && !['8000', '4320'].includes(url.port)
}), '不得访问作者日常服务或外网')
await fs.mkdir(out, { recursive: true })
const json = async (suffix, options) => {
  const response = await fetch(api + suffix, options)
  assert.ok(response.ok, `${suffix}: ${response.status}`)
  return response.json()
}
const entries = await json('/prompts')
const groups = [...new Set(entries.map(prompt => prompt.group))].map(group => ({ group, count: entries.filter(prompt => prompt.group === group).length }))
assert.deepEqual(groups, [
  { group: '角色与规矩', count: 7 }, { group: '聊天', count: 10 }, { group: '开书', count: 7 }, { group: '规划', count: 8 },
  { group: '设定库', count: 5 }, { group: '写作', count: 4 }, { group: '审稿与入库', count: 5 }, { group: '手册', count: 2 },
  { group: '题材打法', count: 2 }, { group: '拆书', count: 14 }, { group: '拆书精髓', count: 15 },
])
const original = await json('/prompts/chat_material')
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1700, height: 2700 }, locale: 'zh-CN', timezoneId: 'Asia/Taipei', reducedMotion: 'reduce' })
const page = await context.newPage()
const pageErrors = [], forbiddenRequests = [], checks = [], screenshots = []
page.on('pageerror', error => pageErrors.push(error.message))
await context.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && !allowedOrigins.has(url.origin)) {
    forbiddenRequests.push(url.origin + url.pathname)
    return route.abort()
  }
  return route.continue()
})
await context.addInitScript(() => {
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', reducedMotion: true }))
  localStorage.setItem('zhibi:editorial-dock', 'side')
})
const check = name => { checks.push(name); console.log(`PASS ${name}`) }
const shot = async name => {
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, name), fullPage: true })
  screenshots.push(name)
}
const heading = () => page.locator('.template-toolbar h2')
const catalog = () => page.getByRole('navigation', { name: '提示词列表', exact: true })
const toggle = name => page.locator(`[data-prompt-group="${name}"] .prompt-group-toggle`)
const companions = () => page.locator('.template-companions')
let call
let succeeded = false
try {
  await page.goto(`${base}/prompts`)
  await expect(heading()).toHaveText('主编人设')
  await expect(page.locator('.prompt-group-toggle').first()).toHaveText('角色与规矩7')
  await expect(toggle('拆书')).toHaveAttribute('aria-expanded', 'false')
  await expect(toggle('拆书精髓')).toHaveAttribute('aria-expanded', 'false')
  // Keep the default state intact; use a tall real viewport so all group
  // headers are visible together instead of collapsing unrelated groups.
  const directoryHeight = await catalog().evaluate(nav => window.innerHeight + nav.scrollHeight - nav.clientHeight + 80)
  await page.setViewportSize({ width: 1700, height: Math.ceil(directoryHeight) })
  await expect(toggle('拆书')).toBeInViewport()
  await expect(toggle('拆书精髓')).toBeInViewport()
  await shot('01-目录默认收起.png')
  check('真实目录分组、先后、79 份计数（含写书的标准）与拆书两组默认收起')

  await page.setViewportSize({ width: 1700, height: 1100 })
  const before = (await json('/prompts/chat_manner')).last_call?.id ?? 0
  const message = '请简单说一句，你会怎样帮助作者？'
  // 主编群聊自任务1起故意不再引用旧提示词。用仍走这些提示词的真实
  // 私聊生成记录，继续逐项验提示词页的「一起发的」与调用详情。
  const note = await json(`/books/${fixture.book}/notes`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ content: message, to: 'chief' }),
  })
  await expect.poll(async () => (await json(`/books/${fixture.book}/meeting?limit=2000`)).find(row => row.payload?.reply_to?.includes(note.id))?.content ?? '', { timeout: 30000 }).not.toBe('')
  await expect.poll(async () => (await json('/prompts/chat_manner')).last_call?.id ?? 0, { timeout: 30000 }).toBeGreaterThan(before)
  const manner = await json('/prompts/chat_manner')
  assert.equal(manner.last_call.purpose, '聊天·主编')
  assert.deepEqual(manner.last_call.used_prompts.parts.system.map(prompt => prompt.name), ['persona_chief', 'chat_voice', 'voice_chief', 'chat_reply', 'chat_manner', 'rules'])
  assert.deepEqual(manner.last_call.used_prompts.parts.user.map(prompt => prompt.name), ['chat_material'])
  call = await json(`/llm-calls/${manner.last_call.id}`)
  assert.deepEqual(call.used_prompts, manner.last_call.used_prompts)
  assert.equal(call.model, 'demo', '私聊必须使用演示模型，不调真实模型')
  await page.goto(`${base}/prompts?template=chat_manner`)
  await expect(heading()).toHaveText('聊天的做法')
  await expect(companions().locator('.used-prompts-row').nth(0)).toHaveText('系统提示主编人设 → 口吻怎么用 → 主编口吻 → 私聊和重新回答 → 聊天的做法 → 通用规则')
  await expect(companions().locator('.used-prompts-row').nth(1)).toHaveText('用户提示聊天带的资料')
  await expect(companions().locator('strong')).toHaveText('聊天的做法')
  await shot('02-聊天的做法一起发的.png')
  await toggle('角色与规矩').click()
  await expect(toggle('角色与规矩')).toHaveAttribute('aria-expanded', 'false')
  await companions().getByRole('button', { name: '主编口吻', exact: true }).click()
  await expect(heading()).toHaveText('主编口吻')
  await expect(toggle('角色与规矩')).toHaveAttribute('aria-expanded', 'true')
  await expect(catalog().getByRole('button', { name: '主编口吻', exact: true })).toBeInViewport()
  check('真实演示模型私聊记录、系统/用户提示顺序与一起发的跨组跳转')

  await page.goto(`${base}/prompts?template=chat_material`)
  await expect(heading()).toHaveText('聊天带的资料')
  await expect(page.locator('.template-variables')).toHaveCount(0)
  await page.getByRole('button', { name: '修改', exact: true }).click()
  const editor = page.getByTestId('prompt-editor').locator('.cm-content')
  await editor.click()
  await editor.press('Control+End')
  await page.keyboard.insertText('\n\n独立验收临时草稿，验收后恢复原内容。')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('已保存，从下一步调用起对所有书生效。', { exact: true })).toBeVisible()
  await expect(page.locator('.prompt-version')).toHaveText('改过')
  await page.getByRole('button', { name: '修改', exact: true }).click()
  await expect(page.locator('.template-actions').getByRole('button')).toHaveText(['恢复默认', '取消', '保存'])
  await expect(page.locator('.template-variables')).toBeVisible()
  await shot('03-改过的提示词修改态.png')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByRole('button', { name: '修改', exact: true })).toBeVisible()
  check('真实保存后标改过，修改态按钮和可用变量；取消返回只读')

  await page.goto(`${base}/prompts?template=chat_manner`)
  await companions().getByRole('button', { name: '查看这次调用', exact: true }).click()
  const detail = page.getByRole('dialog', { name: '调用详情', exact: true })
  await expect(detail.getByRole('heading', { name: '用到的提示词', exact: true })).toBeVisible()
  await expect(detail.locator('.used-prompts-row').nth(0)).toHaveText('系统提示主编人设 → 口吻怎么用 → 主编口吻 → 私聊和重新回答 → 聊天的做法 → 通用规则')
  await shot('04-调用详情用到的提示词.png')
  await detail.getByRole('button', { name: '口吻怎么用', exact: true }).click()
  await expect(detail).toHaveCount(0)
  await expect(page.getByRole('tab', { name: '提示词', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(heading()).toHaveText('口吻怎么用')
  check('真实调用详情按段显示来源，点名字关闭详情并选中提示词')
  assert.deepEqual(pageErrors, [])
  assert.deepEqual(forbiddenRequests, [])
  assert.deepEqual(await fingerprint(), sourceSha256, '验收期间源码改变，必须重跑稳定版本')
  succeeded = true
} finally {
  if (!succeeded) await page.screenshot({ path: path.join(root, 'data/prompts-page/browser-failed.png'), fullPage: true }).catch(() => {})
  await json('/prompts/chat_material', original.customized
    ? { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ content: original.content }) }
    : { method: 'DELETE' })
  assert.equal((await json('/prompts/chat_material')).content, original.content, '独立环境临时改动也要恢复')
  await fs.writeFile(path.join(out, '任务1-真实浏览器验收.json'), JSON.stringify({ base, api, book: fixture.book, sourceSha256, groups, checks, screenshots, call_id: call?.id, call_model: call?.model, call_method: call?.request?.method, used_prompts: call?.used_prompts, pageErrors, forbiddenRequests, realModelCalls: 0, promptRestored: true, ok: succeeded }, null, 2) + '\n')
  await browser.close()
}
