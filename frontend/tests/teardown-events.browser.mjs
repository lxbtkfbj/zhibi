/** 真 BookDesk/useMeeting 的 SSE 与控制回归：独立无代理 Vite，所有 API 和 EventSource 为夹具。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const root = fileURLToPath(new URL('../../', import.meta.url))
const port = Number(process.env.TEARDOWN_EVENTS_TEST_PORT || 4453)
assert.ok(port > 1024 && ![8000, 4320].includes(port), '只使用独立端口')
const base = `http://127.0.0.1:${port}`
const output = path.join(root, 'data/teardown-events-ui')
await fs.mkdir(output, { recursive: true })
const evidence = { base, checks: [], pageErrors: [], unexpectedRequests: [], calls: [], realModelCalls: 0 }
const bookId = 'teardown-events-fixture'
const makeJob = (id = 'job-1', status = 'running', doing = 'read') => ({ id, book_id: bookId, kind: 'teardown', status, pending: { teardown: { doing, reading: [9, 12], read: 8, target: 20, total: 40, eta_seconds: 120, range: [1, 20], failed: [] } }, params: { upto: 20 }, updated_at: '2026-10-20T01:00:00Z', created_at: '2026-10-20T01:00:00Z' })
let currentJob = makeJob()
const book = { id: bookId, title: '事件刷新合成书', source: 'teardown', status: 'writing', genre: '', concept: {}, spine: {}, requirements: [], style_reference: '', trial_read_done: false, chapters_final: 40, words_final: 8000, active_job: currentJob,
  teardown: { stage: 'running', chapters: 40, chars: 8000, author: '验收', intro: '', volumes: 1, original_volumes: true, open_volume_id: null, upto: 20, stop_note: null, imported_at: '2026-10-20T01:00:00Z' } }
let chapters = Array.from({ length: 40 }, (_, index) => ({ id: `chapter-${index + 1}`, index: index + 1, title: `合成第${index + 1}回`, status: 'final', word_count: 200, outline: { goal: `第${index + 1}章发生的事`, scenes: [], cool_point: '', hook: '' }, summary: '', teardown: { read: index < 8, failed: index === 6 } }))
const tree = () => ({ segmented: false, ending: null, arcs: [{ node_id: null, planned: true, volumes: [{ id: 'v1', index: 1, title: '小城', status: 'done', summary: '小城里发生的事', chapter_count: 40, units: [{ id: 'u1', index: 1, title: '旧事来信', status: 'done', summary: '一封信来了', chapter_count: 40, chapters }] }] }] })
let starts = 0
let rejectStart = false
let startResponseMode = 'normal'
let page
const server = await createServer({ configFile: false, root: path.join(root, 'frontend'), cacheDir: path.join(output, 'vite-cache'), plugins: [react(), tailwindcss(), { name: 'deny-real-api', configureServer(vite) { vite.middlewares.use((req, res, next) => { if (req.url?.startsWith('/api/')) { res.statusCode = 503; res.end('Real API forbidden'); return } next() }) } }], server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, open: false, hmr: false, watch: null } })
let browser
const check = (name, details = {}) => { evidence.checks.push({ name, ...details }); console.log(`PASS ${name}`) }
const pause = () => page.waitForTimeout(450)
const emit = (type, data) => page.evaluate(({ type, data }) => window.emitFixture(type, data), { type, data })
const summary = calls => Object.fromEntries(['book', 'library', 'bible', 'outline-tree', 'chapters'].map(key => [key, calls.filter(call => call.method === 'GET' && call.path === `/api/books/${bookId}${key === 'book' ? '' : `/${key}`}`).length]))
try {
  await server.listen()
  browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
  const context = await browser.newContext({ viewport: { width: 1500, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
  await context.addInitScript(() => {
    const clients = []
    class FakeEventSource extends EventTarget {
      constructor(url) { super(); this.url = url; this.readyState = 0; clients.push(this); queueMicrotask(() => { if (this.readyState !== 2) { this.readyState = 1; this.dispatchEvent(new Event('open')) } }) }
      close() { this.readyState = 2 }
    }
    window.EventSource = FakeEventSource
    window.emitFixture = (type, data) => clients.filter(client => client.readyState === 1).forEach(client => client.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) })))
  })
  await context.route(url => url.pathname.startsWith('/api/'), async route => {
    const req = route.request(), url = new URL(req.url()), pathname = url.pathname
    evidence.calls.push({ method: req.method(), path: pathname, query: url.search })
    if (pathname === `/api/teardown/${bookId}/start`) {
      starts += 1
      if (rejectStart) return route.fulfill({ status: 409, json: { detail: '正在拆，点「停下」才能改' } })
      const queued = makeJob(`job-${starts + 1}`, 'queued', 'queued')
      currentJob = queued; book.active_job = queued; book.teardown.stage = 'queued'
      if (startResponseMode !== 'normal') {
        currentJob = makeJob(queued.id, startResponseMode === 'running' ? 'running' : 'succeeded', 'units')
        book.active_job = startResponseMode === 'running' ? currentJob : null
        book.teardown.stage = startResponseMode === 'running' ? 'running' : 'done'
        book.teardown.upto = startResponseMode === 'running' ? 20 : null
        await emit('job', currentJob)
        await new Promise(resolve => setTimeout(resolve, 650))
      }
      return route.fulfill({ json: queued })
    }
    if (pathname === `/api/teardown/${bookId}/stop`) return route.fulfill({ json: currentJob })
    if (req.method() === 'GET') {
      if (pathname === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
      if (pathname === '/api/books') return route.fulfill({ json: [book] })
      if (pathname === '/api/llm/profiles') return route.fulfill({ json: [{ id: 'demo', name: '演示模型', provider: 'demo', has_key: false }] })
      if (pathname === '/api/llm/roles') return route.fulfill({ json: { default: 'demo', teardown: null } })
      if (pathname.startsWith(`/api/books/${bookId}`)) {
        const suffix = pathname.slice(`/api/books/${bookId}`.length)
        const values = { '': book, '/outline-tree': tree(), '/outline': { book_id: bookId, volumes: [] }, '/chapters': chapters,
          '/library': { characters: [], entries: [], categories: [], suggestions_pending: 0 }, '/bible': { relationships: [] }, '/requirements': [], '/threads': [], '/saves': { items: [], more: false }, '/suggestions': [], '/suggestion-changes': {},
          '/settings': { settings: { max_rewrites: 2, trial_read: false, volume_approval: false, chapters_approval: false, segment_approval: false } }, '/chat/conversations': [], '/usage': { calls: 0, input_tokens: 0, output_tokens: 0 },
        }
        if (Object.hasOwn(values, suffix)) return route.fulfill({ json: values[suffix] })
        const one = /^\/chapters\/(\d+)$/.exec(suffix)
        if (one) return route.fulfill({ json: { ...chapters[Number(one[1]) - 1], content: '合成原文，不连接日常书库。', teardown: {} } })
      }
    }
    evidence.unexpectedRequests.push(`${req.method()} ${pathname}`)
    return route.fulfill({ status: 500, json: { detail: 'Unexpected API denied' } })
  })
  page = await context.newPage()
  page.on('pageerror', error => evidence.pageErrors.push(error.message))
  await page.goto(`${base}/desk/${bookId}`)
  const strip = page.getByTestId('teardown-progress-strip')
  await expect(strip).toContainText('设定师在读第 9–12 章')
  await pause()
  let since = evidence.calls.length
  for (let read = 9; read <= 12; read++) { currentJob = makeJob(); currentJob.pending.teardown.read = read; await emit('job', currentJob) }
  await emit('message', { id: 1, book_id: bookId, job_id: currentJob.id, speaker: 'chief', speaker_name: '主编', kind: 'speech', content: '这只是拆书聊天', payload: {}, created_at: '2026-10-20T01:00:00Z' })
  await emit('message_update', { id: 1, book_id: bookId, speaker: 'chief', speaker_name: '主编', kind: 'speech', content: '群聊更新不动书', payload: {}, created_at: '2026-10-20T01:00:00Z' })
  await pause()
  const progressCalls = summary(evidence.calls.slice(since))
  assert.deepEqual(progressCalls, { book: 0, library: 0, bible: 0, 'outline-tree': 0, chapters: 0 })
  check('连续进度及群聊message/message_update不重拉整书或目录', progressCalls)
  since = evidence.calls.length
  chapters = chapters.map(chapter => ({ ...chapter, teardown: { ...chapter.teardown, read: chapter.index <= 12 } }))
  await emit('teardown_saved', { read: 12 })
  await pause()
  const savedCalls = summary(evidence.calls.slice(since))
  assert.deepEqual(savedCalls, { book: 0, library: 0, bible: 0, 'outline-tree': 1, chapters: 1 })
  check('书变了只读取大纲树与带纲目录', savedCalls)
  await strip.getByRole('button', { name: '停下', exact: true }).click()
  await pause()
  await expect(strip.getByRole('button', { name: '正在停：读完手上这几章就停', exact: true })).toBeDisabled()
  check('stop HTTP返回running后仍禁用，等待SSE终态')
  since = evidence.calls.length
  currentJob = { ...currentJob, status: 'cancelled' }; book.active_job = null; book.teardown.stage = 'stopped'; book.teardown.stop_note = '你点了停下，停在第 12 章。'
  await emit('job', currentJob)
  await expect(strip.getByRole('button', { name: '接着拆', exact: true })).toBeVisible()
  await pause()
  const endedCalls = summary(evidence.calls.slice(since))
  assert.deepEqual(endedCalls, { book: 1, library: 1, bible: 1, 'outline-tree': 1, chapters: 1 })
  since = evidence.calls.length
  await emit('job', currentJob); await emit('job', currentJob); await pause()
  assert.deepEqual(summary(evidence.calls.slice(since)), { book: 0, library: 0, bible: 0, 'outline-tree': 0, chapters: 0 })
  check('终态整书五接口只一次且book去重，重复终态不重拉', endedCalls)
  await strip.getByRole('button', { name: '接着拆', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '开始拆《事件刷新合成书》', exact: true })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('spinbutton', { name: '拆到第几章', exact: true })).toHaveValue('20')
  const bounds = await dialog.boundingBox()
  assert.ok(bounds && Math.abs(bounds.x + bounds.width / 2 - 750) < 5 && Math.abs(bounds.y + bounds.height / 2 - 550) < 20)
  await dialog.getByRole('button', { name: '先不拆', exact: true }).click()
  assert.equal(starts, 0)
  await strip.getByRole('button', { name: '接着拆', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  assert.equal(starts, 0)
  await strip.getByRole('button', { name: '接着拆', exact: true }).click()
  rejectStart = true
  await dialog.getByRole('button', { name: '开始拆', exact: true }).click()
  await expect(dialog).toContainText('正在拆，点「停下」才能改')
  await expect(dialog).toBeVisible()
  check('继续窗居中、保留上次目标，取消/Esc不发请求，后台409原样展示')
  rejectStart = false; startResponseMode = 'running'
  await dialog.getByRole('button', { name: '开始拆', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(strip).toContainText('主编在归单元')
  check('开始HTTP旧queued回包不覆盖先到的running进度')
  currentJob = { ...currentJob, status: 'cancelled' }; book.active_job = null; book.teardown.stage = 'stopped'
  await emit('job', currentJob); await pause()
  await strip.getByRole('button', { name: '接着拆', exact: true }).click()
  startResponseMode = 'done'
  await dialog.getByRole('button', { name: '开始拆', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(strip).toContainText('拆完了')
  check('开始HTTP旧queued回包不覆盖先到的terminal和终态整书刷新')
  assert.deepEqual(evidence.pageErrors, [])
  assert.deepEqual(evidence.unexpectedRequests, [])
} finally {
  await browser?.close()
  await server.close()
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
}
console.log(JSON.stringify({ checks: evidence.checks.length, pageErrors: evidence.pageErrors.length, unexpectedRequests: evidence.unexpectedRequests.length }))
