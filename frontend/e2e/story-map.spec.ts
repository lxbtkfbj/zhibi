/** 真后端验收：仅在专用演示数据库、Redis 和提示词覆盖目录上显式运行。 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import type { BookDetail, Job, StoryNode } from '../src/api/types'

const evidence = resolve('../docs/第一包验收')
const enabled = process.env.ZHIBI_STORY_MAP_ACCEPTANCE === '1'

async function json<T>(request: APIRequestContext, path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await request.fetch(`/api${path}`, { method, ...(body === undefined ? {} : { data: body }) })
  expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy()
  return response.status() === 204 ? undefined as T : response.json()
}

async function settled(request: APIRequestContext, id: string, approve = false): Promise<Job> {
  const deadline = Date.now() + 8 * 60_000
  while (Date.now() < deadline) {
    const job = await json<Job>(request, `/jobs/${id}`)
    expect(job.status, job.error || '任务不应失败或取消').not.toMatch(/failed|cancelled/)
    if (job.status === 'succeeded') return job
    if (job.status === 'waiting_author') {
      expect(job.pending?.kind, '验收流程不接受正文卡住后强制定稿').not.toBe('chapter_stuck')
      if (!approve) return job
      expect(['setup_review', 'volume_review', 'trial_read']).toContain(job.pending?.kind)
      await json(request, `/jobs/${id}/decision`, 'POST', { action: 'approve', feedback: '' })
    }
    await new Promise((done) => setTimeout(done, 600))
  }
  throw new Error(`等待演示任务 ${id} 超时`)
}

async function manuscript(page: Page) {
  const tab = page.getByRole('tab', { name: '稿件', exact: true })
  if (await tab.isVisible()) await tab.click()
  await expect(page.getByRole('main', { name: '稿件' })).toBeVisible()
}

async function screenshot(page: Page, suffix: string) {
  await page.screenshot({ path: resolve(evidence, `任务1-${suffix}.png`), fullPage: true })
}

test('任务 1：演示开书、三章续写、节点编辑和术语表真实验收', async ({ page, request, baseURL }) => {
  test.skip(!enabled, '只在显式指定的独立演示实例运行，不访问作者数据库')
  test.setTimeout(12 * 60_000)
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1')
  expect(new URL(baseURL!).port).toBe('4336')
  await mkdir(evidence, { recursive: true })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))

  const profiles = await json<Array<{ provider: string }>>(request, '/llm/profiles')
  expect(profiles.length).toBeGreaterThan(0)
  expect(profiles.every((profile) => profile.provider === 'demo')).toBeTruthy()
  const created = await json<{ book: BookDetail; job: Job }>(request, '/books', 'POST', {
    idea: '第一包任务 1 独立演示验收：一个少年得到残缺古镜，从山城追查身世，最终揭开天幕背后的真相。',
    style_reference: '', ask: false,
  })
  const bookId = created.book.id
  console.log(`STORY_MAP_ACCEPTANCE_BOOK_ID=${bookId}`)
  const review = await settled(request, created.job.id)
  expect(review.pending?.kind).toBe('setup_review')
  await json(request, `/jobs/${created.job.id}/decision`, 'POST', { action: 'approve', feedback: '' })
  await settled(request, created.job.id, true)

  let nodes = await json<StoryNode[]>(request, `/books/${bookId}/nodes`)
  expect(nodes[0].kind).toBe('opening')
  expect(nodes.at(-1)?.kind).toBe('ending')
  expect(nodes.filter((node) => node.kind === 'milestone').length).toBeGreaterThan(0)
  expect(nodes.map((node) => node.index)).toEqual(nodes.map((_, i) => i + 1))

  await page.goto(`/books/${bookId}/spine`)
  await manuscript(page)
  const node = nodes.find((item) => item.kind === 'milestone')!
  const card = page.getByTestId(`story-node-${node.id}`)
  await expect(card).toContainText('暂定')
  const edits = {
    title: '作者验收：古镜醒来',
    event: '古镜第一次映出天幕裂纹，少年决定追查身世。',
    prerequisite: '少年先找到古镜，并取得同行者的信任。',
    consequence: '少年得知线索不止在山城，决定动身远行。',
  }
  for (const [index, field] of (['title', 'event', 'prerequisite', 'consequence'] as const).entries()) {
    await card.getByRole('button').nth(index).click()
    const editor = card.getByRole('textbox')
    await editor.fill(edits[field])
    const saved = page.waitForResponse((response) => response.url().endsWith(`/api/nodes/${node.id}`) && response.request().method() === 'PATCH')
    await editor.press('Control+Enter')
    expect((await saved).status()).toBe(200)
    await expect(card.getByText(edits[field], { exact: true })).toBeVisible()
  }
  nodes = await json<StoryNode[]>(request, `/books/${bookId}/nodes`)
  expect(nodes.find((item) => item.id === node.id)).toMatchObject({ ...edits, status: 'pencil' })
  await page.reload()
  await manuscript(page)
  await expect(card.getByText(edits.title, { exact: true })).toBeVisible()
  await card.scrollIntoViewIfNeeded()
  await screenshot(page, '节点编辑-桌面')

  await page.setViewportSize({ width: 390, height: 844 })
  await manuscript(page)
  await card.scrollIntoViewIfNeeded()
  await expect(card.getByText(edits.event, { exact: true })).toBeVisible()
  const pane = page.getByRole('main', { name: '稿件' })
  expect(await pane.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy()
  await screenshot(page, '节点编辑-窄屏')
  await page.setViewportSize({ width: 1440, height: 1000 })

  const writing = await json<Job>(request, `/books/${bookId}/write`, 'POST', { until: 'count', count: 3 })
  await settled(request, writing.id, true)
  const book = await json<BookDetail>(request, `/books/${bookId}`)
  expect(book.chapters_final).toBe(3)
  const chapters = await json<Array<{ index: number; status: string }>>(request, `/books/${bookId}/chapters`)
  expect(chapters.filter((chapter) => chapter.status === 'final').map((chapter) => chapter.index)).toEqual([1, 2, 3])
  await page.goto(`/books/${bookId}/chapters`)
  await manuscript(page)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('第3章')
  await screenshot(page, '演示前三章')

  await page.goto(`/books/${bookId}`)
  await manuscript(page)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText(nodes[0].event)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText(nodes.at(-1)!.event)

  const bible = await json<{ foreshadowings: { code: string }[]; characters: { name: string }[] }>(request, `/books/${bookId}/bible`)
  expect(bible.foreshadowings.length).toBeGreaterThan(0)
  expect(bible.foreshadowings.every((item) => /^F\d+$/.test(item.code))).toBeTruthy()
  await page.goto(`/books/${bookId}/foreshadowing`)
  await manuscript(page)
  await expect(page.getByRole('main', { name: '稿件' }).getByText(bible.foreshadowings[0].code, { exact: true })).toBeVisible()
  await screenshot(page, '伏笔编号')

  await page.goto(`/books/${bookId}/characters`)
  await manuscript(page)
  await page.getByRole('main', { name: '稿件' }).getByText(bible.characters[0].name, { exact: true }).click()
  await expect(page.getByRole('dialog').getByText('秘密', { exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')

  const original = await json<{ content: string; customized: boolean }>(request, '/prompts/glossary')
  let glossaryChanged = false
  try {
    await page.goto('/prompts')
    await page.getByRole('button', { name: '术语表', exact: true }).click()
    await expect(page.getByRole('heading', { name: '术语表', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '自定义', exact: true }).click()
    const editor = page.getByTestId('prompt-editor').locator('.cm-content')
    await editor.click()
    await editor.press('Control+End')
    await page.keyboard.insertText('\n\n第一包任务 1 验收临时说明：可编辑并恢复。')
    const saved = page.waitForResponse((response) => response.url().endsWith('/api/prompts/glossary') && response.request().method() === 'PUT')
    await page.getByRole('button', { name: '保存', exact: true }).click()
    expect((await saved).status()).toBe(200)
    glossaryChanged = true
    await expect(page.getByText('已保存，从下一步调用起对所有书生效。')).toBeVisible()
    const persisted = await json<{ content: string }>(request, '/prompts/glossary')
    expect(persisted.content).toContain('可编辑并恢复')
    await expect(page.getByText('服务正常', { exact: true })).toBeVisible()
    await screenshot(page, '术语表编辑')

    await page.getByRole('button', { name: '自定义', exact: true }).click()
    await editor.click()
    await editor.press('Control+Home')
    await editor.press('Control+Shift+End')
    await page.keyboard.insertText('## 术语一\n白话解释一。\n\n## 术语二\n白话解释二。\n\n## 术语三\n白话解释三。')
    const rejected = page.waitForResponse((response) => response.url().endsWith('/api/prompts/glossary') && response.request().method() === 'PUT')
    await page.getByRole('button', { name: '保存', exact: true }).click()
    expect((await rejected).status()).toBe(422)
    await expect(page.getByRole('status')).toContainText('术语')
    expect((await json<{ content: string }>(request, '/prompts/glossary')).content).toBe(persisted.content)
    await screenshot(page, '术语不足拒绝保存')
  } finally {
    if (glossaryChanged) {
      if (original.customized) await json(request, '/prompts/glossary', 'PUT', { content: original.content })
      else await json(request, '/prompts/glossary', 'DELETE')
      expect((await json<{ content: string }>(request, '/prompts/glossary')).content).toBe(original.content)
    }
  }
  expect(errors).toEqual([])
  await writeFile(resolve(evidence, '任务1-浏览器结果.json'), JSON.stringify({
    book_id: bookId, chapters_final: book.chapters_final, nodes: nodes.length,
    edited_node_id: node.id, original_node_status_preserved: true,
    viewports: ['1440x1000', '390x844'], glossary_restored: true, page_errors: errors,
  }, null, 2), 'utf8')
})
