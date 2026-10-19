/** Editorial display mode survives reloads, navigation and reopening; all APIs are mocked.
 * TEST_BASE_URL=http://127.0.0.1:<isolated-port> node tests/editorial-dock.browser.mjs
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const baseURL = process.env.TEST_BASE_URL
assert.ok(baseURL, 'Provide an isolated frontend through TEST_BASE_URL')
const origin = new URL(baseURL)
assert.ok(['127.0.0.1', 'localhost'].includes(origin.hostname), 'Only isolated local frontends are allowed')
assert.notEqual(origin.port, '4320', 'Never use the daily frontend')
const artifacts = resolve(process.env.TEST_ARTIFACT_DIR || '../data/editorial-dock-20261019')
await mkdir(artifacts, { recursive: true })
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.ZHIBI_CHROMIUM
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const dockKey = 'zhibi:editorial-dock'
const prototypeKey = 'zhibi:prototype-editorial-dock'
const books = ['one', 'two'].map((suffix, index) => ({
  id: `editorial-dock-${suffix}`, title: `编辑部记忆验收${index + 1}`, source: 'new', status: 'ready', idea: '', genre: '', logline: '',
  job_status: null, active_job: null, concept: {}, spine: {}, requirements: [], style_reference: '', trial_read_done: false, chapters_final: 0, words_final: 0,
  created_at: '2026-10-19T01:00:00Z', updated_at: '2026-10-19T01:00:00Z',
}))
const settings = { title_style: 'short', title_custom: '', person: 'third', intimacy: 'fade', intimacy_custom: '', chapter_words: 3000, other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 2, review_strictness: 'standard', volume_audit: true, volume_approval: true, trial_read: true }
const suggestions = [{ id: 'dock-fixture-suggestion', title: '仅供布局验收的建议', kind: 'chat', target_type: null, target_id: null, payload: {}, origin: {}, status: 'pending' }]
const results = []

async function fixture(name, initial) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', serviceWorkers: 'block' })
  const errors = [], unexpected = []
  context.on('page', page => page.on('pageerror', error => { errors.push(error.message); console.error(`${name}: ${error.message}`) }))
  await context.addInitScript(() => {
    window.__firstEditorialMode = null
    const observer = new MutationObserver(() => {
      if (window.__firstEditorialMode) return
      if (document.querySelector('[data-testid="editorial-docked"]')) window.__firstEditorialMode = 'side'
      else if (document.querySelector('[data-testid="editorial-floating"]')) window.__firstEditorialMode = 'float'
      else if (document.querySelector('button[title="编辑部"]')) window.__firstEditorialMode = 'ball'
    })
    observer.observe(document, { childList: true, subtree: true })
  })
  if (initial) await context.addInitScript(initial)
  await context.route('**/api/**', route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (request.method() === 'GET') {
      if (path.endsWith('/events')) return route.fulfill({ status: 204 })
      if (path === '/api/books') return route.fulfill({ json: books })
      if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
      if (path === '/api/llm/profiles') return route.fulfill({ json: [] })
      if (path === '/api/book-meta') return route.fulfill({ json: { channels: [], chapter_words: 3000, max_tags: 6 } })
      const book = books.find(item => path === `/api/books/${item.id}` || path.startsWith(`/api/books/${item.id}/`))
      if (book) {
        const suffix = path.slice(`/api/books/${book.id}`.length)
        const values = {
          '': book, '/outline': { book_id: book.id, volumes: [] }, '/outline-tree': { arcs: [], ending: null, segmented: false },
          '/library': { categories: [], characters: [], entries: [], focus: { characters: [], entries: [] }, suggestions_pending: suggestions.length },
          '/bible': { characters: [], world_entries: [], relationships: [], foreshadowings: [] },
          '/chapters': [], '/requirements': [], '/threads': [], '/saves': { items: [] },
          '/settings': { settings, rules_text: '【这本书的写作规矩】' }, '/chat/conversations': [],
          '/suggestions': url.searchParams.get('status') === 'accepted' ? [] : suggestions, '/suggestion-changes': {},
        }
        if (Object.hasOwn(values, suffix)) return route.fulfill({ json: values[suffix] })
      }
    }
    unexpected.push(`${request.method()} ${path}`)
    console.error(`${name}: blocked unexpected ${request.method()} ${path}`)
    return route.fulfill({ status: 500, json: { detail: 'Unexpected API request blocked by editorial dock test' } })
  })
  const check = async page => {
    assert.deepEqual(unexpected, [], `${name}: only mocked read-only API traffic`)
    assert.deepEqual(errors, [], `${name}: no page errors`)
    await page.screenshot({ path: resolve(artifacts, `${name}.png`) })
    results.push({ name, errors, unexpected })
    console.log(`PASS ${name}`)
  }
  return { context, page: await context.newPage(), check }
}

const desk = (page, book = books[0]) => page.goto(`${baseURL}/desk/${book.id}`)
async function mode(page, expected) {
  const states = { ball: page.locator('button[title="编辑部"]'), float: page.getByTestId('editorial-floating'), side: page.getByTestId('editorial-docked') }
  await expect(states[expected]).toBeVisible()
  for (const [name, locator] of Object.entries(states)) if (name !== expected) await expect(locator).toHaveCount(0)
}
async function stored(page, expected, key = dockKey) {
  await expect.poll(() => page.evaluate(key => localStorage.getItem(key), key)).toBe(expected)
}
async function reloadAs(page, expected) {
  await page.reload()
  await mode(page, expected)
  assert.equal(await page.evaluate(() => window.__firstEditorialMode), expected, 'Restored mode renders immediately without flashing the ball')
}

try {
  {
    const f = await fixture('mode-lifecycle')
    let page = f.page
    try {
      await desk(page)
      await mode(page, 'ball')
      await page.locator('button[title="编辑部"]').click()
      await mode(page, 'float')
      await page.getByRole('button', { name: '贴到右边', exact: true }).click()
      await mode(page, 'side')
      await stored(page, 'side')
      await reloadAs(page, 'side')
      // Leave/re-enter through actual SPA links, then enter a different book.
      await page.getByRole('link', { name: '书房', exact: true }).click()
      await page.locator(`a[href="/desk/${books[0].id}"]`).first().click()
      await mode(page, 'side')
      await page.getByRole('link', { name: '书房', exact: true }).click()
      await page.locator(`a[href="/desk/${books[1].id}"]`).first().click()
      await mode(page, 'side')
      // Closing the tab removes React memory, but not the browser's layout preference.
      await page.close()
      page = await f.context.newPage()
      await desk(page)
      await mode(page, 'side')
      assert.equal(await page.evaluate(() => window.__firstEditorialMode), 'side')
      await page.getByRole('button', { name: '浮起来', exact: true }).click()
      await stored(page, 'float')
      await reloadAs(page, 'float')
      await page.getByRole('button', { name: '收起', exact: true }).click()
      await stored(page, 'ball')
      await reloadAs(page, 'ball')
      // openChat's functional setter (pending-ball entry) also persists the mode.
      await page.getByTestId('pending-ball-tag').click()
      await mode(page, 'float')
      await stored(page, 'float')
      await expect(page.getByRole('button', { name: '回到聊天', exact: true })).toBeVisible()
      await reloadAs(page, 'float')
      // Drag-to-edge follows the same persistence path as the header button.
      const title = await page.getByTestId('editorial-title').boundingBox()
      assert.ok(title)
      await page.mouse.move(title.x + title.width / 2, title.y + title.height / 2)
      await page.mouse.down()
      await page.mouse.move(1435, title.y + title.height / 2, { steps: 8 })
      await page.mouse.up()
      await mode(page, 'side')
      await stored(page, 'side')
      await reloadAs(page, 'side')
      await f.check(page)
    } finally { await f.context.close() }
  }
  {
    const f = await fixture('invalid-storage')
    try {
      await desk(f.page)
      for (const invalid of ['corrupt', '{"dock":"side"}', 'null', 'SIDE', '']) {
        await f.page.evaluate(({ key, value }) => localStorage.setItem(key, value), { key: dockKey, value: invalid })
        await reloadAs(f.page, 'ball')
        await f.page.locator('button[title="编辑部"]').click()
        await mode(f.page, 'float')
      }
      await f.check(f.page)
    } finally { await f.context.close() }
  }
  {
    const f = await fixture('storage-unavailable', () => {
      Object.defineProperty(window, 'localStorage', { configurable: true, get: () => { throw new DOMException('Storage disabled for test', 'SecurityError') } })
    })
    try {
      await desk(f.page)
      await mode(f.page, 'ball')
      await f.page.locator('button[title="编辑部"]').click()
      await f.page.getByRole('button', { name: '贴到右边', exact: true }).click()
      await mode(f.page, 'side')
      await f.page.getByRole('button', { name: '浮起来', exact: true }).click()
      await mode(f.page, 'float')
      await f.page.getByRole('button', { name: '收起', exact: true }).click()
      await mode(f.page, 'ball')
      await reloadAs(f.page, 'ball')
      await f.check(f.page)
    } finally { await f.context.close() }
  }
  {
    const f = await fixture('prototype-isolation')
    try {
      await desk(f.page)
      await f.page.locator('button[title="编辑部"]').click()
      await f.page.getByRole('button', { name: '贴到右边', exact: true }).click()
      await stored(f.page, 'side')
      await f.page.goto(`${baseURL}/prototype/workspace?book=empty`)
      await mode(f.page, 'ball')
      await f.page.locator('button[title="编辑部"]').click()
      await mode(f.page, 'float')
      await stored(f.page, 'float', prototypeKey)
      await stored(f.page, 'side')
      await reloadAs(f.page, 'float')
      await desk(f.page)
      await mode(f.page, 'side')
      await stored(f.page, 'float', prototypeKey)
      await f.check(f.page)
    } finally { await f.context.close() }
  }
  await writeFile(resolve(artifacts, 'results.json'), JSON.stringify(results, null, 2))
} finally { await browser.close() }
