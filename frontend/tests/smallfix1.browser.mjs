/** 小修 1 真书验收：只读访问隔离书库副本；不模拟 API、不启动服务、不触碰日常环境或模型。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const base = process.env.ZHIBI_SMALLFIX_URL ?? 'http://127.0.0.1:4357'
const api = process.env.ZHIBI_SMALLFIX_API ?? 'http://127.0.0.1:8057/api'
const bookId = 'ff4aff0b-d1f1-46c4-b120-f7da9ac1ec2a'
const output = path.join(root, 'docs/小修验收')
for (const value of [base, api]) {
  const url = new URL(value)
  assert.equal(url.hostname, '127.0.0.1', '验收只连接显式的本机隔离环境')
  assert.ok(!['8000', '4320', ''].includes(url.port), '禁止连接日常端口')
}
await fs.mkdir(output, { recursive: true })
const sources = [
  'backend/app/api/books.py', 'backend/app/schemas.py', 'backend/app/services/teardown_info.py',
  'frontend/src/api/types.ts', 'frontend/src/lib/teardownShelf.ts',
  'frontend/src/lib/workspaceReadingPosition.ts', 'frontend/src/pages/Home.tsx',
  'frontend/src/pages/workspace/Workspace.tsx',
  'frontend/src/pages/workspace/desk-v2/SettingsPages.tsx',
  'frontend/src/pages/workspace/desk-v2/settingsData.ts', 'frontend/tests/smallfix1.browser.mjs',
]
const fingerprint = async () => Object.fromEntries(await Promise.all(sources.map(async file => [file, createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex')])))
const report = {
  startedAt: new Date().toISOString(), base, api, bookId,
  isolation: 'Actual API/UI backed by read-only library copy in zhibi_smallfix1_final_accept (PostgreSQL 5557, Redis 6417, API 8057, frontend 4357). This browser script sends GET only; it never fulfills/fakes API responses, starts services or calls models. Only the isolated copy has its previously organized settings reset to exercise the empty state; original 498 chapters / 100 read chapters are unchanged.',
  fixtureProof: 'data/smallfix1-final/empty-fixture.json',
  sourceSha256: await fingerprint(), checks: [], screenshots: [], requests: [], directApiRequests: [],
  deniedRequests: [], failedApiResponses: [], pageErrors: [],
}
const check = (name, details = {}) => { report.checks.push({ name, ...details }); console.log(`PASS ${name}`) }
const readApi = async pathname => {
  report.directApiRequests.push({ method: 'GET', path: pathname })
  const response = await fetch(`${api}${pathname}`)
  assert.ok(response.ok, `${pathname}: ${response.status}`)
  return response.json()
}
const tab = (page, name) => page.locator('header.top nav.tabs a').filter({ hasText: new RegExp(`^${name}$`) })
const screenshot = async (target, name) => {
  await target.screenshot({ path: path.join(output, name), animations: 'disabled' })
  report.screenshots.push(`docs/小修验收/${name}`)
}
let browser, page
try {
  const [books, detail, chapters, library, fixtureProof] = await Promise.all([
    readApi('/books'), readApi(`/books/${bookId}`), readApi(`/books/${bookId}/chapters`),
    readApi(`/books/${bookId}/library`), fs.readFile(path.join(root, report.fixtureProof), 'utf8').then(JSON.parse),
  ])
  const summary = books.find(book => book.id === bookId)
  assert.ok(summary, '只读副本包含作者的逆天邪神')
  assert.equal(summary.title, '逆天邪神')
  assert.equal(summary.source, 'teardown')
  assert.equal(summary.teardown.stage, 'stopped')
  assert.equal(summary.teardown.chapters, 498)
  assert.equal(summary.teardown.read, 100)
  assert.equal(detail.teardown.read, 100)
  assert.equal(chapters.length, 498)
  const readChapters = chapters.filter(chapter => chapter.teardown?.read)
  assert.equal(readChapters.length, 100)
  assert.equal(Math.max(...readChapters.map(chapter => chapter.index)), 100)
  assert.ok(detail.teardown.settings?.upto == null)
  assert.deepEqual(library.characters, [])
  assert.deepEqual(library.entries, [])
  assert.equal(fixtureProof.database, 'zhibi_smallfix1_final_accept')
  assert.equal(fixtureProof.read_real_chapters, 100)
  assert.equal(fixtureProof.total_real_chapters, 498)
  report.fixture = { title: summary.title, stage: summary.teardown.stage, chapters: chapters.length, listRead: summary.teardown.read, detailRead: detail.teardown.read, chapterRead: readChapters.length, lastRead: 100, settingsUpto: detail.teardown.settings?.upto ?? null, characters: library.characters.length, entries: library.entries.length, proof: fixtureProof }
  check('真实只读副本：498 章、100 章已读，列表与详情 read 一致，设定未整理且无任何条目', report.fixture)

  browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM ?? process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? 'C:/Users/cxc/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe' })
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Taipei', colorScheme: 'light', reducedMotion: 'reduce', serviceWorkers: 'block' })
  // Fresh browser storage: the shelf click itself must select the introduction.
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== base) {
      report.deniedRequests.push({ method: request.method(), url: request.url(), reason: 'Unexpected external origin' })
      return route.abort('blockedbyclient')
    }
    if (url.pathname.startsWith('/api/')) {
      const entry = { method: request.method(), path: url.pathname + url.search }
      report.requests.push(entry)
      if (request.method() !== 'GET' || /\/(?:models|test)(?:\/|$)/.test(url.pathname)) {
        report.deniedRequests.push({ ...entry, reason: 'Mutating or model-related API forbidden' })
        return route.abort('blockedbyclient')
      }
    }
    return route.continue()
  })
  page = await context.newPage()
  page.on('pageerror', error => report.pageErrors.push(error.message))
  page.on('response', response => {
    const url = new URL(response.url())
    if (url.pathname.startsWith('/api/') && !response.ok()) report.failedApiResponses.push({ status: response.status(), path: url.pathname + url.search })
  })
  await page.goto(base, { waitUntil: 'domcontentloaded' })
  const shelfSection = page.locator('section[aria-label="拆的书"]')
  const shelfLink = shelfSection.locator(`a[href="/desk/${bookId}"]`)
  await expect(shelfLink).toBeVisible()
  await expect(shelfLink.locator('p.text-ink-2')).toHaveText('已拆 100 / 498 章')
  await page.evaluate(() => document.fonts.ready)
  await screenshot(shelfSection, '书架-已拆100章.png')
  check('书架卡片逐字显示「已拆 100 / 498 章」，斜杠左右各一个空格，无旧 stop_note 句子')

  await shelfLink.click()
  await expect(page).toHaveURL(`${base}/desk/${bookId}`)
  await expect(tab(page, '简介')).toHaveClass(/\bon\b/)
  await expect(page.locator('.intro-top h1')).toHaveText('逆天邪神')
  check('由真实书架入口点击拆的书，进入同一本书的简介页')
  await tab(page, '设定').click()
  await expect(tab(page, '设定')).toHaveClass(/\bon\b/)
  const paper = page.locator('.desk-v2 .page.full')
  await expect(paper.locator('h1')).toHaveText('设定')
  await expect(paper.locator('.meta')).toHaveText('设定还没整理：点右上角「接着拆」，拆到第 100 章不变，只整理设定，不重读原文')
  await expect(paper.locator('.rule1')).toBeVisible()
  await expect(paper.locator('.tiles')).toHaveCount(0)
  await expect(paper.locator('.tile')).toHaveCount(0)
  await expect(paper.locator('.card')).toHaveCount(0)
  await expect(page.locator('header.top .progress a.btn').filter({ hasText: /^接着拆$/ })).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
  await screenshot(page, '设定-尚未整理.png')
  check('未整理设定页保留原标题与分隔线，meta 逐字一致；八个空框全部不画，接着拆按钮可见但未点击')

  assert.deepEqual(report.pageErrors, [])
  assert.deepEqual(report.deniedRequests, [])
  assert.deepEqual(report.failedApiResponses, [])
  assert.ok(report.requests.length > 0)
  assert.ok(report.requests.every(request => request.method === 'GET'))
  assert.deepEqual(await fingerprint(), report.sourceSha256, '验收期间源文件变化，必须在稳定版本重跑')
  check('零页面异常、零 API 失败、零外部请求、零写请求；所有请求实际透传，验收源文件前后 SHA-256 相同')
  report.ok = true
} catch (error) {
  report.ok = false
  report.error = error.stack ?? String(error)
  throw error
} finally {
  report.finishedAt = new Date().toISOString()
  await fs.writeFile(path.join(output, '小修1浏览器验收.json'), JSON.stringify(report, null, 2) + '\n')
  await browser?.close()
}
console.log(JSON.stringify({ checks: report.checks.length, screenshots: report.screenshots, readOnlyGetRequests: report.requests.length, pageErrors: report.pageErrors.length }))
