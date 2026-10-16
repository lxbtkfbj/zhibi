/** 任务 4：独立演示数据库的真实 HTTP / Celery / 浏览器验收，不使用作者实例。 */
import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import type { BookDetail, ChapterBrief, Job, MeetingMessage, Outline, Secret, StoryNode } from '../src/api/types'

const evidence = path.resolve('../docs/第一包验收')
async function call<T>(request: APIRequestContext, method: 'GET' | 'POST' | 'PATCH', route: string, data?: unknown): Promise<T> {
  const response = await request.fetch(`/api${route}`, { method, data })
  expect(response.ok(), `${route}: ${await response.text()}`).toBeTruthy()
  return response.json()
}
const get = <T>(request: APIRequestContext, route: string) => call<T>(request, 'GET', route)
async function settled(request: APIRequestContext, id: string, kind?: string) {
  let job: Job
  await expect.poll(async () => {
    job = await get<Job>(request, `/jobs/${id}`)
    if (job.status === 'failed') throw new Error(job.error)
    return ['waiting_author', 'succeeded'].includes(job.status) && (!kind || job.pending?.kind === kind)
  }, { timeout: 300_000, intervals: [100, 250, 500] }).toBe(true)
  return job!
}
async function approve(request: APIRequestContext, id: string) {
  await call(request, 'POST', `/jobs/${id}/decision`, { action: 'approve' })
  return settled(request, id)
}
async function create(request: APIRequestContext, idea: string) {
  const result = await call<{ book: BookDetail; job: Job }>(request, 'POST', '/books', { idea, ask: false, mode: 'oneshot' })
  await settled(request, result.job.id, 'setup_review')
  expect((await approve(request, result.job.id)).status).toBe('succeeded')
  return result.book
}
async function shot(page: Page, name: string) {
  await fs.mkdir(evidence, { recursive: true })
  await page.waitForTimeout(350)
  await page.screenshot({ path: path.join(evidence, `任务4-${name}.png`) })
}
async function showArtifact(page: Page, message: MeetingMessage) {
  const card = page.getByTestId(`artifact-message-${message.id}`)
  await card.scrollIntoViewIfNeeded()
  const toggle = card.getByRole('button', { name: `展开${message.content}`, exact: true })
  if (await toggle.count()) await toggle.click()
  await card.scrollIntoViewIfNeeded()
  await expect(card).toBeVisible()
  return card
}

