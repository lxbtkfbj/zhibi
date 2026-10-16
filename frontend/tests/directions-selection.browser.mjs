/** 任务 6 的兼容与交互回归。所有 API 都拦截，不读取或修改作者书库。 */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4342'
const artifacts = resolve(process.env.TEST_ARTIFACT_DIR || '../data/first-package-task6/ui-regression')
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
await mkdir(artifacts, { recursive: true })

const options = [
  '约 50 万字（短篇，约 170 章）', '约 100 万字（中篇，约 330 章）',
  '约 200 万字（长篇，约 670 章）', '约 300 万字（长篇，约 1000 章）',
  '500 万字以上（超长篇，约 1670 章起）',
]
const pending = {
  kind: 'setup_directions', reference: '主角经营恐怖屋，用任务解锁新场景，以悬疑案件连接城市中的旧案；原作后期舞台的具体边界不确定。',
  recommended: 0,
  directions: ['旧案追凶流', '经营扩张流', '失踪追查流'].map((name, index) => ({
    name, titles: [`第${index + 1}间恐怖屋`, `恐怖屋老板只想查清旧案${index ? '' : '却发现全城都在等他开门'}`],
    logline: `恐怖屋老板在第 ${index + 1} 个故事里追查旧案。`, protagonist: '守住恐怖屋的年轻老板',
    golden_finger: '完成任务解锁场景，场景越多能收集的线索越多，但每次任务都需要自己走进未知。',
    opening: '开门前收到一封失踪者来信', selling_points: ['经营成长', '旧案悬疑'],
    stage_ladder: '老城区 → 整座城市 → 省城 → 全国', tone: '悬疑中有暖意', reader: '喜欢经营与解谜的读者',
    difference: `从第 ${index + 1} 种未定线索出发`, editor_note: '保留作者指定的经营设定。', techniques: [],
  })),
  length: { question: '这本书想写多长？', options, recommended: 2, chapter_words: 3000 },
}

async function scenario({ legacy = false, noReference = false, failFirst = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = [], unexpected = [], requests = []
  page.on('pageerror', error => errors.push(error.message))
  const data = structuredClone(pending)
  if (legacy) {
    delete data.reference
    delete data.length.chapter_words
    data.length.options = ['100 万字左右', '200 万字左右', '300 万字以上']
    data.length.recommended = 1
    for (const direction of data.directions) delete direction.titles
  }
  if (noReference) data.reference = ''
  const job = { id: 'mock-task6-job', book_id: 'mock-task6-book', kind: 'book_setup', status: 'waiting_author', pending: data, error: '', created_at: '2026-10-16T00:00:00Z', updated_at: '2026-10-16T00:00:00Z', finished_at: null }
  const book = { id: job.book_id, title: '方向交互测试', source: 'new', genre: '', status: 'setting_up', idea: '借用《某某》的设定', logline: '', job_status: job.status, created_at: job.created_at, updated_at: job.updated_at, style_reference: '', concept: {}, spine: {}, setup_progress: { mode: 'puzzle', current: 'concept', pieces: { concept: 'waiting' } }, requirements: [], trial_read_done: false, active_job: job, chapters_final: 0, words_final: 0 }
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (request.method() === 'POST' && path === `/api/jobs/${job.id}/directions`) {
      requests.push(request.postDataJSON())
      if (failFirst && requests.length === 1) return route.fulfill({ status: 422, json: { detail: '模拟提交失败，请重试。' } })
      return route.fulfill({ json: { ...job, status: 'queued', pending: null, updated_at: '2026-10-16T00:00:01Z' } })
    }
    if (request.method() === 'GET') {
      if (path === `/api/books/${book.id}/events`) return route.fulfill({ status: 204 })
      if (path === `/api/books/${book.id}`) return route.fulfill({ json: book })
      if (path === `/api/books/${book.id}/outline`) return route.fulfill({ json: { volumes: [] } })
      if (path === `/api/books/${book.id}/bible`) return route.fulfill({ json: { characters: [], world_entries: [], relationships: [], foreshadowings: [], secrets: [] } })
      if (['nodes', 'chapters', 'threads', 'secrets'].some(suffix => path === `/api/books/${book.id}/${suffix}`)) return route.fulfill({ json: [] })
      if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
      if (path === '/api/books') return route.fulfill({ json: [] })
      if (path === '/api/glossary') return route.fulfill({ json: { terms: [] } })
    }
    unexpected.push(`${request.method()} ${path}`)
    return route.fulfill({ status: 404, json: { detail: '未预期的测试请求' } })
  })
  await page.goto(`${baseURL}/books/${book.id}`)
  const selection = page.getByRole('region', { name: '选择开书方向', exact: true })
  try { await expect(selection).toBeVisible() } catch (error) {
    console.error({ errors, unexpected, page: await page.locator('body').innerText() })
    throw error
  }
  return { page, selection, requests, check: () => { assert.deepEqual(unexpected, []); assert.deepEqual(errors, []) } }
}

