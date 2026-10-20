/** 第二批任务2：只读查看任务1真模型留下的60章结果；不开始/接着/重试，不发任何写请求。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = 'http://127.0.0.1:4407'
assert.equal(process.env.TEST_BASE_URL, base, '只允许本轮独立验收前端')
const bookId = 'c1163a46-0190-40a5-bf41-554889c2e7a9'
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/拆书第二批验收')
const evidencePath = path.join(root, 'data/teardown2-task2/real-ui.json')
await fs.mkdir(output, { recursive: true })
await fs.mkdir(path.dirname(evidencePath), { recursive: true })
const evidence = { base, bookId, checks: [], screenshots: [], pageErrors: [], writesBlocked: [], realModelCalls: 0 }
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const context = await browser.newContext({ viewport: { width: 1720, height: 1280 }, locale: 'zh-CN', reducedMotion: 'reduce', serviceWorkers: 'block' })
await context.route(url => url.pathname.startsWith('/api/'), async route => {
  if (route.request().method() !== 'GET') { evidence.writesBlocked.push({ method: route.request().method(), path: new URL(route.request().url()).pathname }); return route.abort() }
  return route.continue()
})
const page = await context.newPage()
page.on('pageerror', error => evidence.pageErrors.push(error.message))
const get = async suffix => { const response = await context.request.get(`${base}/api${suffix}`); assert.equal(response.status(), 200, suffix); return response.json() }
const shot = async name => { await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(200); await page.screenshot({ path: path.join(output, name) }); evidence.screenshots.push(`docs/拆书第二批验收/${name}`) }
try {
  const profiles = await get('/llm/profiles')
  assert.ok(profiles.every(profile => profile.provider === 'demo' && !profile.has_key), '独立库不含真实模型配置：空列表或无密钥demo模型')
  const before = await get(`/books/${bookId}`)
  assert.equal(before.source, 'teardown'); assert.equal(before.title, '逆天邪神'); assert.equal(before.teardown.upto, 60)
  assert.ok(!before.active_job || !['queued', 'running'].includes(before.active_job.status), '只读已停下的任务1结果')
  const chapters = await get(`/books/${bookId}/chapters`)
  assert.equal(chapters.filter(chapter => chapter.teardown?.read).length, 60)
  evidence.before = { title: before.title, stage: before.teardown.stage, upto: before.teardown.upto, total: chapters.length, read: 60, profiles: profiles.map(profile => ({ provider: profile.provider, has_key: profile.has_key })) }
  await page.goto(`${base}/desk/${bookId}`)
  await expect(page.getByTestId('teardown-progress-strip')).toContainText('拆到第 60 章了（你定的）。')
  await page.locator('header nav').getByRole('button', { name: '大纲', exact: true }).click()
  const outlineSearch = page.getByPlaceholder('找篇、卷、单元、章……')
  await outlineSearch.fill('迎娶夏倾月')
  await page.getByRole('button', { name: /单元一.*迎娶夏倾月/ }).first().click()
  await outlineSearch.fill('')
  await expect(page.locator('main')).toContainText('云澈重生为流云城废柴萧澈')
  await expect(page.locator('main')).toContainText('下面的章')
  await shot('task2-real-unit.png')
  evidence.checks.push('真实结果大纲单元标题、原有段落、章范围及下属章显示；截图不改结果')
  await page.locator('header nav').getByRole('button', { name: '正文', exact: true }).click()
  const chapterSearch = page.getByPlaceholder('找章节、搜原文……')
  await chapterSearch.fill('迎亲')
  await page.getByRole('button', { name: '第5章 迎亲', exact: true }).click()
  await chapterSearch.fill('')
  await expect(page.locator('.chapter-prose')).toBeVisible()
  const fold = page.getByRole('button', { name: '这一章记下的', exact: true })
  await expect(fold).toHaveAttribute('aria-expanded', 'false')
  await fold.click()
  for (const title of ['出场的人', '新冒出来的', '名场面', '读者在等的', '用了的桥段']) await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
  await fold.evaluate(button => button.scrollIntoView({ block: 'start' }))
  await page.locator('main').evaluate(main => { main.scrollTop = Math.max(0, main.scrollTop - 95) })
  await expect(page.getByText('也叫 萧澈、澈儿、姐夫', { exact: true })).toBeVisible()
  await shot('task2-real-records.png')
  evidence.checks.push('第5顺序章《迎亲》原有真实记录：默认折叠、别名小字、五段内容与名场面；未调用模型或修改原文')
  const after = await get(`/books/${bookId}`)
  assert.deepEqual(after.teardown, before.teardown)
  assert.equal(after.updated_at, before.updated_at)
  evidence.unchanged = true
  assert.deepEqual(evidence.pageErrors, [])
  assert.deepEqual(evidence.writesBlocked, [])
  console.log(JSON.stringify({ checks: evidence.checks.length, screenshots: evidence.screenshots, pageErrors: 0, writeRequests: 0, realModelCalls: 0 }))
} finally {
  await browser.close()
  await fs.writeFile(evidencePath, JSON.stringify(evidence, null, 2))
}
