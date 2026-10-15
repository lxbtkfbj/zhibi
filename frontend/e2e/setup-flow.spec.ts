/** 任务 2 真后端验收：只运行在独立的 4337 / 8017 演示实例。 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import type { Bible, BookDetail, Job, MeetingMessage, StoryNode } from '../src/api/types'

const evidence = resolve('../docs/第一包验收')

async function json<T>(request: APIRequestContext, path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await request.fetch(`/api${path}`, { method, ...(data === undefined ? {} : { data }) })
  expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy()
  return response.status() === 204 ? undefined as T : response.json()
}

async function settled(request: APIRequestContext, id: string, approve = false): Promise<Job> {
  const deadline = Date.now() + 8 * 60_000
  while (Date.now() < deadline) {
    const job = await json<Job>(request, `/jobs/${id}`)
    expect(job.status, job.error).not.toMatch(/failed|cancelled/)
    if (job.status === 'succeeded') return job
    if (job.status === 'waiting_author') {
      if (!approve) return job
      expect(['setup_review', 'volume_review', 'trial_read'], '不强行批准卡住的正文').toContain(job.pending?.kind)
      await json(request, `/jobs/${id}/decision`, 'POST', { action: 'approve' })
    }
    await new Promise(done => setTimeout(done, 600))
  }
  throw new Error('演示任务超时')
}

async function manuscript(page: Page) {
  const tab = page.getByRole('tab', { name: '稿件', exact: true })
  if (await tab.isVisible()) await tab.click()
  await expect(page.getByRole('main', { name: '稿件' })).toBeVisible()
}

async function screen(page: Page, name: string) {
  await page.screenshot({ path: resolve(evidence, `任务2-${name}.png`), fullPage: true })
}

test('任务 2：一口气开书、前三章、新结构入库与历史产出卡片', async ({ page, request, baseURL }) => {
  test.skip(process.env.ZHIBI_SETUP_FLOW_ACCEPTANCE !== '1', '必须显式启用独立演示实例验收')
  test.setTimeout(12 * 60_000)
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1')
  expect(new URL(baseURL!).port).toBe('4337')
  await mkdir(evidence, { recursive: true })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ reducedMotion: true })))
  const profiles = await json<{ provider: string }[]>(request, '/llm/profiles')
  expect(profiles.length).toBeGreaterThan(0)
  expect(profiles.every(profile => profile.provider === 'demo')).toBeTruthy()
  const defaults = await json<{ settings: { setup_mode: string } }>(request, '/settings/new-book-defaults')
  expect(defaults.settings.setup_mode).toBe('oneshot')
  const created = await json<{ book: BookDetail; job: Job }>(request, '/books', 'POST', {
    idea: '第一包任务 2 浏览器验收：少年借青灯窥见寿元，沿着身世线索从小城走向高天，逐步揭开被隐瞒的真相。', mode: 'oneshot', ask: false,
  })
  const bookId = created.book.id
  console.log(`SETUP_FLOW_ACCEPTANCE_BOOK_ID=${bookId}`)
  expect((await settled(request, created.job.id)).pending?.kind).toBe('setup_review')
  const nodes = await json<StoryNode[]>(request, `/books/${bookId}/nodes`)
  const bible = await json<Bible>(request, `/books/${bookId}/bible`)
  expect(nodes[0].kind).toBe('opening')
  expect(nodes.at(-1)?.kind).toBe('ending')
  expect(nodes.filter(node => node.kind === 'milestone').length).toBeGreaterThanOrEqual(6)
  expect(nodes.slice(1).every(node => node.prerequisite && node.consequence)).toBeTruthy()
  expect(nodes.some(node => node.anchors.length > 0)).toBeTruthy()
  expect(bible.secrets.length).toBeGreaterThanOrEqual(4)
  const expectations = bible.foreshadowings.filter(item => item.kind === '期待')
  expect(expectations.length).toBeGreaterThanOrEqual(2)
  expect(expectations.every(item => /^E\d+$/.test(item.code))).toBeTruthy()

  await page.goto(`/books/${bookId}`)
  await page.getByRole('link', { name: '完整主线 →', exact: true }).click()
  await manuscript(page)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('之前得先有')
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('之后变成')
  await screen(page, '一口气节点方案')
  const messages = await json<MeetingMessage[]>(request, `/books/${bookId}/meeting`)
  for (const [type, required, name] of [
    ['spine', '之前：', '会议关键节点'], ['lore', '人物锚点', '会议人物与信息差'], ['outline', '长线期待', '会议全书总纲与期待'],
  ]) {
    const message = messages.findLast(item => item.kind === 'artifact' && item.payload?.type === type)!
    expect(message).toBeTruthy()
    const card = page.getByTestId(`artifact-message-${message.id}`)
    await card.getByRole('button', { name: `展开${message.content}`, exact: true }).click()
    await expect(card).toContainText(required)
    if (type === 'lore') {
      await expect(card).toContainText('信息差')
      await card.getByText('信息差', { exact: true }).scrollIntoViewIfNeeded()
    } else if (type === 'outline') {
      await expect(card).toContainText('走向：节点')
      await card.getByText(/^长线期待：/).scrollIntoViewIfNeeded()
    } else await card.scrollIntoViewIfNeeded()
    await screen(page, name)
    await card.getByRole('button', { name: `收起${message.content}`, exact: true }).click()
  }
  await json(request, `/jobs/${created.job.id}/decision`, 'POST', { action: 'approve' })
  await settled(request, created.job.id, true)
  expect((await json<BookDetail>(request, `/books/${bookId}`)).setup_progress.pieces).toEqual({ concept: 'confirmed', nodes: 'confirmed', cast: 'confirmed', fill: 'confirmed', first_volume: 'confirmed' })
  const writing = await json<Job>(request, `/books/${bookId}/write`, 'POST', { until: 'count', count: 3 })
  await settled(request, writing.id, true)
  const book = await json<BookDetail>(request, `/books/${bookId}`)
  expect(book.chapters_final).toBe(3)
  await page.goto(`/books/${bookId}/chapters`)
  await manuscript(page)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('已定稿 3 章')
  await screen(page, '一口气前三章')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/books/${bookId}/spine`)
  await manuscript(page)
  const card = page.getByTestId(`story-node-${nodes[1].id}`)
  await card.scrollIntoViewIfNeeded()
  await expect(card).toContainText(nodes[1].title)
  expect(await page.getByRole('main', { name: '稿件' }).evaluate(el => el.scrollWidth <= el.clientWidth)).toBeTruthy()
  await screen(page, '节点方案窄屏')
  expect(errors).toEqual([])
  await writeFile(resolve(evidence, '任务2-浏览器结果.json'), JSON.stringify({ book_id: bookId, chapters_final: book.chapters_final, nodes: nodes.length, anchors: nodes.reduce((sum, node) => sum + node.anchors.length, 0), secrets: bible.secrets.length, expectations: expectations.length, page_errors: errors, viewports: ['1440x1000', '390x844'] }, null, 2), 'utf8')
})

test('任务 2：只读查看逐块方向产出', async ({ page, request, baseURL }) => {
  const bookId = process.env.ZHIBI_PUZZLE_READONLY_BOOK
  test.skip(!bookId, '仅检查显式提供的独立逐块验收书，不创建或修改任务')
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1')
  expect(new URL(baseURL!).port).toBe('4337')
  await mkdir(evidence, { recursive: true })
  const errors: string[] = []
  const writes: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', route => {
    if (route.request().method() === 'GET') return route.continue()
    writes.push(`${route.request().method()} ${route.request().url()}`)
    return route.abort()
  })
  await page.addInitScript(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ reducedMotion: true })))
  const messages = await json<MeetingMessage[]>(request, `/books/${bookId}/meeting`)
  const direction = messages.findLast(message => message.kind === 'artifact' && message.payload?.type === 'directions')!
  expect(direction).toBeTruthy()
  const data = direction.payload?.data as { directions?: { name: string }[] } | undefined
  const names = (data?.directions ?? []).map(item => item.name)
  expect(names).toHaveLength(3)
  // 较高的只读取证视口让三个方向完整入镜；不改变实际界面布局或作者偏好。
  await page.setViewportSize({ width: 1440, height: 1800 })
  await page.goto(`/books/${bookId}`)
  const card = page.getByTestId(`artifact-message-${direction.id}`)
  await card.getByRole('button', { name: `展开${direction.content}`, exact: true }).click()
  for (const [index, name] of names.entries()) await expect(card.getByText(`方向 ${index + 1}「${name}」`, { exact: true })).toBeVisible()
  await card.scrollIntoViewIfNeeded()
  await screen(page, '会议开书方向')
  expect(writes).toEqual([])
  expect(errors).toEqual([])
  await writeFile(resolve(evidence, '任务2-方向只读验收.json'), JSON.stringify({ book_id: bookId, directions: names, page_errors: errors, write_requests: writes }, null, 2), 'utf8')
})