try {
  const modern = await scenario({ failFirst: true })
  const { page, selection, requests } = modern
  const reference = selection.getByRole('region', { name: '主编对对标作品的理解' })
  await expect(reference).toContainText(pending.reference)
  await expect(reference).toContainText('理解得不对？在下面「都不满意，重新出」里告诉主编，主编会按你的说法重出。')
  await expect(selection.getByRole('radio')).toHaveCount(5)
  await expect(selection.getByRole('radio').nth(2)).toBeChecked()
  await expect(selection).toContainText('按每章约 3000 字估算章数。想要章数更多、每章更短，先到「本书设置」改每章字数，再点「都不满意，重新出」。')
  const first = selection.getByRole('article', { name: '方向 1：旧案追凶流' })
  await expect(first.getByRole('heading', { name: '方向一 · 旧案追凶流', exact: true })).toBeVisible()
  assert.equal(await first.getByRole('heading').evaluate(element => getComputedStyle(element).fontSize), '14px')
  const titleOne = first.getByRole('button', { name: `《${pending.directions[0].titles[0]}》`, exact: true })
  const titleTwo = first.getByRole('button', { name: `《${pending.directions[0].titles[1]}》`, exact: true })
  await expect(titleOne).toHaveAttribute('aria-pressed', 'false')
  await titleOne.focus(); await page.keyboard.press('Enter')
  await expect(titleOne).toHaveAttribute('aria-pressed', 'true')
  await titleTwo.click()
  await expect(titleOne).toHaveAttribute('aria-pressed', 'false')
  await expect(titleTwo).toHaveAttribute('aria-pressed', 'true')
  await titleTwo.click()
  await expect(titleTwo).toHaveAttribute('aria-pressed', 'false')
  await titleOne.click()
  await selection.getByRole('article', { name: '方向 2：经营扩张流' }).getByRole('button', { name: `《${pending.directions[1].titles[0]}》` }).click()
  await selection.getByRole('radio').nth(4).check()
  await selection.getByRole('textbox', { name: '混搭要求' }).fill('  保留方向二的经营线索。  ')
  await first.getByRole('button', { name: '选这个', exact: true }).click()
  await expect(selection.getByText('模拟提交失败，请重试。', { exact: true })).toBeVisible()
  await expect(titleOne).toHaveAttribute('aria-pressed', 'true')
  await expect(selection.getByRole('radio').nth(4)).toBeChecked()
  await expect(selection.getByRole('textbox', { name: '混搭要求' })).toHaveValue('  保留方向二的经营线索。  ')
  assert.deepEqual(requests[0], { action: 'choose', choice: 0, title: pending.directions[0].titles[0], length: options[4], mix: '保留方向二的经营线索。' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('tab', { name: '稿件', exact: true }).click()
  await first.scrollIntoViewIfNeeded()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  assert.equal(await selection.evaluate(element => element.scrollWidth <= element.clientWidth), true)
  assert.equal(await titleTwo.evaluate(element => element.scrollWidth <= element.clientWidth), true)
  await page.screenshot({ path: resolve(artifacts, 'direction-titles-narrow.png') })
  await first.getByRole('button', { name: '选这个', exact: true }).click()
  await expect(selection).toHaveCount(0)
  assert.equal(requests.length, 2)
  assert.deepEqual(requests[1], requests[0])
  modern.check()
  await page.close()
  console.log('PASS 对标理解、五档篇幅、小号方向标签、书名键盘选择/单选/取消、按卡提交、失败保留与 390px 窄屏')

  const old = await scenario({ legacy: true })
  await expect(old.selection.getByRole('region', { name: '主编对对标作品的理解' })).toHaveCount(0)
  await expect(old.selection.getByRole('group', { name: '书名候选' })).toHaveCount(0)
  await expect(old.selection.getByText(/按每章约/)).toHaveCount(0)
  await expect(old.selection.getByRole('radio')).toHaveCount(3)
  await expect(old.selection.getByRole('radio').nth(1)).toBeChecked()
  await old.selection.getByRole('button', { name: '选这个', exact: true }).first().click()
  await expect(old.selection).toHaveCount(0)
  assert.deepEqual(old.requests, [{ action: 'choose', choice: 0, length: '200 万字左右', mix: '' }])
  old.check()
  await old.page.close()
  console.log('PASS 旧 pending 缺 reference/titles/chapter_words，仍按原篇幅展示并无书名提交')

  const redo = await scenario({ noReference: true })
  await expect(redo.selection.getByRole('region', { name: '主编对对标作品的理解' })).toHaveCount(0)
  await redo.selection.getByRole('button', { name: '都不满意，重新出', exact: true }).click()
  await redo.selection.getByRole('button', { name: '重新出方向', exact: true }).click()
  await expect(redo.selection.getByRole('alert')).toHaveText('写一下哪里不满意')
  assert.deepEqual(redo.requests, [])
  await redo.selection.getByRole('textbox', { name: '不满意的地方' }).fill('  理解不对，请保留恐怖屋经营，不要改成缝尸。  ')
  await redo.selection.getByRole('button', { name: '重新出方向', exact: true }).click()
  await expect(redo.selection).toHaveCount(0)
  assert.deepEqual(redo.requests, [{ action: 'redo', feedback: '理解不对，请保留恐怖屋经营，不要改成缝尸。' }])
  redo.check()
  await redo.page.close()
  console.log('PASS 无对标作品时不展示理解块，重出校验与原样反馈提交')
} finally {
  await browser.close()
}
