/** 旧后台 read 汇总缺字段回归：仅独立前端、内存 GET 夹具，不访问日常服务、书库或模型。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const root = fileURLToPath(new URL('../../', import.meta.url))
const port = Number(process.env.SMALLFIX_SHELF_COMPAT_PORT || 4393)
assert.ok(Number.isInteger(port) && port > 1024 && ![8000, 4320].includes(port))
const base = `http://127.0.0.1:${port}`
const output = path.join(root, 'data/smallfix-shelf-compat')
await fs.mkdir(output, { recursive: true })
const report = { isolation: 'Private Vite without proxy; in-memory GET fixtures; no live API, DB or models.', checks: [], requests: [], pageErrors: [], unexpectedRequests: [] }
const book = (id, read, stage = 'stopped', source = 'teardown') => ({ id, title: id, source, status: 'ready', genre: '', idea: '', logline: '', created_at: '', updated_at: '', job_status: null, teardown: { stage, chapters: 3, author: '', chars: 30, upto: 3, read, stop_reason: 'upto' } })
const books = [book('old-with-holes'), book('old-failed'), book('new-zero', 0), book('new-two', 2), book('old-done', undefined, 'done'), book('author-book', undefined, 'stopped', 'new')]
const chapters = [{ teardown: { read: true, failed: false } }, { teardown: { read: false, failed: true } }, { teardown: { read: true, failed: false } }]
let release
const ready = new Promise(resolve => { release = resolve })
const check = name => { report.checks.push(name); console.log(`PASS ${name}`) }
const server = await createServer({ configFile: false, root: path.join(root, 'frontend'), cacheDir: path.join(output, 'vite-cache'), plugins: [react(), tailwindcss(), { name: 'deny-live-api', configureServer(vite) { vite.middlewares.use((req, res, next) => { if (req.url?.startsWith('/api/')) { res.statusCode = 503; return res.end('Real API forbidden') } next() }) } }], server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, open: false, hmr: false, watch: null } })
let browser, page
try {
  await server.listen()
  browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined })
  const context = await browser.newContext({ viewport: { width: 1500, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.origin !== base) { report.unexpectedRequests.push(req.url()); return route.abort('blockedbyclient') }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const p = url.pathname.slice(4)
    report.requests.push({ method: req.method(), path: p })
    if (req.method() !== 'GET') { report.unexpectedRequests.push(`${req.method()} ${p}`); return route.abort() }
    if (p === '/books') return route.fulfill({ json: books })
    if (p === '/llm/profiles') return route.fulfill({ json: [] })
    if (p === '/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    if (p === '/books/old-with-holes/chapters') { await ready; return route.fulfill({ json: chapters }) }
    if (p === '/books/old-failed/chapters') return route.fulfill({ status: 503, json: { detail: '隔离夹具失败' } })
    report.unexpectedRequests.push(p)
    return route.fulfill({ status: 503, json: { detail: 'Unmocked API denied' } })
  })
  page = await context.newPage()
  page.on('pageerror', error => report.pageErrors.push(error.message))
  const status = id => page.locator(`a[href="/desk/${id}"] p.text-ink-2`)
  await page.goto(base)
  await expect(status('old-with-holes')).toHaveText('已拆 — / 3 章')
  check('旧后台缺 read 时等待目录，不把未知当 0')
  release()
  await expect(status('old-with-holes')).toHaveText('已拆 2 / 3 章')
  check('目录含读失败空洞时按 read 标记计 2 章，不拿 upto=3 代替')
  await expect(status('old-failed')).toHaveText('已拆 — / 3 章')
  await expect.poll(() => report.requests.filter(request => request.path === '/books/old-failed/chapters').length).toBe(2)
  await expect(status('old-failed')).toHaveText('已拆 — / 3 章')
  check('目录请求失败并重试后仍不显示假 0')
  await expect(status('new-zero')).toHaveText('已拆 0 / 3 章')
  await expect(status('new-two')).toHaveText('已拆 2 / 3 章')
  await expect(status('old-done')).toHaveText('拆完了 · 3 章')
  assert.deepEqual(report.requests.filter(request => /\/chapters$/.test(request.path)).map(request => request.path).sort(), ['/books/old-failed/chapters', '/books/old-failed/chapters', '/books/old-with-holes/chapters'])
  check('正常汇总 read 包含 0 不补请求，完成和作者自己的书也不请求目录')
  assert.deepEqual(report.pageErrors, [])
  assert.deepEqual(report.unexpectedRequests, [])
  check('零页面异常、零意外/外部请求、零写请求')
  report.ok = true
} catch (error) {
  report.ok = false
  report.error = error.stack || String(error)
  throw error
} finally {
  release()
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n')
  await browser?.close()
  await server.close()
}
