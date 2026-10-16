/** 任务 5：独立演示 API / Celery / PostgreSQL 的真实浏览器验收；不拦截 API。 */
import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import type { BookDetail, ChapterBrief, Job, Outline, StoryNode } from '../src/api/types'

const evidence = path.resolve('../docs/第一包验收')
const fixturesPath = process.env.ZHIBI_TASK5_FIXTURES || path.resolve('../data/first-package-task5/fixtures.json')
interface Fixtures {
  main: { bookId: string; writeJob: string }
  rhythm: { bookId: string; writeJob: string }
  adjust: { bookId: string; nextJob: string }
  puzzle: { bookId: string; jobId: string }
  legacy: { bookId: string; database: string; migration: string; chapters: { index: number; content: string; outline: unknown }[] }
}
let fixtures: Fixtures
async function call<T>(request: APIRequestContext, method: 'GET' | 'POST' | 'PATCH' | 'DELETE', route: string, data?: unknown): Promise<T> {
  const response = await request.fetch(`/api${route}`, { method, data })
  expect(response.ok(), `${route}: ${await response.text()}`).toBeTruthy()
  return response.status() === 204 ? undefined as T : response.json()
}
const get = <T>(request: APIRequestContext, route: string) => call<T>(request, 'GET', route)
async function settled(request: APIRequestContext, id: string, kind?: string, piece?: string) {
  let job: Job
  await expect.poll(async () => {
    job = await get<Job>(request, `/jobs/${id}`)
    if (job.status === 'failed') throw new Error(job.error)
    return ['waiting_author', 'succeeded'].includes(job.status) && (!kind || job.pending?.kind === kind) && (!piece || (job.pending?.kind === 'setup_piece' && job.pending.piece === piece))
  }, { timeout: 300_000, intervals: [100, 250, 500] }).toBe(true)
  return job!
}
async function shot(page: Page, name: string) {
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(evidence, `任务5-${name}.png`) })
}
async function record(name: string, data: unknown) {
  await fs.writeFile(path.join(evidence, `任务5-${name}.json`), JSON.stringify(data, null, 2))
}
function errors(page: Page) {
  const result: string[] = []
  page.on('pageerror', error => result.push(error.message))
  return result
}
async function manualPage(page: Page, bookId: string, suffix: string) {
  await page.goto(`/books/${bookId}`)
  const navigation = page.getByRole('navigation', { name: '书稿目录' })
  await navigation.locator(`a[href="/books/${bookId}${suffix}"]`).last().click()
  await expect(page).toHaveURL(new RegExp(`${suffix.replaceAll('/', '\\/')}$`))
}
test.beforeAll(async ({ request, baseURL }) => {
  expect(new URL(baseURL!).port, '只能使用任务5隔离预览实例').toBe('4340')
  fixtures = JSON.parse(await fs.readFile(fixturesPath, 'utf8')) as Fixtures
  expect(fixtures.legacy.database).toBe('zhibi_task5_preview_20261016')
  expect((await get<{ provider: string }[]>(request, '/llm/profiles')).every(profile => profile.provider === 'demo')).toBe(true)
  await fs.mkdir(evidence, { recursive: true })
})

