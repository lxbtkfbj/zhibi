/** 任务 5 确认页边界回归：所有 /api/ 请求在内存中应答，不接触书库。 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4347'
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) })
const page = await browser.newPage({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce' })
const errors = [], unexpected = [], mutations = [], checks = []
page.on('pageerror', error => errors.push(error.message))
const plan = { carried: 'E1 和 F2 都在这一段收掉。', pursuit: '从寻人升级为揭开密令', finger_next: '旧物留影可以查到路线', answers: '', map: '北境寒原', new_map: { name: '北境寒原', powers: '巡北军', ceiling: '筑基', rules: '入城须验符', start: '南门', gains: '师兄留下的信' }, power: '', trouble: '被守门人阻拦', opponent: '巡北统领', new_characters: [{ name: '沈霜', role_type: '配角', goal: '追回家书', want: '拿到通行符' }], relationships: [], goal: '七天内拿到密令', goal_link: '密令能找到失踪的师兄', wait: { description: '让巡北军公开密令', plant_plan: '在城门立约', payoff_plan: '公开密令并追责', plant_volume: 2, payoff_volume: 2 }, reveal: '密令另有执笔人', secrets: [{ title: '密令来处', truth: '命令出自宗门', knowers: ['沈霜'] }], end: { title: '寒原追查', event: '公开密令', prerequisite: '先拿到证据', consequence: '踏上追查执笔人的路', volume: 2, adopted: true, status: 'pencil' }, ending: '', finale: true, nodes_view: [{ index: 3, title: '寒原追查' }] }
const pending = { kind: 'segment_review', flow: 2, number: 2, round: 1, plan, split: { volumes: [{ index: 2, title: '寒原', chapter_count: 6, want: '拿到密令', goal: '发现真相', antagonist: '巡北统领' }], anchors: [{ node: 3, character: '沈霜', kind: '登场', note: '带来通行符' }], threads: [{ name: '密令线', beats: [{ volume: 2, beat: '找出执笔人' }] }] }, warnings: ['E1 的兑现要写清楚'], flags: { carried: ['E1 的兑现要写清楚'], goal: ['目标需要期限'] }, decisions: [{ topic: '进入寒原的方式', chosen: '走南门', alternatives: ['走西门'], why: '南门能遇到沈霜' }] }
const job = { id: 'review-job', book_id: 'review', kind: 'write_book', setup_flow: null, status: 'waiting_author', pending, error: '' }
let book = { id: 'review', title: '下一段确认边界', source: 'new', genre: '', status: 'writing', idea: '测试短段', logline: '', style_reference: '', concept: { title: '下一段确认边界' }, protagonist: {}, world: {}, spine: {}, setup_progress: {}, requirements: [], trial_read_done: true, active_job: structuredClone(job), chapters_final: 6, words_final: 18000 }
let failNext = true, release
await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname
  if (!path.startsWith('/api/')) return route.continue()
  if (request.method() === 'POST' && path === '/api/jobs/review-job/segment') {
    const body = request.postDataJSON()
    mutations.push(body)
    await new Promise(resolve => { release = resolve })
    if (failNext) { failNext = false; return route.fulfill({ status: 503, json: { detail: '模拟提交失败，原稿保留' } }) }
    book.active_job = body.action === 'revise'
      ? { ...job, pending: { ...pending, round: book.active_job.pending.round + 1, decisions: [{ ...pending.decisions[0], chosen: '走西门', alternatives: ['走南门'] }] } }
      : { ...job, status: 'waiting_author', pending: { kind: 'volume_review', volume: 2, title: '寒原', issues: [] } }
    return route.fulfill({ json: book.active_job })
  }
  if (request.method() === 'GET') {
    if (path.endsWith('/events')) return route.fulfill({ status: 204 })
    if (path === '/api/books/review') return route.fulfill({ json: book })
    if (path === '/api/books/other') return route.fulfill({ json: { ...book, id: 'other', title: '另一本书', active_job: { ...job, id: 'other-job', book_id: 'other', pending } } })
    if (/\/outline$/.test(path)) return route.fulfill({ json: { concept: book.concept, volumes: [] } })
    if (/\/settings$/.test(path)) return route.fulfill({ json: { settings: { segment_approval: true }, defaults: { segment_approval: true }, overrides: {} } })
    if (/\/bible$/.test(path)) return route.fulfill({ json: { characters: [], world_entries: [], relationships: [], secrets: [], foreshadowings: [{ code: 'E1', description: '师兄归来', kind: '期待', plant_plan: '山门约定', payoff_plan: '寒原相见' }, { code: 'F2', description: '未署名的信', kind: '伏笔', plant_plan: '留在青灯下', payoff_plan: '认出笔迹' }] } })
    if (['nodes', 'chapters', 'threads', 'secrets'].some(suffix => path.endsWith(`/${suffix}`))) return route.fulfill({ json: [] })
    if (path === '/api/books') return route.fulfill({ json: [] })
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    if (path === '/api/glossary') return route.fulfill({ json: { terms: [] } })
  }
  unexpected.push(`${request.method()} ${path}`)
  return route.fulfill({ status: 500, json: { detail: '验收未预期的 API 请求已拦截' } })
})
const review = page.getByTestId('next-segment-review')
const bar = page.getByTestId('decision-bar')
const checkbox = page.getByRole('checkbox', { name: '确认时把它钉死' })
const confirm = bar.getByRole('button', { name: '确认这一段', exact: true })
const send = page.getByRole('button', { name: '发送', exact: true })
const report = resolve('../data/second-package-task5/next-segment-boundaries.json')
try {
  await page.goto(`${base}/books/review/spine`)
  await expect(page).toHaveURL(`${base}/books/review/next-segment`)
  await expect(review.locator('.setup-question')).toHaveCount(14)
  await expect(review.getByRole('navigation', { name: '作者重点看' }).getByRole('link')).toHaveCount(3)
  await expect(review.locator('#q-carried')).toContainText('需要再看看：E1 的兑现要写清楚')
  await expect(review.locator('#q-goal')).not.toContainText('E1 的兑现要写清楚')
  await expect(review).toContainText('这是收尾段：开始收线，往结局走。')
  await expect(review.locator('#q-answers')).toContainText('还远，写到再定')
  await expect(review.locator('#q-people')).toContainText('追回家书')
  await expect(review.locator('#q-volumes')).toContainText('找出执笔人')
  await expect(review.locator('#q-cast')).toContainText('节点 3「寒原追查」')
  await expect(review.getByRole('textbox')).toHaveCount(0)
  await review.getByRole('button', { name: '查看 F2 台账' }).hover()
  await expect(page.getByRole('tooltip')).toContainText('未署名的信')
  checks.push('自动跟随独立页、十四题、三道重点看、题下提醒、只读正文、F/E 台账、全部结构化内容')

  await checkbox.check()
  await page.getByTestId('full-sidebar').getByRole('link', { name: '书的概念', exact: true }).click()
  await confirm.click()
  await expect(confirm).toBeDisabled()
  assert.deepEqual(mutations[0], { action: 'confirm', pin_end: true })
  release()
  await expect(bar).toContainText('模拟提交失败，原稿保留')
  await page.getByTestId('full-sidebar').getByRole('link', { name: '定下一段 · 待确认', exact: true }).click()
  await expect(checkbox).toBeChecked()
  checks.push('钉死选择在切稿件页后被拍板条读取；失败保留原稿与勾选')

  await review.getByRole('radio', { name: '走西门', exact: true }).check()
  await review.getByRole('button', { name: '按我选的改' }).click()
  await expect(confirm).toBeDisabled()
  await expect(checkbox).toBeDisabled()
  await expect(review.getByRole('radio', { name: '走西门', exact: true })).toBeDisabled()
  await expect(review.getByTestId('next-segment-actions').getByRole('button').first()).toBeDisabled()
  await expect(send).toBeDisabled()
  assert.deepEqual(mutations[1], { action: 'revise', flips: [{ topic: '进入寒原的方式', choice: '走西门' }] })
  release()
  await expect(review.getByRole('radio', { name: '走西门', exact: true })).toBeChecked()
  await expect(checkbox).not.toBeChecked()
  checks.push('换决定只交 revise + flips；所有动作共享锁；新轮次清空钉死')

  await checkbox.check()
  await page.getByRole('textbox', { name: '修改意见', exact: true }).fill('确认时不应同时提交')
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll('button')]
    buttons.filter(button => button.textContent.trim() === '确认这一段').forEach(button => button.click())
    document.querySelector('button[aria-label="发送"]')?.click()
  })
  await expect(confirm).toBeDisabled()
  await expect.poll(() => mutations.length).toBe(3)
  assert.deepEqual(mutations[2], { action: 'confirm', pin_end: true })
  release()
  await expect(review).toHaveCount(0)
  await expect(bar).toContainText('第 2 卷卷纲')
  await expect(page.getByTestId('full-sidebar').getByRole('link', { name: '定下一段 · 待确认' })).toHaveCount(0)
  checks.push('拍板条与页底同一事件循环连点只发送一次，确认转卷纲后临时导航消失')

  // SPA 换书触发同一个 BookLayout 的 key 边界，而非靠 reload 清状态。
  await page.evaluate(() => { history.pushState({}, '', '/books/other/next-segment'); dispatchEvent(new PopStateEvent('popstate')) })
  await expect(review).toBeVisible()
  await expect(checkbox).not.toBeChecked()
  checks.push('SPA 换书后钉死勾选清空')
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  await mkdir(resolve('../data/second-package-task5'), { recursive: true })
  await writeFile(report, JSON.stringify({ passed: true, checks, mutations, errors, unexpected }, null, 2))
  console.log(JSON.stringify({ passed: true, checks, report }, null, 2))
} catch (error) {
  console.error({ errors, unexpected, mutations, body: await page.locator('body').innerText() })
  throw error
} finally { release?.(); await browser.close() }
