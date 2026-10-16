import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

// 全 API 在浏览器拦截：不读取或改动任何真实书、任务、服务状态。
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const base = process.env.PREVIEW_BASE ?? 'http://127.0.0.1:4345'
const executablePath = process.env.CHROMIUM_PATH ?? 'C:/Users/cxc/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
const bookId = 'task3-restart-mock'
const timestamp = '2026-10-16T09:00:00Z'
const oldJob = { id: 'task3-old-flow', book_id: bookId, kind: 'book_setup', setup_flow: 1, status: 'waiting_author', pending: { kind: 'setup_review', flow: 1, round: 1 }, error: '', created_at: timestamp, updated_at: timestamp, finished_at: null }
const newJob = { ...oldJob, id: 'task3-new-flow', setup_flow: 2, pending: { kind: 'setup_piece', flow: 2, piece: 'protagonist', round: 1, flags: {}, warnings: ['程序提醒：开局动机需再看看'], decisions: [], review: [{ question: 'interlock', problem: '三件套联系还不够清楚', suggestion: '补一句金手指如何推动追求' }], suggestions: [{ target: 'concept', problem: '核心循环可更具体', suggestion: '解锁定调后补充反复行动' }], unlock_requests: [{ target: 'world', reason: '需要核对世界中的对手安排' }] } }
const concept = { title: '重开边界模拟书', genre: '玄幻', tags: ['全模拟验收'], target_reader: '喜欢智斗的读者', logline: '保留作者要求，按新五步开书', core_loop: '收集线索并识破对手', selling_points: ['用信息差反击'], tone: '清楚利落', target_length: 100, target_volumes: 3, chapter_words: 3000, stage_ladder: '镇子 → 京城' }
let book = { id: bookId, title: concept.title, source: 'new', genre: concept.genre, status: 'setting_up', idea: '只在浏览器模拟的旧流程书', logline: concept.logline, job_status: 'waiting_author', created_at: timestamp, updated_at: timestamp, style_reference: '', concept, protagonist: {}, world: {}, spine: {}, setup_progress: { mode: 'puzzle', current: 'concept', pieces: { concept: 'confirmed' } }, requirements: [], trial_read_done: false, active_job: oldJob, chapters_final: 0, words_final: 0 }
const emptyBible = { characters: [], relationships: [], world_entries: [], foreshadowings: [], secrets: [] }
const settings = { setup_mode: 'puzzle', person: 'third', chapter_words: 3000, title_style: 'short', title_custom: '', intimacy: 'heart', intimacy_custom: '', other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 2, review_strictness: 'standard', volume_audit: true, volume_approval: true, segment_approval: true, trial_read: true }
const browser = await chromium.launch({ headless: true, executablePath })
const page = await browser.newPage({ viewport: { width: 1560, height: 1080 }, reducedMotion: 'reduce' })
const errors = []
const writes = []
const screenshots = []
const unexpected = []
let restartAttempts = 0
let releaseRestart
const pendingRestart = new Promise(resolve => { releaseRestart = resolve })
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', async route => {
  const request = route.request()
  const pathname = new URL(request.url()).pathname
  if (!pathname.startsWith('/api/')) return route.continue()
  const method = request.method()
  if (method !== 'GET') writes.push({ method, path: pathname, body: request.postDataJSON() })
  if (pathname === `/api/jobs/${oldJob.id}/restart-setup` && method === 'POST') {
    restartAttempts += 1
    if (restartAttempts === 1) return route.fulfill({ status: 503, json: { detail: '模拟重开失败，作者原文已保留，请重试' } })
    await pendingRestart
    book = { ...book, active_job: newJob, protagonist: { name: '陆远', pursuit: '找到失踪亲人' }, setup_progress: { mode: 'puzzle', current: 'protagonist', pieces: { concept: 'confirmed', protagonist: 'waiting', world: 'todo', segment: 'todo', first_volume: 'todo' } } }
    return route.fulfill({ json: newJob })
  }
  if (pathname === `/api/books/${bookId}/notes` && method === 'POST') {
    const body = request.postDataJSON()
    return route.fulfill({ json: { id: 1, book_id: bookId, job_id: oldJob.id, speaker: 'author', speaker_name: '作者', kind: 'note', content: body.content, payload: { thread: body.to, requirement_saved: true }, created_at: timestamp } })
  }
  if (pathname === `/api/jobs/${newJob.id}/piece` && method === 'POST') return route.fulfill({ json: newJob })
  if (method !== 'GET') {
    unexpected.push(`${method} ${pathname}`)
    return route.fulfill({ status: 409, json: { detail: '模拟验收禁止此写请求' } })
  }
  if (pathname === `/api/books/${bookId}`) return route.fulfill({ json: book })
  if (pathname === `/api/books/${bookId}/events`) return route.fulfill({ contentType: 'text/event-stream', body: 'retry: 600000\n: isolated mock\n\n' })
  if (pathname === `/api/books/${bookId}/outline`) return route.fulfill({ json: { concept, volumes: [] } })
  if (pathname === `/api/books/${bookId}/bible`) return route.fulfill({ json: emptyBible })
  if (pathname === `/api/books/${bookId}/settings` || pathname === '/api/settings/new-book-defaults') return route.fulfill({ json: { settings, rules_text: '' } })
  if (/\/(nodes|threads|chapters|secrets|requirements|profiles)$/.test(pathname)) return route.fulfill({ json: [] })
  if (pathname === '/api/books') return route.fulfill({ json: [book] })
  if (pathname === '/api/llm/roles') return route.fulfill({ json: { default: null, chief: null, lorekeeper: null, writer: null, reviewer: null } })
  if (pathname === '/api/glossary') return route.fulfill({ json: { terms: [] } })
  if (pathname.endsWith('/usage')) return route.fulfill({ json: { calls: 0, prompt_tokens: null, completion_tokens: null, by_role: {} } })
  unexpected.push(`${method} ${pathname}`)
  return route.fulfill({ json: {} })
})

