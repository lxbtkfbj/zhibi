/** 真书房/BookDesk 导航回归：独立 Vite、隔离缓存、全部 API 内存夹具；不访问日常服务/书库/模型。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const root = fileURLToPath(new URL('../../', import.meta.url))
const port = Number(process.env.TEARDOWN_INTRO_TEST_PORT || 4392)
assert.ok(Number.isInteger(port) && port > 1024 && ![8000, 4320].includes(port), '必须使用独立端口')
const base = `http://127.0.0.1:${port}`
const output = path.join(root, 'data/teardown-intro-ui')
await fs.mkdir(output, { recursive: true })
const sources = ['frontend/src/pages/Home.tsx', 'frontend/src/pages/workspace/Workspace.tsx', 'frontend/src/lib/workspaceReadingPosition.ts']
const fingerprint = async () => Object.fromEntries(await Promise.all(sources.map(async file => [file, createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex')])))
const evidence = { base, startedAt: new Date().toISOString(), sourceSha256: await fingerprint(), isolation: 'Real main/router/Home/BookDesk; private Vite without proxy; browser rejects external origins; only mocked GET APIs; fake SSE; no DB or model.', checks: [], screenshots: [], requests: [], unexpectedRequests: [], externalRequests: [], pageErrors: [] }
const check = (name, details = {}) => { evidence.checks.push({ name, ...details }); console.log(`PASS ${name}`) }
const bookId = 'teardown-intro-fixture', authorId = 'author-intro-fixture', confirmingId = 'confirming-intro-fixture'
const makeBook = (id, title, source) => ({ id, title, source, status: 'ready', genre: '悬疑', idea: '隔离导航回归，不使用真实书库。', logline: '书房入口与当前阅读位置各自保留。', concept: { title, story: '合成的简介。', genre: '悬疑', channel: '男频', tags: [] }, spine: {}, requirements: [], style_reference: '', protagonist: {}, world: {}, setup_progress: {}, trial_read_done: true, chapters_final: 3, words_final: 600, chapter_words: 2500, card_layouts: {}, active_job: null, job_status: null, created_at: '2026-10-20T01:00:00Z', updated_at: '2026-10-20T02:00:00Z' })
const book = { ...makeBook(bookId, '书架导航合成书', 'teardown'), teardown: { stage: 'done', chapters: 3, chars: 600, author: '隔离验收', intro: '', volumes: 1, original_volumes: true, open_volume_id: null, upto: null, read: 3, stop_note: null, imported_at: '2026-10-20T01:00:00Z' } }
const authorBook = makeBook(authorId, '作者导航合成书', 'new')
const confirmingBook = { ...book, id: confirmingId, title: '待确认合成书', teardown: { ...book.teardown, stage: 'confirming', read: 0 } }
const books = [authorBook, book, confirmingBook]
const chapters = Array.from({ length: 3 }, (_, i) => ({ id: `chapter-${i + 1}`, index: i + 1, title: ['晨雾', '来信', '归途'][i], status: 'final', word_count: 200, outline: { goal: `第 ${i + 1} 章发生的事`, scenes: [], cool_point: '', hook: '' }, summary: '', teardown: { read: true, failed: false } }))
const tree = { segmented: false, ending: null, arcs: [{ node_id: null, planned: true, volumes: [{ id: 'v1', index: 1, title: '旧港', status: 'done', summary: '一座合成的港口。', chapter_count: 3, units: [{ id: 'u1', index: 1, title: '来信', status: 'done', summary: '合成的单元。', chapter_count: 3, chapters }] }] }] }
const settings = { settings: { setup_mode: 'puzzle', max_rewrites: 2, trial_read: false, volume_approval: false, chapters_approval: false, segment_approval: false }, rules_text: '' }
const server = await createServer({
  configFile: false, root: path.join(root, 'frontend'), cacheDir: path.join(output, 'vite-cache'),
  plugins: [react(), tailwindcss(), { name: 'deny-live-api', configureServer(vite) {
    vite.middlewares.use((req, res, next) => { if (req.url?.startsWith('/api/')) { res.statusCode = 503; res.end('Real API forbidden'); return } next() })
  } }],
  server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, open: false, hmr: false, watch: null },
})
let browser, page
const tab = name => page.locator('header.top nav.tabs a').filter({ hasText: new RegExp(`^${name}$`) })
const selectedTab = async name => { await expect(tab(name)).toHaveClass(/\bon\b/) }
const entryConsumed = async () => expect.poll(() => page.evaluate(() => !!(history.state?.usr?.teardownIntro || history.state?.usr?.teardownHome))).toBe(false)
const screenshot = async name => { await page.evaluate(() => document.fonts.ready); await page.screenshot({ path: path.join(output, name), fullPage: true }); evidence.screenshots.push(path.join(output, name)) }
const shelf = () => page.locator('section[aria-label="拆的书"]').locator(`a[href="/desk/${bookId}"]`)
const returnToShelf = async () => { await page.locator('header.top a.back').click(); await expect(shelf()).toBeVisible() }
try {
  await server.listen()
  console.log(`ISOLATED_REAL_APP ${base}`)
  browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined })
  const context = await browser.newContext({ viewport: { width: 1500, height: 1100 }, locale: 'zh-CN', timezoneId: 'Asia/Taipei', reducedMotion: 'reduce', serviceWorkers: 'block' })
  await context.addInitScript(({ bookId, authorId }) => {
    class FixtureEventSource extends EventTarget {
      constructor(url) { super(); this.url = url; this.readyState = 0; queueMicrotask(() => { if (this.readyState !== 2) { this.readyState = 1; this.dispatchEvent(new Event('open')) } }) }
      close() { this.readyState = 2 }
    }
    window.EventSource = FixtureEventSource
    if (sessionStorage.getItem('teardown-intro-fixture-seeded')) return
    sessionStorage.setItem('teardown-intro-fixture-seeded', 'yes')
    sessionStorage.setItem(`zhibi:workspace-reading:${bookId}`, JSON.stringify({ tab: '正文', entry: 'overview', node: 'book', chapter: 'c3', open: ['book', 'v1', 'u1'] }))
    sessionStorage.setItem(`zhibi:workspace-reading:${authorId}`, JSON.stringify({ tab: '大纲', entry: 'overview', node: 'book', chapter: 'home', open: ['book', 'v1', 'u1'] }))
    localStorage.setItem(`zhibi:teardown-reading:${bookId}`, JSON.stringify({ chapter: 2, at: 1792458000000 }))
  }, { bookId, authorId })
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== base) { evidence.externalRequests.push(request.url()); return route.abort('blockedbyclient') }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const p = url.pathname.slice(4), method = request.method()
    evidence.requests.push({ method, path: p + url.search })
    const reply = body => route.fulfill({ json: body })
    if (method === 'GET') {
      if (p === '/books') return reply(books)
      if (p === '/llm/profiles') return reply([])
      if (p === '/llm/roles') return reply({ default: null, chief: null, lorekeeper: null, writer: null, reviewer: null, router: null, teardown: null })
      if (p === '/health') return reply({ status: 'ok', components: {} })
      if (p === '/glossary') return reply({ terms: [] })
      if (p === '/prompts') return reply([])
      if (p === '/book-meta') return reply({ channels: [{ key: '男频', categories: ['悬疑'], tag_groups: [] }], chapter_words: 2500, max_tags: 5 })
      if (p === '/settings/new-book-defaults') return reply(settings)
      for (const item of [book, authorBook]) {
        const prefix = `/books/${item.id}`
        if (p !== prefix && !p.startsWith(`${prefix}/`)) continue
        const suffix = p.slice(prefix.length)
        const values = { '': item, '/outline-tree': tree, '/outline': { book_id: item.id, volumes: [] }, '/chapters': chapters,
          '/library': { characters: [], entries: [], categories: [], suggestions_pending: 0 }, '/bible': { characters: [], world_entries: [], foreshadowings: [], relationships: [] }, '/requirements': [], '/threads': [], '/saves': { items: [], more: false }, '/suggestions': [], '/suggestion-changes': {}, '/settings': settings, '/chat/conversations': [], '/usage': { calls: 0, input_tokens: 0, output_tokens: 0 },
          '/teardown/digest': { people: [], things: [], waits: [], hero: null, changes: [] },
        }
        if (Object.hasOwn(values, suffix)) return reply(values[suffix])
        const match = /^\/chapters\/(\d+)$/.exec(suffix)
        if (match && chapters[Number(match[1]) - 1]) return reply({ ...chapters[Number(match[1]) - 1], content: `第 ${match[1]} 章的隔离合成原文，不连接日常书库。`, teardown: {} })
      }
    }
    evidence.unexpectedRequests.push(`${method} ${p}`)
    console.log(`UNMOCKED ${method} ${p}`)
    return route.fulfill({ status: 503, json: { detail: 'Unmocked API denied' } })
  })
  page = await context.newPage()
  page.on('pageerror', error => evidence.pageErrors.push(error.message))
  await page.goto(base)
  await shelf().click()
  await selectedTab('简介')
  await expect(page.locator('.intro-top h1')).toHaveText(book.title)
  await entryConsumed()
  assert.equal(await page.evaluate(id => JSON.parse(localStorage.getItem(`zhibi:teardown-reading:${id}`)).chapter, bookId), 2)
  await screenshot('01-shelf-opens-intro.png')
  check('真实书架点击拆的书，覆盖上次正文位置进入简介；入口标记已消费，保留读到第 2 章')

  await tab('正文').click()
  await selectedTab('正文')
  await expect(page.locator('.continue')).toContainText('第 2 章 来信')
  await page.locator('.continue a.btn').filter({ hasText: /^接着读/ }).click()
  await expect(page.locator('.page.reader h1')).toHaveText('第 2 章 来信')
  await expect(page.locator('.reading-prose')).toContainText('第 2 章的隔离合成原文')
  check('切换正文仍显示接着读第 2 章，接着读打开原阅读位置')

  await page.reload()
  await selectedTab('正文')
  await expect(page.locator('.page.reader h1')).toHaveText('第 2 章 来信')
  await expect(page.locator('.reading-prose')).toContainText('第 2 章的隔离合成原文')
  await entryConsumed()
  await screenshot('02-reader-survives-reload.png')
  check('正文第 2 章刷新后仍为该章，不被书架入口标记再次拉回简介')

  await page.getByRole('button', { name: '系统设置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '系统设置', exact: true })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('link', { name: /提示词.*调用记录/ }).click()
  await expect(page.getByRole('heading', { name: '提示词与调用记录', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /返回当前书|返回书页|返回书房|回到书房|回到书页/ }).first().click()
  await selectedTab('正文')
  await expect(page.locator('.page.reader h1')).toHaveText('第 2 章 来信')
  check('从系统设置进入提示词再返回，仍保留正文第 2 章')

  await tab('大纲').click()
  await selectedTab('大纲')
  await returnToShelf()
  await shelf().click()
  await selectedTab('简介')
  await expect(page.locator('.intro-top h1')).toHaveText(book.title)
  await entryConsumed()
  check('从大纲返回书架再点击同一本拆的书，重新进入简介而不是记忆的大纲')

  await returnToShelf()
  const confirmingLink = page.locator('section[aria-label="拆的书"]').locator(`a[href="/teardown/${confirmingId}"]`)
  await expect(confirmingLink).toBeVisible()
  assert.equal(await confirmingLink.evaluate(link => link.getAttribute('href')), `/teardown/${confirmingId}`)
  await page.locator(`a[href="/desk/${authorId}"]`).last().click()
  await selectedTab('大纲')
  check('作者自己的书继续恢复原大纲页；待确认拆书仍指向确认页')

  await page.goto(base)
  await page.evaluate(id => { history.pushState({ usr: { teardownHome: true }, key: 'isolated-import-fixture', idx: (history.state?.idx ?? 0) + 1 }, '', `/desk/${id}`) }, bookId)
  await page.reload()
  await selectedTab('正文')
  await expect(page.locator('.continue')).toContainText('第 2 章 来信')
  await entryConsumed()
  await page.locator('.continue a.btn').filter({ hasText: /^接着读/ }).click()
  await expect(page.locator('.page.reader h1')).toHaveText('第 2 章 来信')
  await page.reload()
  await selectedTab('正文')
  await expect(page.locator('.page.reader h1')).toHaveText('第 2 章 来信')
  check('旧导入入口 teardownHome 仍打开正文首页；消费标记后读章刷新不再跳首页')

  assert.deepEqual(evidence.pageErrors, [])
  assert.deepEqual(evidence.unexpectedRequests, [])
  assert.deepEqual(evidence.externalRequests, [])
  assert(evidence.requests.every(request => request.method === 'GET'), '导航只能产生只读 GET 请求')
  assert.deepEqual(await fingerprint(), evidence.sourceSha256, '验收期间导航源文件变动，需要在稳定版本重跑')
  check('零页面异常、零意外接口、零外部请求、零写请求，导航源文件验收前后相同')
  evidence.ok = true
} catch (error) {
  evidence.ok = false
  evidence.error = error.stack || String(error)
  if (page) await screenshot('FAILED-state.png').catch(() => {})
  throw error
} finally {
  evidence.finishedAt = new Date().toISOString()
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(evidence, null, 2) + '\n')
  await browser?.close()
  await server.close()
}
console.log(JSON.stringify({ checks: evidence.checks.length, pageErrors: evidence.pageErrors.length, unexpectedRequests: evidence.unexpectedRequests.length, externalRequests: evidence.externalRequests.length }))
