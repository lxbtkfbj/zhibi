/** 新五步边界回归：所有 API 拦截，不读取或改动任何真实书库。 */
import assert from 'node:assert/strict'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4344'
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) })
const page = await browser.newPage({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce' })
const errors = [], unexpected = [], mutations = []
page.on('pageerror', error => errors.push(error.message))
const oldJob = { id: 'old-setup', book_id: 'fixture', kind: 'book_setup', setup_flow: 1, status: 'waiting_author', pending: { kind: 'setup_piece', piece: 'nodes', round: 0 }, error: '' }
let book = { id: 'fixture', title: '五步界面回归', source: 'new', genre: '', status: 'setting_up', idea: '寻找妹妹', logline: '', style_reference: '', concept: { title: '五步界面回归' }, protagonist: {}, world: {}, spine: {}, setup_progress: { mode: 'puzzle', current: 'nodes', pieces: { concept: 'confirmed', nodes: 'waiting' } }, requirements: ['保留作者要求'], trial_read_done: false, active_job: oldJob, chapters_final: 0, words_final: 0 }
let restartAttempts = 0
let nodes = []
let messages = []
await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname
  if (!path.startsWith('/api/')) return route.continue()
  if (request.method() === 'POST' && path === '/api/jobs/old-setup/restart-setup') {
    mutations.push({ path, body: request.postDataJSON() })
    restartAttempts += 1
    await new Promise(resolve => setTimeout(resolve, 350))
    if (restartAttempts === 1) return route.fulfill({ status: 503, json: { detail: '模拟重开失败，作者内容未丢失' } })
    const next = { ...oldJob, id: 'new-setup', setup_flow: 2, status: 'queued', pending: null }
    book = { ...book, active_job: next, setup_progress: {} }
    return route.fulfill({ json: next })
  }
  if (request.method() === 'GET') {
    if (path === '/api/books/fixture/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: messages.map((message, index) => `id: ${index + 1}\nevent: message\ndata: ${JSON.stringify(message)}\n\n`).join('') })
    if (path === '/api/books/fixture') return route.fulfill({ json: book })
    if (path === '/api/books/fixture/outline') return route.fulfill({ json: { concept: book.concept, volumes: [] } })
    if (path === '/api/books/fixture/bible') return route.fulfill({ json: { characters: [], world_entries: [], relationships: [], foreshadowings: [], secrets: [] } })
    if (path === '/api/books/fixture/nodes') return route.fulfill({ json: nodes })
    if (['chapters', 'threads', 'secrets'].some(suffix => path === `/api/books/fixture/${suffix}`)) return route.fulfill({ json: [] })
    if (path === '/api/books') return route.fulfill({ json: [] })
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    if (path === '/api/glossary') return route.fulfill({ json: { terms: [] } })
  }
  unexpected.push(`${request.method()} ${path}`)
  return route.fulfill({ status: 404, json: { detail: '未预期的回归请求，已拦截' } })
})

try {
  for (const status of ['failed', 'cancelled']) {
    book.active_job.status = status
    await page.goto(`${base}/books/fixture/spine`)
    await expect(page.getByTestId('restart-setup-bar')).toBeVisible()
    await expect(page.getByRole('button', { name: '继续', exact: true })).toHaveCount(0)
  }
  book.active_job.status = 'waiting_author'
  await page.goto(`${base}/books/fixture/spine`)
  const restart = page.getByTestId('restart-setup-bar')
  await expect(restart).toContainText('保留你的点子、作者要求、已选的方向和已确认的定调')
  await expect(page.getByRole('button', { name: '确认这一块', exact: true })).toHaveCount(0)
  await restart.getByRole('button', { name: '按新流程重开', exact: true }).click()
  await expect(restart.getByRole('button', { name: '按新流程重开', exact: true })).toBeDisabled()
  await expect(restart).toContainText('模拟重开失败，作者内容未丢失')
  await expect(restart.getByRole('button', { name: '按新流程重开', exact: true })).toBeEnabled()
  assert.deepEqual(book.requirements, ['保留作者要求'])
  await restart.getByRole('button', { name: '按新流程重开', exact: true }).click()
  await expect(restart).toHaveCount(0)
  assert.equal(restartAttempts, 2)

  // 旧书主角钩子照常显示，既不误造主角卡也不提示重开。
  book = { ...book, status: 'ready', active_job: null, concept: { title: '旧书', protagonist_hook: '旧书主角钩子原文' }, setup_progress: {} }
  await page.goto(`${base}/books/fixture/protagonist`)
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('这本书开书时还没有主角卡')
  await expect(page.getByRole('main', { name: '稿件' })).toContainText('旧书主角钩子原文')
  await expect(restart).toHaveCount(0)

  // 只读新卡包含写到再定占位，且路由高亮不会跟着 pending 转移到别的块。
  book = { ...book, status: 'setting_up', concept: { title: '新书', core_loop: '每一单元查案找到线索', benchmark: '只借鉴悬疑氛围' }, protagonist: { name: '陆远', pursuit: '找妹妹', interlock: '青灯帮助查案，案件带来妹妹线索' }, world: { surface: '力量公开', power: '炼气', maps: [{ name: '青石镇', powers: '镇守说了算' }], trouble: '催债', opponent: '镇守要隐瞒旧案', shadow: '幕后人的手印', mystery: '妹妹在哪里' }, setup_progress: { mode: 'puzzle', current: 'first_volume', pieces: { concept: 'confirmed', protagonist: 'confirmed', world: 'confirmed', segment: 'confirmed', first_volume: 'waiting' } }, active_job: { ...oldJob, id: 'new', setup_flow: 2, pending: { kind: 'setup_piece', flow: 2, piece: 'first_volume', round: 0, flags: {}, review: [{ question: 'unit_loop', problem: '第二单元循环较弱', suggestion: '让线索推动寻找' }] } } }
  await page.goto(`${base}/books/fixture/protagonist`)
  const manuscript = page.getByRole('main', { name: '稿件' })
  await expect(manuscript.getByText('先空着，写到这里时主编会来问你', { exact: true })).toHaveCount(2)
  await expect(manuscript.getByTestId('protagonist-card').getByRole('textbox')).toHaveCount(0)
  await expect(page.getByTestId('full-sidebar').getByRole('link', { name: /② 主角/ })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByTestId('full-sidebar').getByRole('link', { name: /⑤ 第一卷/ })).not.toHaveAttribute('aria-current', 'page')
  await page.getByTestId('decision-bar').locator('summary').click()
  await expect(page.getByTestId('decision-bar')).toContainText('第二单元循环较弱')

  await page.goto(`${base}/books/fixture/world`)
  await expect(manuscript.getByRole('region', { name: '世界与地图' })).toContainText('谁说了算：镇守说了算')
  await expect(manuscript).toContainText('谜底：写到再定')
  await page.goto(`${base}/books/fixture/concept`)
  await expect(manuscript).toContainText('每一单元查案找到线索')
  await expect(manuscript).toContainText('只借鉴悬疑氛围')
  await expect(manuscript.getByText('主角钩子', { exact: true })).toHaveCount(0)

  // 非第一段等待时，即使带了旧候选快照，也不能露出候选和补空操作。
  nodes = [{ id: 'n1', index: 1, kind: 'opening', title: '开篇', event: '', prerequisite: '', consequence: '', status: 'empty', volume: null, origin: 'author', anchors: [], editor_note: '', techniques: [] }]
  book.active_job.pending.candidates = { node_id: 'n1', nodes: [{ title: '不应露出的旧候选', event: '旧内容' }] }
  await page.goto(`${base}/books/fixture/spine`)
  await expect(manuscript.getByRole('button', { name: '补上这个空位', exact: true })).toHaveCount(0)
  await expect(manuscript.getByRole('button', { name: '给我 3 个候选', exact: true })).toHaveCount(0)
  await expect(manuscript.getByRole('region', { name: '节点 1 的候选' })).toHaveCount(0)
  book.active_job.pending.piece = 'segment'
  await page.reload()
  await expect(manuscript.getByRole('button', { name: '补上这个空位', exact: true })).toBeVisible()
  await expect(manuscript.getByRole('button', { name: '给我 3 个候选', exact: true })).toBeVisible()
  await expect(manuscript.getByRole('region', { name: '节点 1 的候选' })).toBeVisible()

  // 空的新消息与旧消息都能展开；实际字段在新快照里可见。
  book = { ...book, status: 'ready', active_job: null }
  messages = [
    ['protagonist', { name: '陆远', pursuit: '找妹妹' }], ['world', book.world], ['segment', { goal: '拿到线索', nodes: [] }],
    ['segment_volumes', { volumes: [], threads: [], anchors: [] }], ['concept', { core_loop: '一案一线索' }],
    ['volume_plan', { want: '拿到名额', pressure: '期限将至', units: [{ index: 1, title: '第一单元', chapter_count: 5, loop: '调查与反击完整循环' }] }],
    ['protagonist', null], ['world', null], ['segment', null], ['segment_volumes', null], ['concept', null], ['volume_plan', {}],
    ['spine', { opening: '旧开篇', ending: '旧结局' }], ['lore', {}], ['outline', {}],
  ].map(([type, data], index) => ({ id: index + 1, book_id: 'fixture', job_id: 'history', speaker: 'chief', speaker_name: '主编', kind: 'artifact', content: `快照 ${index + 1}`, payload: { type, data }, created_at: null }))
  await page.goto(`${base}/books/fixture`)
  for (const message of messages) {
    const card = page.getByTestId(`artifact-message-${message.id}`)
    await card.getByRole('button', { name: `展开${message.content}`, exact: true }).click()
    if (message.id === 6) {
      await expect(card).toContainText('这一卷想做成')
      await expect(card).toContainText('卷首处境')
      await expect(card).toContainText('调查与反击完整循环')
    }
  }
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  assert.deepEqual(mutations.map(item => item.path), ['/api/jobs/old-setup/restart-setup', '/api/jobs/old-setup/restart-setup'])
  console.log('通过：重开失败重试/进行中禁用、旧书钩子、只读字段、路由高亮、单块审稿、节点门禁、新旧快照缺字段回归。全部 API 已拦截。')
} catch (error) {
  console.error({ errors, unexpected, body: await page.locator('body').innerText() })
  throw error
} finally {
  await browser.close()
}
