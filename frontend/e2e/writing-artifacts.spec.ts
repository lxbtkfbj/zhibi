/** 任务 4 的最小界面回归：拦截全部 API，仅使用内存稿件，绝不访问作者数据库。 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import type { BookDetail, Job, MeetingMessage, Volume } from '../src/api/types'

const bookId = 'writing-artifacts-mock'
const root = `/books/${bookId}`
const evidence = path.resolve('../docs/第一包验收')
const oldTitle = '旧章纲：保留没有情绪数据的历史稿件'
const newTitle = '新章纲：情绪落点与本章揭晓'
const auditTitle = '第二卷专项审稿：五项检查'

function artifact(id: number, type: string, content: string, data: unknown): MeetingMessage {
  return {
    id, book_id: bookId, job_id: 'writing-artifacts-job',
    speaker: type === 'volume_audit' ? 'reviewer' : 'chief',
    speaker_name: type === 'volume_audit' ? '审稿' : '主编',
    kind: 'artifact', content, payload: { type, data }, created_at: '2026-10-01T08:00:00Z',
  }
}

async function mockWriting(page: Page) {
  const job: Job = {
    id: 'writing-artifacts-job', book_id: bookId, kind: 'write_book', status: 'waiting_author',
    pending: {
      kind: 'volume_review', volume: 2, title: '古城对质',
      // 只有冲突文本；调整文字必须由结构化提议生成，避免测试只证明原样显示一个字符串。
      issues: ['节点冲突：下一处铁钉要求保留证人，卷纲不得安排证人提前退场。'],
      node_update: {
        node_id: 'pencil-node', index: 3,
        current: { title: '夜探古城', event: '潜入古城', prerequisite: '取得密道图', consequence: '找到证据' },
        proposed: { title: '当众举证', event: '在城门口展示账册', prerequisite: '证人愿意出面', consequence: '旧敌失势' },
        reason: '前文已经取得证据，改为公开对质更自然',
      },
    },
    error: '', created_at: '', updated_at: '', finished_at: null,
  }
  const book: BookDetail = {
    id: bookId, title: '写作接入展示回归', source: 'new', genre: '玄幻', status: 'writing',
    idea: '', logline: '只读展示用模拟书，不属于作者数据库。', job_status: 'waiting_author',
    created_at: '', updated_at: '', style_reference: '', concept: {}, spine: {}, setup_progress: {},
    requirements: [], trial_read_done: true, active_job: job, chapters_final: 10, words_final: 30000,
  }
  const volume: Volume = {
    id: 'volume-two', index: 2, title: '古城对质', stage: '古城', summary: '循着已完成的前文安排公开对质。',
    goal: '在卷末取得继续追查的入口', climax: '当众举证', antagonist: '守城长老', power_range: '练气后期',
    thread_beats: [], new_characters: [], chapter_count: 6, status: 'detailed', recap: '', units: [],
    target_node_id: 'pencil-node', reaches_node: true, editor_note: '', techniques: [],
  }
  const messages = [
    artifact(201, 'chapter_plan', oldTitle, {
      unit: '第2卷第1单元「旧稿」',
      chapters: [{ index: 11, title: '旧稿没有情绪字段', hook: '保留原章纲，不补造情绪' }],
    }),
    artifact(202, 'chapter_plan', newTitle, {
      unit: '第2卷第2单元「当众举证」',
      chapters: [
        { index: 12, title: '众目之下', hook: '证人推开城门', emotion: -1, mood: '虐', reveals: [] },
        { index: 13, title: '账册揭晓', hook: '下一封密信现身', emotion: 2, mood: '爽', reveals: [{ ref: 'S2', to: '柳如烟', how: '在众人面前核对账册，识破主角的伪装' }] },
      ],
    }),
    artifact(203, 'volume_audit', auditTitle, {
      volume: 2, verdict: 'pass',
      checks: [
        { aspect: 'villain', ok: true, comment: '对手提前设下后手' },
        { aspect: 'rhythm', ok: true, comment: '卷末是最大高潮' },
        { aspect: 'foreshadow', ok: true, comment: '旧账册的线索有回收' },
        { aspect: 'repetition', ok: true, comment: '破局方式与前卷不同' },
        { aspect: 'expectation', ok: true, comment: '三年之约的兑现超出预期' },
      ],
      issues: [],
    }),
  ]
  const unexpected: string[] = []
  const writes: string[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, '')
    const method = request.method()
    const reply = (json: unknown) => route.fulfill({ status: 200, json })
    if (method !== 'GET') writes.push(`${method} ${pathname}`)
    if (pathname === `${root}/events` && method === 'GET') {
      // 通过真正的 EventSource 消息解析路径注入稿件；延后重连，避免静态流关闭后反复拉取。
      const body = 'retry: 3600000\n\n' + messages.map(message => `id: ${message.id}\nevent: message\ndata: ${JSON.stringify(message)}\n\n`).join('')
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body })
    }
    if (pathname === root && method === 'GET') return reply(book)
    if (pathname === `${root}/outline` && method === 'GET') return reply({ concept: {}, volumes: [volume] })
    if (pathname === `${root}/bible` && method === 'GET') return reply({ characters: [], relationships: [], world_entries: [], foreshadowings: [], secrets: [] })
    if ([`${root}/nodes`, `${root}/secrets`, `${root}/threads`, `${root}/chapters`].includes(pathname) && method === 'GET') return reply([])
    if (pathname === `${root}/usage` && method === 'GET') return reply({ calls: 0, prompt_tokens: null, completion_tokens: null, by_role: {} })
    if (pathname === `/jobs/${job.id}` && method === 'GET') return reply(job)
    if (pathname === '/health' && method === 'GET') return reply({ status: 'ok', components: {} })
    if (pathname === '/glossary' && method === 'GET') return reply({ terms: [] })
    // 没有 route.continue 或 fallback，未预期请求也不能碰到真实服务。
    unexpected.push(`${method} ${pathname}`)
    return route.fulfill({ status: 404, json: { detail: `未模拟接口：${method} ${pathname}` } })
  })
  return { unexpected, writes }
}

async function openArtifact(page: Page, id: number, title: string) {
  const card = page.getByTestId(`artifact-message-${id}`)
  await card.getByRole('button', { name: `展开${title}`, exact: true }).click()
  await expect(card.getByRole('button', { name: `收起${title}`, exact: true })).toHaveAttribute('aria-expanded', 'true')
  return card
}

async function noHorizontalOverflow(locator: Locator) {
  expect(await locator.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
}

async function screenshot(page: Page, name: string) {
  await page.screenshot({ path: path.join(evidence, `任务4-补充-${name}.png`), fullPage: true })
}

test.beforeEach(async ({ page }) => {
  await mkdir(evidence, { recursive: true })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  page.on('pageerror', error => { throw error })
})

test('章纲产出：旧稿不虚构零分，新稿显示正负情绪及揭晓', async ({ page }) => {
  const state = await mockWriting(page)
  await page.goto(`${root}/volume/2`)
  const old = await openArtifact(page, 201, oldTitle)
  await expect(old).toContainText('旧稿没有情绪字段')
  await expect(old.locator('[aria-label^="情绪 "]')).toHaveCount(0)
  await expect(old).not.toContainText('0 悬')
  await expect(old).not.toContainText('0 爽')
  const current = await openArtifact(page, 202, newTitle)
  await expect(current.getByLabel('情绪 -1，主情绪 虐', { exact: true })).toHaveText('-1 虐')
  await expect(current.getByLabel('情绪 2，主情绪 爽', { exact: true })).toHaveText('+2 爽')
  await expect(current).toContainText('揭晓：S2 → 柳如烟 · 在众人面前核对账册，识破主角的伪装')
  await current.scrollIntoViewIfNeeded()
  await screenshot(page, '旧新章纲与揭晓')
  expect(state.unexpected).toEqual([])
  expect(state.writes).toEqual([])
})

test('专项审稿五项中文展示，拍板条同时说明节点调整与冲突', async ({ page }) => {
  const state = await mockWriting(page)
  await page.goto(`${root}/volume/2`)
  const audit = await openArtifact(page, 203, auditTitle)
  for (const label of ['反派智商', '爽点节奏', '伏笔排期', '套路重复', '期待感']) {
    await expect(audit.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(audit.locator('li')).toHaveCount(5)
  await expect(audit).not.toContainText('expectation')
  const issues = page.getByTestId('decision-bar').getByRole('list', { name: '卷纲与章节提醒' })
  await expect(issues).toContainText('节点冲突：下一处铁钉要求保留证人')
  await expect(issues).toContainText('节点调整：暂定节点 3「夜探古城」拟改为「当众举证」')
  await expect(issues).toContainText('批准卷纲后应用')
  await expect(issues.locator('li')).toHaveCount(2)
  await screenshot(page, '五项审稿与节点拍板')
  expect(state.unexpected).toEqual([])
  expect(state.writes).toEqual([])
})

test('390 像素暗色：情绪揭晓、五项审稿与节点提醒可见且不横溢', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'ink', reducedMotion: true })))
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  const state = await mockWriting(page)
  await page.goto(`${root}/volume/2`)
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ink')
  const current = await openArtifact(page, 202, newTitle)
  const emotion = current.getByLabel('情绪 2，主情绪 爽', { exact: true })
  await emotion.scrollIntoViewIfNeeded()
  await expect(emotion).toBeVisible()
  await expect(current.getByText('揭晓：S2 → 柳如烟 · 在众人面前核对账册，识破主角的伪装', { exact: true })).toBeVisible()
  expect(await emotion.evaluate(element => {
    const style = getComputedStyle(element)
    return style.color !== style.backgroundColor && style.color !== 'rgba(0, 0, 0, 0)' && Number(style.opacity) > 0
  })).toBe(true)
  await noHorizontalOverflow(page.locator('html'))
  await noHorizontalOverflow(page.getByTestId('conversation-pane'))
  await noHorizontalOverflow(current)
  await screenshot(page, '窄屏暗色章纲')
  await current.getByRole('button', { name: `收起${newTitle}`, exact: true }).click()
  const audit = await openArtifact(page, 203, auditTitle)
  await audit.getByText('期待感', { exact: true }).scrollIntoViewIfNeeded()
  await expect(audit.getByText('期待感', { exact: true })).toBeVisible()
  await noHorizontalOverflow(audit)
  await screenshot(page, '窄屏暗色审稿')
  await page.getByRole('tab', { name: '稿件', exact: true }).click()
  const bar = page.getByTestId('decision-bar')
  await expect(bar).toBeVisible()
  await expect(bar.getByText(/节点调整：暂定节点 3/)).toBeVisible()
  await expect(bar.getByText(/节点冲突：下一处铁钉/)).toBeVisible()
  await noHorizontalOverflow(page.locator('html'))
  await noHorizontalOverflow(page.getByRole('main', { name: '稿件' }))
  await noHorizontalOverflow(bar)
  await screenshot(page, '窄屏暗色节点拍板')
  expect(state.unexpected).toEqual([])
  expect(state.writes).toEqual([])
})
