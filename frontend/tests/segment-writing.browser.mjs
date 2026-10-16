/** 任务 4 最小确认界面回归；所有 API 都拦截，绝不连接作者书库。 */
import assert from 'node:assert/strict'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4345'
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) })
const page = await browser.newPage({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce' })
const errors = [], unexpected = [], mutations = []
page.on('pageerror', error => errors.push(error.message))
const plan = { carried: 'E1 在这一段兑现', pursuit: '查清师兄的死因', finger_next: '看见旧物留下的路线', answers: '', map: '北境寒原', new_map: null, power: '', trouble: '守门人不肯放行', opponent: '寒原守将', new_characters: [], relationships: [], goal: '七天内拿到师兄留下的证据', goal_link: '找到真相', wait: { description: '让守将公开认错' }, reveal: '新的线索', secrets: [], end: { title: '寒原追查', event: '拿到证据，直面守将', prerequisite: '拿到入城资格', consequence: '知道敌人是谁', volume: 2, adopted: false, status: 'pencil' }, ending: '', finale: false }
const pending = { kind: 'segment_review', flow: 2, number: 2, round: 0, plan, split: { volumes: [] }, warnings: ['E1 还开着，请看看这一段怎么收。', '第二条提醒只在展开后显示。'], flags: { carried: ['E1 还开着，请看看这一段怎么收。'] }, decisions: [] }
const job = { id: 'segment-job', book_id: 'fixture', kind: 'write_book', setup_flow: null, status: 'waiting_author', pending, error: '' }
let book = { id: 'fixture', title: '定下一段回归', source: 'new', genre: '', status: 'writing', idea: '测试短段', logline: '', style_reference: '', concept: { title: '定下一段回归' }, protagonist: {}, world: {}, spine: {}, setup_progress: {}, requirements: [], trial_read_done: true, active_job: job, chapters_final: 6, words_final: 18000 }
const messages = [{ id: 1, book_id: 'fixture', job_id: job.id, speaker: 'chief', speaker_name: '主编', kind: 'artifact', content: '第 2 段：走到「寒原追查」', payload: { type: 'segment_plan', data: plan }, created_at: null }]
let failNext = true

await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname
  if (!path.startsWith('/api/')) return route.continue()
  if (request.method() === 'POST' && path === '/api/jobs/segment-job/segment') {
    mutations.push({ path, body: request.postDataJSON() })
    await new Promise(resolve => setTimeout(resolve, 450))
    if (failNext) { failNext = false; return route.fulfill({ status: 503, json: { detail: '模拟失败：保留本轮规划和意见' } }) }
    book = { ...book, active_job: { ...job, status: 'queued', pending: null } }
    return route.fulfill({ json: book.active_job })
  }
  if (request.method() === 'GET') {
    if (path === '/api/books/fixture/events') return route.fulfill({ contentType: 'text/event-stream', body: messages.map(message => `id: ${message.id}\nevent: message\ndata: ${JSON.stringify(message)}\n\n`).join('') })
    if (path === '/api/books/fixture') return route.fulfill({ json: book })
    if (path === '/api/books/fixture/outline') return route.fulfill({ json: { concept: book.concept, volumes: [] } })
    if (path === '/api/books/fixture/bible') return route.fulfill({ json: { characters: [], world_entries: [], relationships: [], foreshadowings: [], secrets: [] } })
    if (['nodes', 'chapters', 'threads', 'secrets'].some(suffix => path === `/api/books/fixture/${suffix}`)) return route.fulfill({ json: [] })
    if (path === '/api/books') return route.fulfill({ json: [] })
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    if (path === '/api/glossary') return route.fulfill({ json: { terms: [] } })
  }
  unexpected.push(`${request.method()} ${path}`)
  return route.fulfill({ status: 404, json: { detail: '未预期的请求，已拦截' } })
})

try {
  await page.goto(`${base}/books/fixture/spine`)
  const bar = page.getByTestId('decision-bar')
  const confirm = bar.getByRole('button', { name: '确认这一段', exact: true })
  const delegate = bar.getByRole('button', { name: '交给编辑部定', exact: true })
  const composer = page.getByRole('textbox', { name: '修改意见', exact: true })
  const send = page.getByRole('button', { name: '发送', exact: true })
  await expect(bar).toContainText('待你确认：第 2 段（E1 还开着，请看看这一段怎么收。）')
  await expect(composer).toHaveAttribute('placeholder', '说说下一段想怎么改…')
  await expect(bar.getByText('第二条提醒只在展开后显示。', { exact: true })).not.toBeVisible()
  await bar.locator('summary').click()
  await expect(bar.getByText('第二条提醒只在展开后显示。', { exact: true })).toBeVisible()
  await bar.locator('summary').click()
  const artifact = page.getByTestId('artifact-message-1')
  await artifact.getByRole('button', { name: '展开第 2 段：走到「寒原追查」', exact: true }).click()
  for (const text of ['寒原追查：拿到证据，直面守将', '北境寒原', '七天内拿到师兄留下的证据', '查清师兄的死因']) await expect(artifact).toContainText(text)

  // 失败不丢作者原文，修改时两个拍板按钮同时锁定。
  await composer.fill('保留原地图，不要换地图。')
  await send.click()
  await expect(confirm).toBeDisabled()
  await expect(delegate).toBeDisabled()
  await expect(send).toBeDisabled()
  await expect(page.getByText('模拟失败：保留本轮规划和意见', { exact: true })).toBeVisible()
  await expect(composer).toHaveValue('保留原地图，不要换地图。')
  await expect(confirm).toBeEnabled()
  assert.deepEqual(mutations[0].body, { action: 'revise', feedback: '保留原地图，不要换地图。' })
  await send.click()
  await expect(bar).toHaveCount(0)
  await expect(composer).toHaveCount(0)
  assert.equal(mutations.length, 2)

  // 确认连点只发送一次；请求期间代定与聊天也不能重复提交。
  book = { ...book, active_job: { ...job, pending: { ...pending, round: 1 } } }
  await page.reload()
  await composer.fill('不应与确认同时提交')
  await confirm.evaluate(button => { button.click(); button.click() })
  await expect(confirm).toBeDisabled()
  await expect(delegate).toBeDisabled()
  await expect(send).toBeDisabled()
  await expect(bar).toHaveCount(0)
  assert.equal(mutations.length, 3)
  assert.deepEqual(mutations[2].body, { action: 'confirm' })

  // 代定同样调用专用接口，不误调用旧的 /decision。
  book = { ...book, active_job: job }
  await page.reload()
  await delegate.click()
  await expect(confirm).toBeDisabled()
  await expect(bar).toHaveCount(0)
  assert.deepEqual(mutations[3].body, { action: 'delegate' })
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  console.log('通过：下一段拍板、第一条提醒/折叠、四项会议卡、聊天修改失败保留与重试、确认/代定、跨组件防重复。全部 API 已拦截。')
} catch (error) {
  console.error({ errors, unexpected, mutations, body: await page.locator('body').innerText() })
  throw error
} finally { await browser.close() }
