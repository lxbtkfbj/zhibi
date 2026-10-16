/** 第二包任务 3 边界验收：全部 API 请求仅由内存 fixture 应答，不接触任何真实书库。 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4345'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:/Users/cxc/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
const output = resolve('../data/second-package-task3/boundaries.json')
const shots = resolve('../docs/第二包验收')
await mkdir(resolve('../data/second-package-task3'), { recursive: true })
await mkdir(shots, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath })
const page = await browser.newPage({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
const errors = [], unexpected = [], mutations = [], results = []
page.on('pageerror', error => errors.push(error.message))

const character = { id: 'char-1', name: '陆远', aliases: [], role_type: '主角', gender: '男', age: '十九岁', appearance: '旧衣少年', personality: '谨慎而执着', background: '自幼与妹妹相依为命', abilities: '青灯照见旧事', goal: '找到妹妹', want: '赶在封城前拿到线索', location: '青石镇', condition: '尚未入门', notes: '', is_alive: true, first_appearance_chapter: null }
const baseBook = { id: 'boundaries', title: '开书界面边界验收', source: 'new', genre: '悬疑修仙', status: 'ready', idea: '寻找失踪的妹妹', logline: '', style_reference: '', concept: { title: '开书界面边界验收', protagonist_hook: '旧书里的主角钩子', core_loop: '查一宗旧案，找一条妹妹的线索' }, protagonist: {}, world: {}, spine: { core_conflict: '追查真相与镇守隐瞒', protagonist_arc: '从自保到承担', theme: '亲情与选择' }, setup_progress: {}, requirements: [], trial_read_done: false, active_job: null, chapters_final: 0, words_final: 0 }
const node = (id, index, kind, title) => ({ id, index, kind, title, event: `${title}发生的事`, prerequisite: '拿到线索', consequence: '查案更进一步', volume: index === 1 ? 1 : 2, status: 'pencil', origin: 'ai', anchors: [], editor_note: '', techniques: [], segment: null })
const baseNodes = [node('opening', 1, 'opening', '雨夜来信'), node('endpoint', 2, 'milestone', '外门考核'), node('ending', 3, 'ending', '找到妹妹')]
const segment = { number: 1, status: 'confirmed', planned_at: 0, map: '青石镇', trouble: '封城', opponent: '镇守', goal: '通过考核拿到出城名额', goal_link: '获准去妹妹失踪的山门', wait: '陆远能否在封城前拿到名额', reveal: '来信出自妹妹之手', opening: { scene: '边界测试：第一章的旧场面', pressure: '封城只剩三天', first_win: '第二章反将催债人一军', finger: '第一章青灯照出信纸暗纹', hook: '第三章发现妹妹的笔迹' }, carried: '', pursuit: '', finger_next: '', answers: '', finale: false }
const unit = { id: 'unit-1', index: 1, title: '破庙来信', chapter_count: 5, goal: '找出信的来历', conflict: '催债人阻拦', climax: '反制催债人', outcome: '拿到考核名额的线索', loop: '旧的单元循环内容', key_events: [], thread_beats: [], foreshadow_actions: [], tropes: [], resolution: '', status: 'planned', recap: '', editor_note: '', techniques: [], reveals: [] }
const volume = { id: 'volume-1', index: 1, title: '青石镇', want: '拿到出城名额', pressure: '城门将关', stage: '青石镇', summary: '少年查明来信之谜', goal: '入门并出城', climax: '外门考核逆转', antagonist: '镇守', power_range: '从杂役到入门', thread_beats: [], new_characters: ['陆远'], chapter_count: 12, status: 'detailed', recap: '', units: [structuredClone(unit)], target_node_id: 'endpoint', reaches_node: true, editor_note: '', techniques: [] }
const baseBible = { characters: [character], world_entries: [{ id: 'entry-1', category: '规则', name: '旧书城规', content: '夜半不得出城。' }], relationships: [], foreshadowings: [], secrets: [] }
let book = structuredClone(baseBook), nodes = structuredClone(baseNodes), volumes = [structuredClone(volume)], bible = structuredClone(baseBible)

await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname
  // Vite 的 /src/api/*.ts 是前端模块，不是后端 API。
  if (!path.startsWith('/api/')) return route.continue()
  if (request.method() === 'GET') {
    if (path === '/api/books/boundaries/events') return route.fulfill({ status: 204 })
    if (path === '/api/books/boundaries') return route.fulfill({ json: book })
    if (path === '/api/books/boundaries/outline') return route.fulfill({ json: { concept: book.concept, volumes } })
    if (path === '/api/books/boundaries/bible') return route.fulfill({ json: bible })
    if (path === '/api/books/boundaries/nodes') return route.fulfill({ json: nodes })
    if (path === '/api/books/boundaries/secrets') return route.fulfill({ json: bible.secrets })
    if (['chapters', 'threads'].some(suffix => path === `/api/books/boundaries/${suffix}`)) return route.fulfill({ json: [] })
    if (path === '/api/books') return route.fulfill({ json: [] })
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    if (path === '/api/glossary') return route.fulfill({ json: { terms: [] } })
  }
  if (request.method() === 'PATCH' && path === '/api/nodes/endpoint') {
    const body = request.postDataJSON()
    mutations.push({ method: 'PATCH', path, body })
    const target = nodes.find(item => item.id === 'endpoint')
    if (body.segment) target.segment = { ...target.segment, ...body.segment, opening: { ...target.segment.opening, ...body.segment.opening } }
    for (const key of Object.keys(body).filter(key => key !== 'segment')) target[key] = body[key]
    return route.fulfill({ json: target })
  }
  if (request.method() === 'PATCH' && path === '/api/units/unit-1') {
    const body = request.postDataJSON()
    mutations.push({ method: 'PATCH', path, body })
    Object.assign(volumes[0].units[0], body)
    return route.fulfill({ json: volumes[0].units[0] })
  }
  unexpected.push(`${request.method()} ${path}`)
  return route.fulfill({ status: 500, json: { detail: '边界验收未预期的 API 请求，已阻止连接真实接口' } })
})

const manuscript = page.getByRole('main', { name: '稿件', exact: true })
async function open(path) {
  await page.goto(`${base}/books/boundaries/${path}`)
  await expect(page.getByTestId('full-sidebar')).toBeVisible()
  // 手动目录点击关闭自动跟随，防止跨块 flags 验收被 pending 页面抢回。
  await page.getByTestId('full-sidebar').locator(`a[href="/books/boundaries/${path}"]`).last().click()
  await expect(page).toHaveURL(`${base}/books/boundaries/${path}`)
}
async function shot(name) {
  const filename = `任务3-边界-${name}.png`
  // 既有抽屉仍有 0.38 秒的入场动画，截图应取稳定终态而非半透明帧。
  await page.waitForTimeout(450)
  await page.screenshot({ path: resolve(shots, filename), fullPage: true })
  return `docs/第二包验收/${filename}`
}
function setupJob(status, piece, flags = {}) {
  book.status = 'setting_up'
  book.setup_progress = { mode: 'puzzle', current: piece, pieces: { concept: 'confirmed', protagonist: 'confirmed', world: 'confirmed', segment: piece === 'segment' ? 'waiting' : 'confirmed', first_volume: piece === 'first_volume' ? 'waiting' : 'todo' } }
  book.active_job = { id: 'boundary-job', book_id: book.id, kind: 'book_setup', setup_flow: 2, status, pending: status === 'waiting_author' ? { kind: 'setup_piece', flow: 2, piece, flags, round: 1, warnings: [] } : null, error: '', created_at: null, updated_at: null, finished_at: null }
}

try {
  await open('protagonist')
  await expect(manuscript).toContainText('这本书开书时还没有主角卡')
  await expect(manuscript).toContainText('旧书里的主角钩子')
  await expect(manuscript.locator('.setup-question')).toHaveCount(0)
  results.push({ check: '旧书无主角卡：保留说明、钩子及人物资料', passed: true, screenshot: await shot('旧书主角') })

  await open('world')
  await expect(manuscript.locator('.setup-question')).toHaveCount(0)
  await expect(manuscript).toContainText('旧书城规')
  results.push({ check: '旧书 world 为空：只有设定条目，不生成假回答', passed: true, screenshot: await shot('旧书世界') })

  await open('spine')
  await expect(manuscript.getByTestId('first-segment-panel')).toHaveCount(0)
  await expect(manuscript.locator('[data-testid^="story-node-"]')).toHaveCount(3)
  await expect(manuscript.getByTestId('unplanned-segment')).toHaveCount(0)
  results.push({ check: '旧书无 segment：保持节点时间轴，不误显示第一段和未规划带', passed: true, screenshot: await shot('旧书地图') })

  await open('volume/1')
  await expect(manuscript.locator('.setup-question')).toHaveCount(7)
  await expect(manuscript.locator('#q-landing')).toHaveCount(0)
  await expect(manuscript.locator('#q-units')).toContainText('旧的单元循环内容')
  results.push({ check: '旧卷无 opening：七个新分节正常，隐藏开篇落地', passed: true, screenshot: await shot('旧书卷页') })

  nodes[1].segment = structuredClone(segment)
  setupJob('running', 'segment')
  await open('spine')
  const panel = manuscript.getByTestId('first-segment-panel')
  await expect(panel.locator('.setup-question')).toHaveCount(8)
  await expect(manuscript).toContainText('编辑部正在工作，这里暂时只能看、不能改。')
  await expect(panel.locator('[title="点击修改"]')).toHaveCount(0)
  await expect(manuscript.getByRole('textbox')).toHaveCount(0)
  await expect(manuscript.getByRole('button', { name: '钉死节点 2', exact: true })).toBeDisabled()
  await expect(manuscript.getByTestId('unplanned-segment')).toContainText('写到这里之前，主编会先来定下一段')
  assert.equal(await manuscript.getByTestId('unplanned-segment').evaluate(element => element.tagName), 'DIV')
  results.push({ check: '编辑部运行中第一段和时间轴只读；未规划带静态不可展开', passed: true, screenshot: await shot('第一段锁定') })

  await open('volume/1')
  await expect(manuscript.locator('.setup-question')).toHaveCount(8)
  await expect(manuscript.locator('[title="点击修改"]')).toHaveCount(0)
  await expect(manuscript.getByRole('textbox')).toHaveCount(0)
  await expect(manuscript.locator('#q-landing')).toContainText(segment.opening.scene)
  results.push({ check: '编辑部运行中卷与单元均只读；第一卷显示五项开篇', passed: true, screenshot: await shot('卷页锁定') })

  setupJob('waiting_author', 'segment', { opening: ['开篇边界提醒'], want: ['不应串到卷页的提醒'] })
  await open('spine')
  await expect(manuscript.locator('#q-opening')).toContainText('需要再看看：开篇边界提醒')
  await expect(manuscript.locator('#q-goal')).not.toContainText('开篇边界提醒')
  await expect(manuscript.getByText('不应串到卷页的提醒', { exact: false })).toHaveCount(0)
  await manuscript.locator('#q-opening').getByRole('button', { name: segment.opening.scene, exact: true }).click()
  await manuscript.locator('#q-opening').getByRole('textbox', { name: '编辑文字', exact: true }).fill('边界测试：作者改过的第一章场面')
  await manuscript.locator('#q-opening').getByRole('textbox').press('Control+Enter')
  await expect(manuscript.locator('#q-opening')).toContainText('边界测试：作者改过的第一章场面')
  await expect(manuscript.locator('#q-opening').getByRole('textbox')).toHaveCount(0)
  assert.deepEqual(mutations.at(-1), { method: 'PATCH', path: '/api/nodes/endpoint', body: { segment: { opening: { scene: '边界测试：作者改过的第一章场面' } } } })
  assert.equal(nodes[1].segment.opening.hook, segment.opening.hook)
  assert.equal(nodes[1].segment.goal, segment.goal)
  results.push({ check: '第一段提醒只在对应题；opening 编辑只 PATCH 一个字段，兄弟字段保留', passed: true, screenshot: await shot('开篇最小保存') })

  await open('volume/1')
  await expect(manuscript.locator('#q-want')).not.toContainText('不应串到卷页的提醒')
  await expect(manuscript.locator('.setup-question').filter({ hasText: '需要再看看：' })).toHaveCount(0)
  await expect(manuscript.locator('#q-landing')).toContainText('边界测试：作者改过的第一章场面')
  results.push({ check: '等待 segment 时 flags 不串到卷页；开篇改动同步到只读落地题', passed: true, screenshot: await shot('提醒不串卷页') })

  setupJob('waiting_author', 'first_volume', { units: ['单元边界提醒'], opening: ['不应串到第一段的提醒'] })
  await open('volume/1')
  await expect(manuscript.locator('#q-units')).toContainText('需要再看看：单元边界提醒')
  const loop = manuscript.locator('#q-units').getByRole('button', { name: '旧的单元循环内容', exact: true })
  await loop.click()
  await manuscript.locator('#q-units').getByRole('textbox', { name: '编辑文字', exact: true }).fill('查案找到线索，反击对手，推进寻找妹妹')
  await manuscript.locator('#q-units').getByRole('textbox').press('Control+Enter')
  await expect(manuscript.locator('#q-units').getByRole('textbox')).toHaveCount(0)
  assert.deepEqual(mutations.at(-1), { method: 'PATCH', path: '/api/units/unit-1', body: { loop: '查案找到线索，反击对手，推进寻找妹妹' } })
  await expect(manuscript.locator('#q-units')).toContainText('查案找到线索，反击对手，推进寻找妹妹')
  results.push({ check: '单元循环可编辑且请求仅含 loop；卷题提醒定位正确', passed: true, screenshot: await shot('单元循环保存') })

  await open('spine')
  await expect(manuscript.locator('.setup-question').filter({ hasText: '需要再看看：' })).toHaveCount(0)
  results.push({ check: '等待 first_volume 时 flags 不串到第一段同名 opening 题', passed: true, screenshot: await shot('提醒不串第一段') })

  book = structuredClone(baseBook)
  await open('characters')
  await manuscript.locator('#character-char-1').click()
  const sheet = page.getByRole('dialog')
  const editable = sheet.getByRole('button', { name: character.personality, exact: true })
  await editable.hover()
  const display = await editable.evaluate(element => {
    const rect = element.getBoundingClientRect(), css = getComputedStyle(element), pencil = element.querySelector('svg')?.getBoundingClientRect()
    return { textX: rect.x + parseFloat(css.paddingLeft), rect: { x: rect.x, right: rect.right, top: rect.top, bottom: rect.bottom }, pencil: pencil && { x: pencil.x, right: pencil.right, top: pencil.top, bottom: pencil.bottom } }
  })
  assert.ok(display.pencil.x >= display.rect.x && display.pencil.right <= display.rect.right)
  assert.ok(display.pencil.top >= display.rect.top && display.pencil.bottom <= display.rect.bottom)
  const hoverShot = await shot('人物悬停对齐')
  await editable.click()
  const textarea = sheet.getByRole('textbox', { name: '编辑文字', exact: true })
  const editingTextX = await textarea.evaluate(element => {
    const rect = element.getBoundingClientRect(), css = getComputedStyle(element)
    return rect.x + parseFloat(css.borderLeftWidth) + parseFloat(css.paddingLeft)
  })
  assert.ok(Math.abs(display.textX - editingTextX) <= 1, `人物文字左边缘切换位移 ${editingTextX - display.textX}px`)
  await textarea.press('Escape')
  results.push({ check: '人物页 Editable 悬停铅笔在底色内、显示态与编辑态文字左缘差不超过 1px', passed: true, screenshot: hoverShot, alignment: { displayTextX: display.textX, editingTextX } })

  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  assert.equal(mutations.length, 2)
  console.log(`通过 ${results.length} 项边界验收；全部 API mock，只有 opening.scene 与 loop 两笔内存 PATCH。`)
} catch (error) {
  results.push({ passed: false, error: error.stack || String(error), screenshot: await shot('失败现场'), body: await page.locator('body').innerText() })
  throw error
} finally {
  await writeFile(output, JSON.stringify({ checkedAt: new Date().toISOString(), baseURL: base, allApiMocked: true, noRealLibraryAccess: true, results, errors, unexpected, mutations }, null, 2))
  await browser.close()
}