test('任务5 1/2/7：前三章地图、拼图位置、窄屏暗色及开写节点操作', async ({ page, request }) => {
  const browserErrors = errors(page)
  const id = fixtures.main.bookId
  const chapters = await get<ChapterBrief[]>(request, `/books/${id}/chapters`)
  const nodes = await get<StoryNode[]>(request, `/books/${id}/nodes`)
  expect(chapters.filter(chapter => chapter.status === 'final')).toHaveLength(3)
  await page.goto(`/books/${id}`)
  const strip = page.getByTestId('story-map-strip')
  await expect(strip).toBeVisible()
  const summary = '第 1 卷 3/31 章 · 离「外门考核」还有 28 章'
  await expect(strip).toHaveAttribute('aria-label', summary)
  await expect(page.getByTestId('story-map-summary')).toHaveText(summary)
  await expect(page.locator('header').first()).toContainText('第 1 卷 · 已定稿 3 章 · 离「外门考核」还有 28 章')
  const cursor = await page.getByTestId('story-map-cursor').boundingBox()
  const opening = strip.locator('[data-passed="true"]').first()
  const openingBox = await opening.boundingBox()
  const nextBox = await strip.getByRole('button', { name: /节点 2「外门考核」/ }).boundingBox()
  expect(cursor!.x).toBeGreaterThan(openingBox!.x + openingBox!.width / 2)
  expect(cursor!.x).toBeLessThan(nextBox!.x + nextBox!.width / 2)
  await shot(page, '01-前三章概览地图')
  await strip.getByRole('button', { name: /节点 2「外门考核」/ }).focus()
  await expect(strip.getByRole('tooltip').filter({ hasText: '外门考核' })).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`/spine#story-node-${nodes[1].id}$`))
  const target = page.getByTestId(`story-node-${nodes[1].id}`)
  await expect(target).toBeFocused()
  await page.getByTestId('story-map-strip').scrollIntoViewIfNeeded()
  await expect(page.getByTestId(`story-node-${nodes[0].id}`)).toHaveAttribute('data-passed', 'true')
  await expect(page.getByTestId(`story-node-${nodes[0].id}`)).toContainText('已写到')
  await expect(page.locator('[data-testid="node-segment"][data-active="true"]')).toContainText('正在写：第 1 卷 3/31 章')
  await shot(page, '02-拼图地图与已写到')
  await page.locator('[data-testid="node-segment"][data-active="true"]').scrollIntoViewIfNeeded()
  await shot(page, '02-当前分段高亮')
  await expect(page.getByRole('button', { name: /换候选|补上这个空位/ })).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('tab', { name: '稿件', exact: true }).click()
  await strip.scrollIntoViewIfNeeded()
  expect((await page.locator('#manuscript-pane').boundingBox())!.width).toBeLessThan(560)
  expect(await strip.locator('.story-map-node').count()).toBeLessThan(nodes.length)
  await expect(strip.getByLabel('省略的节点')).toHaveCount(1)
  await expect(strip.getByRole('button', { name: /节点 1「/ })).toBeVisible()
  await expect(strip.getByRole('button', { name: /节点 9「/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await strip.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  await shot(page, '07-窄屏地图省略')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('tab', { name: '外观', exact: true }).click()
  await page.getByRole('button', { name: '墨色·暗', exact: true }).click()
  await page.getByRole('button', { name: '关闭设置' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ink')
  await shot(page, '07-窄屏暗色地图')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  expect(await strip.locator('.story-map-cursor').evaluate(element => getComputedStyle(element).animationName)).toBe('none')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('tab', { name: '外观', exact: true }).click()
  await page.getByRole('button', { name: '宣纸·亮', exact: true }).click()
  await page.getByRole('button', { name: '关闭设置' }).click()
  await target.getByRole('button', { name: /在节点 2 下面插入/ }).click()
  await expect(page.getByRole('dialog', { name: '插入一个铁钉节点' })).toBeVisible()
  await page.getByPlaceholder('给节点起个名字').fill('验收临时铁钉')
  await page.getByRole('button', { name: '添加节点', exact: true }).click()
  const added = page.locator('[data-node-status="pinned"]').filter({ hasText: '验收临时铁钉' })
  await expect(added).toBeVisible()
  await added.getByRole('button', { name: /删除节点/ }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(added).toHaveCount(0)
  expect(browserErrors).toEqual([])
  await record('地图结果', { bookId: id, finalChapters: 3, summary, cursorAfterOpening: true, passedOpening: true, activeSegment: true, keyboardTooltipAndNodeNavigation: true, narrowViewport: '390×844', manuscriptBelow560: true, nodesCollapsed: true, darkMode: true, reducedMotion: true, noWritingCandidates: true, insertNamedPinnedAndCleanup: true, browserErrors })
})

test('任务5 3/6：卷页情绪曲线动作揭晓及章节抽屉', async ({ page, request }) => {
  const browserErrors = errors(page)
  const id = fixtures.adjust.bookId
  const outline = await get<Outline>(request, `/books/${id}/outline`)
  const chapters = await get<ChapterBrief[]>(request, `/books/${id}/chapters?volume=1`)
  expect(chapters.filter(chapter => chapter.status === 'final')).toHaveLength(31)
  await manualPage(page, id, '/volume/1')
  const manuscript = page.getByRole('main', { name: '稿件' })
  await expect(manuscript.getByRole('region', { name: '本卷走向' })).toContainText('本卷发生')
  await expect(manuscript).toContainText('编辑批注')
  await shot(page, '03-卷走向与编辑批注')
  await manuscript.getByTestId('emotion-curve').first().scrollIntoViewIfNeeded()
  await expect(manuscript.getByTestId('emotion-curve')).toHaveCount(4)
  await expect(manuscript.getByRole('list', { name: '各章主情绪' })).toHaveCount(4)
  await shot(page, '03-单元情绪曲线与主情绪')
  const point = manuscript.getByTestId('emotion-curve').first().getByRole('button').first()
  await point.hover()
  await expect(page.getByRole('tooltip')).toContainText('第 1 章 · 0 平稳或悬着 · 悬')
  await shot(page, '03-情绪点悬停')
  await page.mouse.move(0, 0)
  const firstAction = manuscript.getByRole('list', { name: '期待与伏笔动作' }).first()
  await expect(firstAction).toContainText('立下 E6')
  await expect(firstAction).toContainText('埋下 F1')
  await firstAction.getByRole('button').filter({ hasText: '立下 E6' }).hover()
  await expect(page.getByRole('tooltip')).toContainText('当众立下的约定')
  await shot(page, '03-期待伏笔动作提示')
  await page.mouse.move(0, 0)
  const revealButton = manuscript.getByRole('button', { name: '揭晓 S1 → 苏晚晴', exact: true }).first()
  await revealButton.hover()
  await expect(page.getByRole('tooltip')).toContainText('陆远以证据解释先前异常')
  await shot(page, '03-揭晓标签与提示')
  await page.mouse.move(0, 0)
  const actionsText = await manuscript.getByRole('list', { name: '期待与伏笔动作' }).allTextContents()
  expect(actionsText.join(' ')).toContain('兑现 E10')
  expect(actionsText.join(' ')).toContain('回收 F8')
  const revealChapter = chapters.find(chapter => chapter.outline?.reveals?.length)!
  await page.getByRole('navigation', { name: '书稿目录' }).locator(`a[href="/books/${id}/volume/1"]`).click()
  await manuscript.locator(`a[href="/books/${id}/chapter/${revealChapter.index}"]`).click()
  await page.getByRole('button', { name: '章纲', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '章纲' })
  expect(revealChapter.outline?.emotion).toBe(2)
  await expect(drawer).toContainText('情绪：+2 爆发爽快（' + revealChapter.outline?.mood + '）')
  await expect(drawer.getByRole('button', { name: '揭晓 S1 → 苏晚晴', exact: true })).toBeVisible()
  await shot(page, '06-章节章纲情绪与揭晓')
  await drawer.getByRole('button', { name: '揭晓 S1 → 苏晚晴', exact: true }).focus()
  await expect(page.getByRole('tooltip')).toContainText(revealChapter.outline!.reveals![0].how)
  await page.keyboard.press('Escape')
  expect(browserErrors).toEqual([])
  await record('卷章结果', { bookId: id, firstVolumeFinalChapters: 31, curveCount: outline.volumes[0].units.length, pointTooltip: '第 1 章 · 0 平稳或悬着 · 悬', actionsText, revealChapter: revealChapter.index, chapterEmotion: revealChapter.outline?.emotion, chapterMood: revealChapter.outline?.mood, reveals: revealChapter.outline?.reveals, browserErrors })
})

test('任务5 4：真实节奏触发器的遗留问题与连续主情绪提示', async ({ page, request }) => {
  const browserErrors = errors(page)
  const id = fixtures.rhythm.bookId
  const outline = await get<Outline>(request, `/books/${id}/outline`)
  const issues = outline.volumes[0].units[0].plan_issues ?? []
  expect(issues.length).toBeGreaterThan(0)
  await page.goto(`/books/${id}/volume/1`)
  const warning = page.getByTestId('unit-plan-issues').first()
  await warning.evaluate(element => element.scrollIntoView({ block: 'start' }))
  await expect(warning).toContainText(`章纲还有 ${issues.length} 处节奏问题`)
  await warning.locator('summary').click()
  for (const issue of issues) await expect(warning).toContainText(issue)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('连续至少 4 章主情绪相同')
  await expect(page.locator('[aria-label*="连续至少 4 章主情绪相同"]')).not.toHaveCount(0)
  await shot(page, '04-节奏问题展开与主情绪警示')
  const calls = await get<{ items: { purpose: string }[] }>(request, `/llm-calls?book_id=${id}&limit=100`)
  expect(calls.items.filter(item => item.purpose === '写作·章纲')).toHaveLength(2)
  expect(browserErrors).toEqual([])
  await record('节奏结果', { bookId: id, jobId: fixtures.rhythm.writeJob, planIssues: issues, chapterPlanCalls: 2, repeatedMoodWarning: true, browserErrors })
})

test('任务5 5：节点调整前后对比、批准与拼图板持久化', async ({ page, request }) => {
  test.setTimeout(600_000)
  const browserErrors = errors(page)
  let { bookId: id, nextJob: jobId } = fixtures.adjust
  let job = await get<Job>(request, `/jobs/${jobId}`)
  // 可重复运行；旧轮已批准时重新走真实演示流程，不恢复或篡改已批准的节点。
  if (job.status !== 'waiting_author' || job.pending?.kind !== 'volume_review') {
    const created = await call<{ book: BookDetail; job: Job }>(request, 'POST', '/books', { idea: '第一包任务5节点调整复验：少年持青灯循证破局。', ask: false, mode: 'oneshot' })
    id = created.book.id
    await settled(request, created.job.id, 'setup_review')
    await call(request, 'POST', `/jobs/${created.job.id}/decision`, { action: 'approve' }); await settled(request, created.job.id)
    const write = await call<Job>(request, 'POST', `/books/${id}/write`, { until: 'volume', count: 1 })
    await settled(request, write.id, 'trial_read'); await call(request, 'POST', `/jobs/${write.id}/decision`, { action: 'approve' }); await settled(request, write.id)
    const outline = await get<Outline>(request, `/books/${id}/outline`)
    await call(request, 'PATCH', `/volumes/${outline.volumes[1].id}`, { title: '测试节点调整·第二卷' })
    jobId = (await call<Job>(request, 'POST', `/books/${id}/write`, { until: 'count', count: 1 })).id
    job = await settled(request, jobId, 'volume_review')
  }
  if (job.pending?.kind !== 'volume_review' || !job.pending.node_update) throw new Error('缺少真实节点调整提议')
  const proposal = job.pending.node_update
  const original = (await get<StoryNode[]>(request, `/books/${id}/nodes`)).find(node => node.id === proposal.node_id)!
  expect(original.title).toBe(proposal.current.title)
  await page.goto(`/books/${id}/volume/2`)
  const comparison = page.getByTestId('node-update-comparison')
  await expect(comparison).toContainText(`这一卷建议调整暂定节点「${original.title}」`)
  await expect(comparison).toContainText('批准卷纲会同时应用这个调整')
  for (const field of ['名称', '发生什么', '之前得先有', '之后变成']) {
    await expect(comparison).toContainText(`调整前 · ${field}`)
    await expect(comparison).toContainText(`调整后 · ${field}`)
  }
  expect(await comparison.locator('u').count()).toBeGreaterThan(0)
  await shot(page, '05-节点调整提议与前后对比')
  await comparison.getByText(proposal.reason, { exact: false }).last().scrollIntoViewIfNeeded()
  await shot(page, '05-节点调整前提后果与理由')
  const approvalResponse = page.waitForResponse(response => response.url().endsWith('/jobs/' + jobId + '/decision') && response.request().method() === 'POST')
  await page.getByTestId('decision-bar').getByRole('button', { name: '批准开写', exact: true }).click()
  expect((await approvalResponse).ok()).toBe(true)
  expect((await settled(request, jobId)).status).toBe('succeeded')
  const updated = (await get<StoryNode[]>(request, `/books/${id}/nodes`)).find(node => node.id === original.id)!
  for (const key of ['title', 'event', 'prerequisite', 'consequence'] as const) expect(updated[key]).toBe(proposal.proposed[key])
  expect(updated.updated_by_volume).toBe(2)
  expect(updated.status).toBe('pencil')
  await manualPage(page, id, '/spine')
  const card = page.getByTestId(`story-node-${updated.id}`)
  await card.scrollIntoViewIfNeeded()
  await expect(card).toContainText('第 2 卷拆卷纲时调整过')
  await expect(card).toContainText(proposal.proposed.title)
  await shot(page, '05-批准后节点更新与卷次说明')
  expect(browserErrors).toEqual([])
  await record('节点调整结果', { bookId: id, jobId, proposal, original, updated, approvedInBrowser: true, browserErrors })
})

test('任务5 8：0010真实迁移旧书无目标节点的降级展示', async ({ page, request }) => {
  const browserErrors = errors(page)
  const id = fixtures.legacy.bookId
  const outline = await get<Outline>(request, `/books/${id}/outline`)
  expect(outline.volumes.every(volume => !volume.target_node_id)).toBe(true)
  await page.goto(`/books/${id}`)
  await expect(page.getByTestId('story-map-strip')).toContainText('第 1 卷 2/5 章 · 全书已定稿 2/5 章')
  await expect(page.getByTestId('story-map-strip').locator('.story-map-node')).toHaveCount(0)
  await expect(page.getByTestId('story-map-strip')).toContainText('计划终点')
  await shot(page, '08-旧书概览章数地图')
  await manualPage(page, id, '/volume/1')
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('出章纲后显示情绪曲线')
  await expect(page.getByTestId('emotion-curve')).toHaveCount(0)
  await shot(page, '08-旧卷无节点与旧章纲')
  for (const old of fixtures.legacy.chapters.filter(chapter => chapter.content)) {
    const chapter = await get<{ content: string; outline: unknown }>(request, `/books/${id}/chapters/${old.index}`)
    expect(chapter.content).toBe(old.content)
    expect(chapter.outline).toEqual(old.outline)
  }
  expect(browserErrors).toEqual([])
  await record('旧书界面结果', { bookId: id, migration: fixtures.legacy.migration, nullTargets: true, ratio: 0.4, noFabricatedEmotion: true, originalChaptersUnchanged: true, browserErrors })
})

test('任务5 9：关键节点与填中间待确认各只高亮一项', async ({ page, request }) => {
  test.setTimeout(300_000)
  const browserErrors = errors(page)
  let { bookId: id, jobId } = fixtures.puzzle
  const existing = await get<Job>(request, `/jobs/${jobId}`)
  if (existing.pending?.kind !== 'setup_piece' || existing.pending.piece !== 'nodes') {
    const created = await call<{ book: BookDetail; job: Job }>(request, 'POST', '/books', { idea: '第一包任务5高亮复验：少年借青灯追查旧案。', ask: false, mode: 'puzzle' })
    id = created.book.id; jobId = created.job.id
    await settled(request, jobId, 'setup_directions')
    await call(request, 'POST', `/jobs/${jobId}/directions`, { action: 'choose', choice: 0, length: '百万字以上（长篇连载）' })
    await settled(request, jobId, 'setup_piece', 'concept')
    await call(request, 'POST', `/jobs/${jobId}/piece`, { action: 'confirm', piece: 'concept' })
    await settled(request, jobId, 'setup_piece', 'nodes')
  }
  await page.goto(`/books/${id}/spine`)
  const nav = page.getByRole('navigation', { name: '书稿目录' })
  const nodes = nav.getByRole('link', { name: /② 关键节点/ })
  const fill = nav.getByRole('link', { name: /④ 填中间/ })
  await expect(nodes).toHaveAttribute('aria-current', 'step')
  await expect(fill).not.toHaveAttribute('aria-current')
  await expect(nodes).toHaveClass(/bg-card /)
  await expect(fill).not.toHaveClass(/bg-card /)
  await shot(page, '09-关键节点仅亮第二项')
  await page.getByRole('button', { name: '确认这一块', exact: true }).click()
  await settled(request, jobId, 'setup_piece', 'cast')
  await page.getByRole('button', { name: '确认这一块', exact: true }).click()
  await settled(request, jobId, 'setup_piece', 'fill')
  await expect(fill).toHaveAttribute('aria-current', 'step')
  await expect(nodes).not.toHaveAttribute('aria-current')
  await expect(fill).toHaveClass(/bg-card /)
  await expect(nodes).not.toHaveClass(/bg-card /)
  await shot(page, '09-填中间仅亮第四项')
  expect(browserErrors).toEqual([])
  await record('左栏高亮结果', { bookId: id, jobId, nodesOnlySecondActive: true, fillOnlyFourthActive: true, browserErrors })
})
