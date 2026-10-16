/** 写作设置边界回归：所有 API 都由本地 fixture 应答，绝不访问真实书库。 */
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4347'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:/Users/cxc/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
const output = resolve('../data/second-package-task5/settings-boundaries.json')
const browser = await chromium.launch({ headless: true, executablePath })
const context = await browser.newContext({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
const page = await context.newPage()
const errors = [], unexpected = [], writes = [], results = []
page.on('pageerror', error => errors.push(error.message))
const settings = { setup_mode: 'puzzle', title_style: 'chief', title_custom: '', person: 'third', intimacy: 'heart', intimacy_custom: '', chapter_words: 2000, other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 2, review_strictness: 'standard', volume_audit: true, volume_approval: true, segment_approval: true, trial_read: true }
const book = { id: 'settings-boundary', title: '写作设置边界验收', source: 'new', genre: '玄幻', status: 'ready', idea: '测试设置', logline: '', style_reference: '', concept: { title: '写作设置边界验收', target_length: 50, chapter_words: 4000, core_loop: '必须保留的作者原文' }, protagonist: { name: '陆远', pursuit: '找到妹妹' }, world: {}, spine: {}, setup_progress: {}, requirements: [], trial_read_done: false, active_job: null, chapters_final: 0, words_final: 0 }
const character = { id: 'hero', name: '陆远', role_type: '主角', aliases: [], gender: '', age: '', appearance: '', personality: '谨慎', background: '', abilities: '', goal: '找到妹妹', want: '拿到城门钥匙', location: '', condition: '', notes: '', is_alive: true, first_appearance_chapter: null }
let failNext = false, delayNext = false
await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
  if (!path.startsWith('/api/')) return route.continue()
  if (method === 'GET') {
    if (path === '/api/books/settings-boundary/events') return route.fulfill({ status: 204 })
    if (path === '/api/books/settings-boundary') return route.fulfill({ json: book })
    if (path === '/api/books/settings-boundary/settings') { await new Promise(resolve => setTimeout(resolve, 150)); return route.fulfill({ json: { settings, rules_text: '' } }) }
    if (path === '/api/books/settings-boundary/outline') return route.fulfill({ json: { concept: book.concept, volumes: [] } })
    if (path === '/api/books/settings-boundary/bible') return route.fulfill({ json: { characters: [character], relationships: [], world_entries: [], foreshadowings: [], secrets: [] } })
    if (['chapters', 'nodes', 'threads', 'secrets', 'requirements'].some(suffix => path === `/api/books/settings-boundary/${suffix}`)) return route.fulfill({ json: [] })
    if (path === '/api/books') return route.fulfill({ json: [] })
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    if (path === '/api/glossary') return route.fulfill({ json: { terms: [] } })
  }
  if (method === 'PATCH') {
    const body = request.postDataJSON()
    writes.push({ path, body })
    if (path === '/api/books/settings-boundary') {
      if (delayNext) { delayNext = false; await new Promise(resolve => setTimeout(resolve, 180)) }
      if (failNext) { failNext = false; return route.fulfill({ status: 503, json: { detail: '篇幅测试保存失败，请重试' } }) }
      assert.deepEqual(Object.keys(body), ['concept'])
      assert.deepEqual(Object.keys(body.concept), ['target_length'])
      book.concept = { ...book.concept, ...body.concept }
      return route.fulfill({ json: book })
    }
    if (path === '/api/books/settings-boundary/settings') {
      Object.assign(settings, body)
      return route.fulfill({ json: { settings, rules_text: '' } })
    }
    if (path === '/api/characters/hero') { Object.assign(character, body); return route.fulfill({ json: character }) }
  }
  unexpected.push(`${method} ${path}`)
  return route.fulfill({ status: 500, json: { detail: '未预期请求，已阻止连接真实接口' } })
})
const manuscript = page.getByRole('main', { name: '稿件', exact: true })
const input = () => manuscript.getByRole('spinbutton', { name: '全书计划写多长（万字）' })
const countLengthWrites = () => writes.filter(write => write.path === '/api/books/settings-boundary').length
try {
  await page.goto(`${base}/books/settings-boundary/settings`)
  await expect(input()).toHaveValue('50')
  assert.equal(writes.length, 0)
  await expect(manuscript).toContainText('按每章约 2000 字，约 250 章')
  results.push('延迟初次读取不保存默认值，优先用本书章字数')

  book.concept.core_loop = '服务端同时更新的作者原文'
  delayNext = true
  await input().fill('20')
  await input().press('Enter')
  await input().blur()
  await expect.poll(() => book.concept.target_length).toBe(20)
  await expect(input()).toHaveValue('20')
  assert.equal(countLengthWrites(), 1)
  assert.equal(book.concept.core_loop, '服务端同时更新的作者原文')
  await input().fill('25')
  await input().blur()
  await expect.poll(() => book.concept.target_length).toBe(25)
  assert.equal(countLengthWrites(), 2)
  results.push('回车/失焦仅保存篇幅，快速重复不发双写，不覆盖并发更新的其他概念字段')

  failNext = true
  await input().fill('30')
  await input().press('Enter')
  await expect(manuscript.getByText('篇幅测试保存失败，请重试', { exact: true })).toBeVisible()
  await expect(input()).toHaveValue('30')
  assert.equal(book.concept.target_length, 25)
  await manuscript.getByRole('button', { name: '重试保存篇幅' }).click()
  await expect.poll(() => book.concept.target_length).toBe(30)
  await expect(input()).toHaveValue('30')
  const afterRetry = countLengthWrites()
  await input().fill('1001')
  await input().blur()
  await expect(manuscript.getByText('请填写 5–1000 之间的整数（万字）', { exact: true })).toBeVisible()
  assert.equal(countLengthWrites(), afterRetry)
  await input().fill('30')
  await input().blur()
  results.push('保存失败保留草稿并能重试；越界不发请求')

  await manuscript.getByRole('switch', { name: '每一段开写前先给我确认' }).click()
  await expect.poll(() => settings.segment_approval).toBe(false)
  assert.equal(settings.volume_approval, true)
  await page.reload()
  await expect(manuscript.getByRole('switch', { name: '每一段开写前先给我确认' })).toHaveAttribute('aria-checked', 'false')
  results.push('段确认开关独立保存且刷新保留，不改卷纲拍板')

  for (const status of ['queued', 'running']) {
    book.active_job = { id: 'writing-job', book_id: book.id, kind: 'write', setup_flow: null, status, pending: null, error: '', created_at: '', updated_at: '', finished_at: null }
    await page.reload()
    await expect(input()).toBeDisabled()
    await expect(manuscript.getByText('编辑部工作时不能改，等这一步做完', { exact: true })).toBeVisible()
    await expect(manuscript.getByRole('switch', { name: '每一段开写前先给我确认' })).toBeEnabled()
  }
  results.push('排队/运行中篇幅禁用，普通写作设置仍可编辑')

  book.active_job = null
  await page.goto(`${base}/books/settings-boundary/protagonist`)
  await expect(manuscript.getByTestId('protagonist-current-want')).toContainText('拿到城门钥匙')
  await manuscript.getByRole('link', { name: '去人物页 →', exact: true }).click()
  await manuscript.locator('#character-hero').click()
  const sheet = page.getByRole('dialog')
  const want = sheet.getByText('拿到城门钥匙', { exact: true })
  await want.click()
  await sheet.getByRole('textbox', { name: '编辑文字' }).fill('守住城门等待妹妹')
  await sheet.getByRole('textbox', { name: '编辑文字' }).press('Control+Enter')
  await expect.poll(() => character.want).toBe('守住城门等待妹妹')
  await page.goto(`${base}/books/settings-boundary/protagonist`)
  await expect(manuscript.getByTestId('protagonist-current-want')).toContainText('守住城门等待妹妹')
  character.want = ' '
  await page.reload()
  await expect(manuscript.getByTestId('protagonist-current-want')).toHaveCount(0)
  results.push('人物页编辑同一 want 字段，主角页读取新值，空值不显示')

  const css = await readFile(new URL('../src/components/setupQuestions.css', import.meta.url), 'utf8')
  const labels = ['书名', '全书篇幅（万字）', '第 1 章的切入场面', '前 3 章被什么压着', '这是一个超过九个字的字段名称']
  await page.setContent(`<style>${css} .container{container:manuscript/inline-size;width:700px} dt{font-size:12px;line-height:18px;display:flex;flex-wrap:wrap} dd{font-size:15px;margin:0} dl{margin:0}</style><div class="container"><dl class="setup-facts">${labels.map(label => `<div class="setup-fact-row"><dt><span>${label}</span></dt><dd>测试内容</dd></div>`).join('')}</dl><dl class="setup-facts" data-short>${['书名', '读者定位'].map(label => `<div class="setup-fact-row"><dt><span>${label}</span></dt><dd>另一张短表</dd></div>`).join('')}</dl></div>`)
  const measurements = await page.locator('.setup-facts').first().locator('dt').evaluateAll(rows => rows.map(row => ({ width: row.getBoundingClientRect().width, height: row.getBoundingClientRect().height })))
  assert.ok(measurements.every(row => row.width === 108))
  assert.ok(measurements.slice(0, 4).every(row => row.height === 18))
  assert.equal(measurements.at(-1).height, 36)
  assert.deepEqual(await page.locator('[data-short] dt').evaluateAll(rows => rows.map(row => row.getBoundingClientRect().width)), [48, 48])
  await page.locator('.container').evaluate(element => { element.style.width = '390px' })
  const stacked = await page.locator('.setup-fact-row').first().evaluate(row => { const [label, value] = [...row.children].map(child => child.getBoundingClientRect()); return label.x === value.x && value.y > label.y })
  assert.equal(stacked, true)
  results.push('真实 Chromium 测量：按本表最长名称独立取48px/108px，三种回归名称单行，超9em折行，390px仍上下排')

  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  await mkdir(resolve('../data/second-package-task5'), { recursive: true })
  await writeFile(output, JSON.stringify({ results, errors, unexpected, writes }, null, 2))
  console.log(JSON.stringify({ passed: results.length, results, output }, null, 2))
} finally { await browser.close() }