test('任务4：写完第一卷、章纲情绪揭晓、信息差重写撤销、第二卷节点批准', async ({ page, request, baseURL }) => {
  test.setTimeout(900_000)
  expect(new URL(baseURL!).port).toBe('4338')
  expect((await get<{ provider: string }[]>(request, '/llm/profiles')).every(profile => profile.provider === 'demo')).toBe(true)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const book = await create(request, '第一包任务4验收：少年陆远持青灯，靠信息差和证据在宗门中破局。')
  const write = await call<Job>(request, 'POST', `/books/${book.id}/write`, { until: 'volume', count: 1 })
  await settled(request, write.id, 'trial_read')
  expect((await approve(request, write.id)).status).toBe('succeeded')
  const chapters = await get<ChapterBrief[]>(request, `/books/${book.id}/chapters?volume=1`)
  expect(chapters.length).toBe(31)
  expect(chapters.every(chapter => chapter.status === 'final' && typeof chapter.outline?.emotion === 'number')).toBe(true)
  const outline = await get<Outline>(request, `/books/${book.id}/outline`)
  expect(outline.volumes[0].status).toBe('done')
  expect(outline.volumes[0].recap).toBeTruthy()
  const reveals = chapters.filter(chapter => chapter.outline?.reveals?.length)
  expect(reveals.length).toBeGreaterThan(0)
  const revealed = reveals[0]
  const reveal = revealed.outline!.reveals![0]
  const before = await get<Secret[]>(request, `/books/${book.id}/secrets`)
  const secret = before.find(item => item.code === reveal.ref)!
  expect(secret.knowers.some(knower => knower.name === reveal.to && knower.since_chapter === revealed.index)).toBe(true)
  await page.goto(`/books/${book.id}/secrets`)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText(reveal.to)
  await shot(page, '01-揭晓后知情人')
  const messages = await get<MeetingMessage[]>(request, `/books/${book.id}/meeting?limit=2000`)
  const plan = messages.find(message => message.payload?.type === 'chapter_plan' && (message.payload.data as { chapters: { reveals?: unknown[] }[] }).chapters.some(chapter => chapter.reveals?.length))!
  const card = await showArtifact(page, plan)
  await expect(card).toContainText('揭晓：')
  await expect(card.locator('[aria-label^="情绪"]')).not.toHaveCount(0)
  await shot(page, '02-章纲情绪与揭晓')

  // 持续读真实接口，捕捉重写先撤销、再提取的中间状态，不把重写后重新获知误认为未撤销。
  const rewrite = await call<Job>(request, 'POST', `/books/${book.id}/chapters/${revealed.index}/rewrite`, { feedback: '保留揭晓，但把知道真相的过程写清楚。', confirm: true })
  let reverted: Secret[] = []
  await expect.poll(async () => {
    const current = await get<Secret[]>(request, `/books/${book.id}/secrets`)
    const item = current.find(item => item.id === secret.id)!
    if (!item.knowers.some(knower => knower.name === reveal.to && knower.since_chapter === revealed.index)) { reverted = current; return true }
    return false
  }, { timeout: 30_000, intervals: [25, 50] }).toBe(true)
  expect((await settled(request, rewrite.id)).status).toBe('succeeded')
  const afterRewrite = await get<Secret[]>(request, `/books/${book.id}/secrets`)
  expect(afterRewrite.find(item => item.id === secret.id)!.knowers.some(knower => knower.name === reveal.to && knower.since_chapter === revealed.index)).toBe(true)
  const rewrittenMessages = await get<MeetingMessage[]>(request, `/books/${book.id}/meeting?limit=2000`)
  expect(rewrittenMessages.some(message => message.job_id === rewrite.id && message.content.includes('信息差 1 条'))).toBe(true)
  await page.reload()
  const revoke = page.getByText(/设定师先撤掉了第.*信息差 1 条/).first()
  await revoke.scrollIntoViewIfNeeded()
  await shot(page, '03-重写信息差撤销回执')

  const second = outline.volumes[1]
  const nodes = await get<StoryNode[]>(request, `/books/${book.id}/nodes`)
  const originalNode = nodes.find(node => node.id === second.target_node_id)!
  expect(originalNode.status).toBe('pencil')
  await call(request, 'PATCH', `/volumes/${second.id}`, { title: `测试节点调整·${second.title}` })
  const next = await call<Job>(request, 'POST', `/books/${book.id}/write`, { until: 'count', count: 1 })
  const waiting = await settled(request, next.id, 'volume_review')
  expect(waiting.pending?.kind).toBe('volume_review')
  if (waiting.pending?.kind !== 'volume_review') throw new Error('missing volume gate')
  expect(waiting.pending.node_update?.node_id).toBe(originalNode.id)
  expect(waiting.pending.node_update?.current.title).toBe(originalNode.title)
  expect((await get<StoryNode[]>(request, `/books/${book.id}/nodes`)).find(node => node.id === originalNode.id)!.title).toBe(originalNode.title)
  const volumeCalls = await get<{ items: { id: number; purpose: string }[] }>(request, `/llm-calls?book_id=${book.id}&limit=100`)
  const targetContexts: { purpose: string; containsTarget: boolean }[] = []
  for (const purpose of ['写作·第2卷比稿方向', '写作·第2卷方案1', '写作·第2卷专项审稿']) {
    const recorded = volumeCalls.items.find(call => call.purpose === purpose)!
    expect(recorded).toBeTruthy()
    const detail = await get<{ request: unknown }>(request, `/llm-calls/${recorded.id}`)
    expect(JSON.stringify(detail.request)).toContain(originalNode.title)
    expect(JSON.stringify(detail.request)).toContain(originalNode.prerequisite)
    targetContexts.push({ purpose, containsTarget: true })
  }
  await page.goto(`/books/${book.id}/volume/2`)
  await expect(page.getByTestId('decision-bar')).toContainText('节点调整：')
  await shot(page, '04-第二卷节点提议待批准')
  const secondMessages = await get<MeetingMessage[]>(request, `/books/${book.id}/meeting?limit=2000`)
  const audit = secondMessages.filter(message => message.job_id === next.id && message.payload?.type === 'volume_audit').at(-1)!
  const auditCard = await showArtifact(page, audit)
  for (const label of ['反派智商', '爽点节奏', '伏笔排期', '套路重复', '期待感']) await expect(auditCard).toContainText(label)
  await shot(page, '05-卷纲五项审稿')
  const decisionResponse = page.waitForResponse(response => response.url().endsWith(`/jobs/${next.id}/decision`) && response.request().method() === 'POST')
  await page.getByTestId('decision-bar').getByRole('button', { name: '批准开写', exact: true }).click()
  expect((await decisionResponse).ok()).toBe(true)
  expect((await settled(request, next.id)).status).toBe('succeeded')
  const updated = (await get<StoryNode[]>(request, `/books/${book.id}/nodes`)).find(node => node.id === originalNode.id)!
  expect(updated.title).toBe(waiting.pending.node_update!.proposed.title)
  expect(updated.updated_by_volume).toBe(2)
  expect(updated.status).toBe('pencil')
  expect(updated.origin).toBe('ai')
  await page.goto(`/books/${book.id}/spine`)
  await page.getByTestId(`story-node-${updated.id}`).scrollIntoViewIfNeeded()
  await shot(page, '06-批准后节点更新')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/books/${book.id}/volume/2`)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, '07-窄屏写作')
  expect(errors).toEqual([])
  await fs.writeFile(path.join(evidence, '任务4-主流程结果.json'), JSON.stringify({ bookId: book.id, firstVolumeJob: write.id, chapterCount: chapters.length, emotionCurve: chapters.map(chapter => ({ index: chapter.index, emotion: chapter.outline?.emotion, mood: chapter.outline?.mood })), revealChapter: revealed.index, reveal, before: secret, reverted: reverted.find(item => item.id === secret.id), afterRewrite: afterRewrite.find(item => item.id === secret.id), rewriteJob: rewrite.id, nextVolumeJob: next.id, targetContexts, pending: waiting.pending, originalNode, updatedNode: updated, browserErrors: errors }, null, 2))
})

test('任务4：坏节奏触发器仅重出一次并保存 plan_issues', async ({ page, request, baseURL }) => {
  test.setTimeout(240_000)
  expect(new URL(baseURL!).port).toBe('4338')
  const book = await create(request, '任务4节奏验收：从宗门中一步步揭开青灯身世。')
  const outline = await get<Outline>(request, `/books/${book.id}/outline`)
  const unit = outline.volumes[0].units[0]
  await call(request, 'PATCH', `/units/${unit.id}`, { title: `测试节奏·${unit.title}` })
  const write = await call<Job>(request, 'POST', `/books/${book.id}/write`, { until: 'count', count: 1 })
  expect((await settled(request, write.id)).status).toBe('succeeded')
  const final = await get<Outline>(request, `/books/${book.id}/outline`)
  const issues = final.volumes[0].units[0].plan_issues ?? []
  expect(issues.length).toBeGreaterThan(0)
  const calls = await get<{ items: { id: number; purpose: string }[] }>(request, `/llm-calls?book_id=${book.id}&limit=100`)
  const plans = calls.items.filter(call => call.purpose === '写作·章纲')
  expect(plans.length).toBe(2)
  const retry = await get<{ request: unknown }>(request, `/llm-calls/${plans[0].id}`)
  expect(JSON.stringify(retry.request)).toContain('当前章纲')
  expect(JSON.stringify(retry.request)).toContain('压抑')
  await page.goto(`/books/${book.id}/volume/1`)
  const messages = await get<MeetingMessage[]>(request, `/books/${book.id}/meeting`)
  const plan = messages.find(message => message.job_id === write.id && message.payload?.type === 'chapter_plan')!
  await showArtifact(page, plan)
  await shot(page, '08-坏节奏重出后章纲')
  await fs.writeFile(path.join(evidence, '任务4-节奏结果.json'), JSON.stringify({ bookId: book.id, jobId: write.id, planCallIds: plans.map(call => call.id), planIssues: issues, retryHasRevision: true }, null, 2))
})