const shot = async name => {
  const filename = `docs/第二包验收/任务3-重开边界-${name}.png`
  await page.screenshot({ path: path.join(root, filename) })
  screenshots.push(filename)
}
const cardButtons = () => page.getByRole('button', { name: '按新流程重开', exact: true })
const sidebar = page.getByTestId('full-sidebar')
const conversation = page.getByTestId('conversation-pane')
const groupDraft = '保留这段群聊原稿：主角叫陆远，重开后再处理。'

try {
  await page.goto(`${base}/books/${bookId}`, { waitUntil: 'networkidle' })
  await expect(cardButtons()).toHaveCount(2)
  await expect(page.getByTestId('restart-setup-overview')).toBeVisible()
  await expect(page.getByTestId('restart-setup-bar')).toBeVisible()
  const group = conversation.getByRole('textbox', { name: '给编辑部发消息', exact: true })
  await expect(group).toHaveAttribute('placeholder', '这本书要先按新流程重开，重开后再提意见')
  await group.fill(groupDraft)
  await expect(conversation.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  await group.press('Enter')
  await conversation.getByRole('button', { name: '发送', exact: true }).evaluate(button => button.click())
  await expect(group).toHaveValue(groupDraft)
  assert.deepEqual(writes, [], '旧群聊 Enter 和禁用按钮均不发请求')
  await shot('旧群聊禁用双入口')

  await sidebar.locator('[data-conversation="chief"]').click()
  const direct = conversation.getByRole('textbox', { name: '发消息给主编', exact: true })
  await direct.fill('只记下这条私聊要求，不续跑旧图。')
  await conversation.getByRole('button', { name: '发送', exact: true }).click()
  await expect(direct).toHaveValue('')
  assert.deepEqual(writes, [{ method: 'POST', path: `/api/books/${bookId}/notes`, body: { content: '只记下这条私聊要求，不续跑旧图。', to: 'chief' } }])
  await expect(conversation.getByText('已记下，下次开工会按你的要求来。', { exact: true })).toBeVisible()
  await shot('私聊仍走插话')
  await sidebar.locator('[data-conversation="group"]').click()
  await expect(group).toHaveValue(groupDraft)

  await page.getByTestId('restart-setup-overview').getByRole('button', { name: '按新流程重开', exact: true }).click()
  await expect(page.getByTestId('restart-setup-overview').getByText('模拟重开失败，作者原文已保留，请重试', { exact: true })).toBeVisible()
  await expect(cardButtons()).toHaveCount(2)
  await expect(cardButtons().nth(0)).toBeEnabled()
  await expect(cardButtons().nth(1)).toBeEnabled()
  await expect(group).toHaveValue(groupDraft)
  await shot('失败保留重试')

  await page.getByTestId('restart-setup-bar').getByRole('button', { name: '按新流程重开', exact: true }).click()
  await expect(cardButtons().nth(0)).toBeDisabled()
  await expect(cardButtons().nth(1)).toBeDisabled()
  await expect(cardButtons().nth(0).locator('.animate-spin')).toHaveCount(1)
  await expect(cardButtons().nth(1).locator('.animate-spin')).toHaveCount(1)
  assert.equal(restartAttempts, 2)
  await shot('两处同步加载禁用')
  // 在请求未结束时手动离开概览，检查成功回调确实导航回概览。
  await sidebar.getByRole('link', { name: '书的概念', exact: true }).click()
  await expect(page).toHaveURL(`${base}/books/${bookId}/concept`)
  releaseRestart()
  await expect(page).toHaveURL(`${base}/books/${bookId}`)
  await expect(cardButtons()).toHaveCount(0)
  const tracker = page.getByTestId('puzzle-tracker')
  await expect(tracker.getByRole('button', { name: '定调', exact: true })).toBeVisible()
  for (const name of ['主角', '世界与人', '第一段', '第一卷']) await expect(tracker.getByRole('button', { name, exact: true })).toBeVisible()
  await expect(tracker.locator('button[aria-current="step"]')).toHaveText('主角')
  await expect(conversation.getByRole('textbox', { name: '修改意见', exact: true })).toHaveValue(groupDraft)
  await shot('成功回概览新五步')

  const decision = page.getByTestId('decision-bar')
  await decision.locator('summary').click()
  const reminderItems = decision.locator('details > ul > li')
  await expect(reminderItems).toHaveCount(4)
  await expect(reminderItems.nth(0)).toContainText('程序提醒：开局动机需再看看')
  await expect(reminderItems.nth(1)).toHaveText('审稿：三件套联系还不够清楚——补一句金手指如何推动追求')
  await expect(reminderItems.nth(1).getByRole('button')).toHaveCount(0)
  await expect(reminderItems.nth(2)).toContainText('审稿建议')
  await expect(reminderItems.nth(2).getByRole('button', { name: '解锁并修改', exact: true })).toBeVisible()
  await expect(reminderItems.nth(3)).toContainText('解锁请求')
  await expect(reminderItems.nth(3).getByRole('button', { name: '解锁并修改', exact: true })).toBeVisible()
  await shot('审稿只读与提醒顺序')

  await conversation.getByRole('button', { name: '发送', exact: true }).click()
  await expect(conversation.getByRole('textbox', { name: '修改意见', exact: true })).toHaveValue('')
  assert.deepEqual(writes.at(-1), { method: 'POST', path: `/api/jobs/${newJob.id}/piece`, body: { action: 'revise', piece: 'protagonist', feedback: groupDraft } })
  assert.equal(writes.filter(item => item.path.endsWith('/notes')).length, 1)
  assert.equal(writes.filter(item => item.path.endsWith('/piece')).length, 1)
  assert.equal(writes.filter(item => item.path.endsWith('/restart-setup')).length, 2)
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  await shot('新流程意见走当前块')
  const result = { passed: true, mode: '全 API 浏览器模拟；未访问真实 API，未创建或修改真实书和任务', preview: base, bookId, checks: ['概览下一步与稿件顶部均有重开说明卡', '旧 flow 群聊 Enter/禁用按钮均不发请求', '旧 flow 点名私聊只走 notes，切回群聊原草稿保留', '503 失败保留双卡、错误、重试与群聊草稿', '重开进行中双入口均加载且禁用', '异页等待重开成功后返回概览并显示新五块', '拍板条顺序为提醒/只读审稿/审稿建议/解锁请求，审稿无按钮，后两项保留解锁并修改', '新 flow 群聊原稿发送走当前 protagonist piece revise'], writes, screenshots, runtimeErrors: errors, unexpectedApiRequests: unexpected }
  await fs.mkdir(path.join(root, 'data/second-package-task3'), { recursive: true })
  await fs.writeFile(path.join(root, 'data/second-package-task3/restart-boundaries.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
} catch (cause) {
  console.error(JSON.stringify({ url: page.url(), errors, unexpected, body: (await page.locator('body').innerText()).slice(0, 2500) }, null, 2))
  throw cause
} finally {
  releaseRestart()
  await browser.close()
}
