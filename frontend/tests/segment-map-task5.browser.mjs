/** 段带边界验收：所有 API 都由内存 fixture 应答，绝不访问真实书库。 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4347'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:/Users/cxc/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
const output = resolve('../data/second-package-task5/map-boundaries.json')
const shots = resolve('../docs/第二包验收')
const browser = await chromium.launch({ headless: true, executablePath })
const page = await browser.newPage({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
const errors = [], unexpected = [], mutations = [], results = []
page.on('pageerror', error => errors.push(error.message))
const settings = { setup_mode: 'puzzle', title_style: 'chief', title_custom: '', person: 'third', intimacy: 'heart', intimacy_custom: '', chapter_words: 3000, other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 2, review_strictness: 'standard', volume_audit: true, volume_approval: true, segment_approval: true, trial_read: true }
const book = { id: 'map-boundary', title: '段带边界验收', source: 'new', genre: '玄幻', status: 'writing', idea: '测试短段', logline: '', style_reference: '', concept: { title: '段带边界验收', target_length: 100, chapter_words: 3000 }, protagonist: {}, world: {}, spine: {}, setup_progress: {}, requirements: [], trial_read_done: true, active_job: null, chapters_final: 9, words_final: 27000 }
const plan = number => ({ number, status: 'confirmed', planned_at: 6 * (number - 1), map: `第 ${number} 段地图`, trouble: '盘查', opponent: '统领', goal: `第 ${number} 段目标`, goal_link: '更接近兄长', wait: `第 ${number} 段期待`, reveal: `第 ${number} 段揭晓`, opening: null, carried: 'E1 与 F2 留待查清', pursuit: '找到兄长', finger_next: '看清旧物来历', answers: '军令来自山门', finale: false })
const node = (id, index, kind, title, segment = null) => ({ id, index, kind, title, segment, event: `${title}发生的事`, prerequisite: '拿到线索', consequence: '查案更进一步', volume: index, status: 'pencil', origin: 'ai', anchors: [], editor_note: '', techniques: [] })
let nodes = [node('opening', 1, 'opening', '开篇'), node('first', 2, 'milestone', '山门', plan(1)), node('second', 3, 'milestone', '寒原追查', plan(2)), node('future', 4, 'milestone', '王城'), node('ending', 5, 'ending', '结局')]
const volume = (index, target, status) => ({ id: `v${index}`, index, title: `卷 ${index}`, want: '拿到线索', pressure: '盘查', stage: '寒原', summary: '追回家书', goal: '找到兄长', climax: '揭晓来历', antagonist: '统领', power_range: '', thread_beats: [], new_characters: [], chapter_count: 6, status, recap: '', units: [], target_node_id: target, reaches_node: true, editor_note: '', techniques: [] })
let volumes = [volume(1, 'first', 'done'), volume(2, 'second', 'approved')]
const chapter = (index, volume) => ({ id: `c${index}`, index, volume_id: `v${volume}`, unit_id: null, status: 'final', title: `第 ${index} 章`, word_count: 3000, summary: '', attempts: 1, outline: null })
let chapters = Array.from({ length: 9 }, (_, at) => chapter(at + 1, at < 6 ? 1 : 2))
await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
  if (!path.startsWith('/api/')) return route.continue()
  if (method === 'GET') {
    if (path === '/api/books/map-boundary/events') return route.fulfill({ status: 204 })
    if (path === '/api/books/map-boundary') return route.fulfill({ json: book })
    if (path === '/api/books/map-boundary/settings') return route.fulfill({ json: { settings, rules_text: '' } })
    if (path === '/api/books/map-boundary/outline') return route.fulfill({ json: { concept: book.concept, volumes } })
    if (path === '/api/books/map-boundary/nodes') return route.fulfill({ json: nodes })
    if (path === '/api/books/map-boundary/chapters') return route.fulfill({ json: chapters })
    if (path === '/api/books/map-boundary/bible') return route.fulfill({ json: { characters: [], relationships: [], world_entries: [], foreshadowings: [], secrets: [] } })
    if (['threads', 'secrets', 'requirements'].some(suffix => path === `/api/books/map-boundary/${suffix}`)) return route.fulfill({ json: [] })
    if (path === '/api/books') return route.fulfill({ json: [] })
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    if (path === '/api/glossary') return route.fulfill({ json: { terms: [] } })
  }
  if (method === 'PATCH' && path === '/api/nodes/second') {
    const body = request.postDataJSON()
    mutations.push({ path, body })
    const target = nodes.find(node => node.id === 'second')
    target.segment = { ...target.segment, ...body.segment }
    return route.fulfill({ json: target })
  }
  unexpected.push(`${method} ${path}`)
  return route.fulfill({ status: 500, json: { detail: '未预期请求，已阻止连接真实接口' } })
})
const manuscript = page.getByRole('main', { name: '稿件', exact: true })
const band = () => manuscript.locator('[data-testid="writing-segment-band"][data-segment-number="2"]')
async function open(path = 'spine') {
  // 从设置进入，初始就关闭跟随；等待作者时也能检查地图，不跳到待确认卷页。
  await page.goto(`${base}/books/map-boundary/settings`)
  await expect(manuscript.getByRole('heading', { name: '本书设置', exact: true })).toBeVisible()
  await page.getByTestId('full-sidebar').locator(`a[href="/books/map-boundary${path ? `/${path}` : ''}"]`).last().click()
  await expect(page).toHaveURL(`${base}/books/map-boundary${path ? `/${path}` : ''}`)
}
async function shot(name) {
  await mkdir(shots, { recursive: true })
  const filename = `任务5-边界-段带${name}.png`
  await page.screenshot({ path: resolve(shots, filename), fullPage: true })
  return `docs/第二包验收/${filename}`
}
try {
  await open()
  await expect(manuscript.locator('[data-segment-number="1"][data-segment-status="done"]')).toHaveCount(1)
  await expect(band()).toHaveAttribute('data-segment-status', 'writing')
  await expect(band()).toContainText('正在写：第 2 卷 3/6 章')
  await expect(manuscript.getByRole('button', { name: '现在就规划下一段', exact: true })).toHaveCount(1)
  await expect(manuscript.locator('[data-segment-end="future"]')).toContainText('现在就规划下一段')
  await expect(manuscript.locator('[data-segment-end="ending"]')).not.toContainText('现在就规划下一段')
  await band().locator('summary').first().click()
  const snapshot = structuredClone(nodes[2].segment)
  for (const field of ['goal', 'wait', 'reveal', 'map']) {
    await band().getByRole('button', { name: nodes[2].segment[field], exact: true }).click()
    const textbox = band().getByRole('textbox', { name: '编辑文字', exact: true })
    await textbox.fill(`作者编辑 ${field}`)
    await textbox.press('Control+Enter')
    await expect(textbox).toHaveCount(0)
    assert.deepEqual(mutations.at(-1), { path: '/api/nodes/second', body: { segment: { [field]: `作者编辑 ${field}` } } })
    snapshot[field] = `作者编辑 ${field}`
    assert.deepEqual(nodes[2].segment, snapshot)
  }
  await expect(band().getByText('上一段的线头', { exact: true })).not.toBeVisible()
  await band().getByText('定下一段时的四件事', { exact: true }).click()
  await expect(band().getByText('上一段的线头', { exact: true })).toBeVisible()
  await expect(band().getByRole('button', { name: 'E1 与 F2 留待查清', exact: true })).toHaveCount(0)
  await band().scrollIntoViewIfNeeded()
  results.push({ check: '段状态与卷内进度正确；仅首个 later 提供规划；四项最小 PATCH 保留全部兄弟字段；四件事默认收起且只读', screenshot: await shot('最小保存') })

  await open('')
  await expect(manuscript.getByTestId('current-segment-goal')).toHaveText('第 2 段 · 想做成：作者编辑 goal')
  results.push({ check: '概览读取正在写的段，显示保存后的目标' })

  for (const status of ['queued', 'running', 'waiting_author']) {
    book.active_job = { id: 'job', book_id: book.id, kind: 'write_book', setup_flow: null, status, pending: status === 'waiting_author' ? { kind: 'volume_review', volume: 2, title: '寒原', issues: [] } : null, error: '', created_at: '', updated_at: '', finished_at: null }
    await open()
    await expect(manuscript.getByRole('button', { name: '现在就规划下一段', exact: true })).toHaveCount(0)
    await band().locator('summary').first().click()
    if (status !== 'waiting_author') {
      await expect(band().locator('[title="点击修改"]')).toHaveCount(0)
      await expect(band().getByRole('textbox')).toHaveCount(0)
    } else {
      await expect(band().getByRole('button', { name: '作者编辑 goal', exact: true })).toHaveCount(1)
    }
  }
  results.push({ check: 'queued/running 时段四项只读；queued/running/waiting_author 都不提供手动规划；等拍板时仍允许编辑已保存段' })
  assert.equal(mutations.length, 4)

  book.active_job = null
  for (const approval of [true, false]) {
    settings.segment_approval = approval
    await open()
    await manuscript.getByRole('button', { name: '现在就规划下一段', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '现在就规划下一段？' })
    await expect(dialog).toContainText('规划第 3 段：下一张地图、对手、目标和终点。')
    await expect(dialog).toContainText(approval ? '规划好之后会停下来等你确认。规划期间不会写新章节。' : '规划好之后按设置直接通过，群聊里会告诉你。')
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
  }
  results.push({ check: '手动规划确认框根据本书设置切换确认/自动通过文案，取消不发送规划请求' })

  chapters = [{ ...chapter(1, 1), status: 'drafting' }]
  book.chapters_final = 0
  volumes[0].status = 'approved'
  await open()
  await expect(manuscript.locator('[data-testid="writing-segment-band"][data-segment-number="1"]')).toContainText('正在写：第 1 卷 0/6 章')
  await expect(manuscript.getByTestId('story-map-strip')).toHaveCount(0)
  results.push({ check: '首章尚未定稿时地图仍隐藏，但正在写的段带显示第 1 卷 0/6 章' })

  nodes.at(-1).segment = plan(3)
  volumes.push(volume(3, 'ending', 'done'))
  volumes[0].status = 'done'
  volumes[1].status = 'done'
  chapters = Array.from({ length: 18 }, (_, at) => chapter(at + 1, Math.floor(at / 6) + 1))
  book.chapters_final = 18
  await open()
  await expect(manuscript.getByRole('button', { name: '现在就规划下一段', exact: true })).toHaveCount(0)
  await expect(manuscript.getByTestId('story-map-summary')).toHaveText('全书完结')
  await expect(manuscript.getByTestId('story-map-cursor')).toHaveAttribute('style', 'left: 100%;')
  results.push({ check: '结局已规划时即使仍有未规划远景也不再提供手动规划；18 章实写/333 章估计完全写完时地图游标仍抵达结局' })

  nodes = nodes.map(node => ({ ...node, segment: null }))
  chapters = chapters.slice(0, 9)
  volumes = volumes.slice(0, 2)
  volumes[1].status = 'approved'
  book.chapters_final = 9
  await open()
  await expect(manuscript.getByTestId('writing-segment-band')).toHaveCount(0)
  await expect(manuscript.getByRole('button', { name: '现在就规划下一段', exact: true })).toHaveCount(0)
  await expect(manuscript.getByTestId('story-map-summary')).not.toContainText('第 2 段')
  await open('')
  await expect(manuscript.getByTestId('current-segment-goal')).toHaveCount(0)
  results.push({ check: '旧书保持旧卷带/无段号，无手动规划与概览段目标' })
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
} finally {
  await mkdir(resolve('../data/second-package-task5'), { recursive: true })
  await writeFile(output, JSON.stringify({ isolation: '全部 /api/ 请求由内存 fixture 应答，不访问任何真实书库', results, mutations, errors, unexpected }, null, 2))
  await browser.close()
}
console.log(JSON.stringify({ passed: results.length, output, errors, unexpected }, null, 2))
