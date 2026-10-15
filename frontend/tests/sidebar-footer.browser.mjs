/** Isolated sidebar layout regression: every API call is mocked; no author data is changed. */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4332'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const artifacts = resolve(process.env.TEST_ARTIFACT_DIR || '../data/sidebar-footer-20261016')
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const book = { id: 'sidebar-fixture', title: '底栏布局测试', source: 'new', status: 'ready', idea: '', genre: '', logline: '', job_status: null, active_job: null, concept: {}, spine: {}, requirements: [], style_reference: '', trial_read_done: false, chapters_final: 0, words_final: 0 }
const settings = { title_style: 'short', title_custom: '', person: 'third', intimacy: 'fade', intimacy_custom: '', chapter_words: null, other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 2, review_strictness: 'standard', volume_audit: true, volume_approval: true, trial_read: true }
const cases = [
  { width: 1440, height: 1000, volumes: 0, theme: 'paper' },
  { width: 1440, height: 720, volumes: 32, theme: 'paper' },
  { width: 1440, height: 600, volumes: 32, theme: 'ink' },
  { width: 1440, height: 720, volumes: 32, theme: 'ink', large: true },
  { width: 390, height: 844, volumes: 32, theme: 'paper' },
  { width: 390, height: 568, volumes: 32, theme: 'ink' },
]
try {
  for (const scenario of cases) {
    const { width, height, volumes, theme, large } = scenario
    const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce' })
    const page = await context.newPage()
    const errors = [], unexpected = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(({ theme, large }) => localStorage.setItem('zhibi:appearance', JSON.stringify({ theme, reducedMotion: true, uiScale: large ? 'large' : 'standard' })), { theme, large })
    const outline = { book_id: book.id, volumes: Array.from({ length: volumes }, (_, i) => ({ id: `volume-${i + 1}`, index: i + 1, title: `第${i + 1}卷 · 长目录测试`, chapter_count: 8, status: 'planned', units: [] })) }
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname
      if (!path.startsWith('/api/')) return route.continue()
      if (route.request().method() === 'GET') {
        if (path.endsWith('/events')) return route.fulfill({ status: 204 })
        const suffix = path.replace(`/api/books/${book.id}`, '')
        const values = { '': book, '/outline': outline, '/bible': { characters: [], world_entries: [], relationships: [], foreshadowings: [] }, '/threads': [], '/chapters': [], '/requirements': [], '/settings': { settings, rules_text: '【这本书的写作规矩】' } }
        if (Object.hasOwn(values, suffix)) return route.fulfill({ json: values[suffix] })
      }
      unexpected.push(`${route.request().method()} ${path}`)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected request blocked by sidebar test' } })
    })
    try {
      await page.goto(`${baseURL}/books/${book.id}/chapters`)
      await expect(page.getByTestId('full-sidebar')).toBeAttached()
      const mobile = !await page.getByTestId('full-sidebar').isVisible()
      if (mobile) await page.getByRole('button', { name: '展开书稿目录' }).click()
      const sidebar = mobile ? page.getByRole('dialog', { name: '编辑部与书稿目录' }) : page.getByTestId('full-sidebar')
      const nav = sidebar.getByRole('navigation', { name: '书稿目录' })
      const footer = sidebar.getByTestId('book-settings-footer')
      const link = footer.getByRole('link', { name: '本书设置', exact: true })
      await expect(link).toBeInViewport({ ratio: 1 })
      await expect(nav.getByRole('link', { name: '本书设置', exact: true })).toHaveCount(0)
      const before = await footer.boundingBox()
      const bounds = await sidebar.boundingBox()
      assert.ok(Math.abs(before.y + before.height - bounds.y - bounds.height) < 1, 'Footer stays at sidebar bottom')
      assert.ok(before.y + before.height <= height, 'Footer stays inside viewport')
      if (volumes) {
        await expect(nav.getByRole('link', { name: '第 32 卷', exact: false })).toBeAttached()
        assert.ok(await nav.evaluate(el => el.scrollHeight > el.clientHeight), 'Long directory scrolls independently')
      }
      await nav.evaluate(el => { el.scrollTop = el.scrollHeight })
      if (volumes) await expect.poll(() => nav.evaluate(el => el.scrollTop)).toBeGreaterThan(0)
      assert.deepEqual(await footer.boundingBox(), before, 'Scrolling the directory never moves settings')
      const last = await nav.getByRole('link', { name: /^伏笔/ }).boundingBox()
      assert.ok(last.y + last.height <= before.y, 'Last directory item is not covered by footer')
      await expect(link).toBeInViewport({ ratio: 1 })
      await nav.evaluate(el => { el.scrollTop = 0 })
      assert.deepEqual(await footer.boundingBox(), before)
      await page.screenshot({ path: resolve(artifacts, `sidebar-${width}x${height}-${theme}${large ? '-large' : ''}.png`) })
      await link.focus()
      await link.press('Enter')
      await expect(page).toHaveURL(new RegExp(`/books/${book.id}/settings$`))
      await expect(page.getByRole('heading', { name: '本书设置', exact: true })).toBeVisible()
      if (mobile) {
        await expect(sidebar).not.toBeVisible()
        await page.getByRole('button', { name: '展开书稿目录' }).click()
      }
      await expect(sidebar.getByRole('link', { name: '本书设置', exact: true })).toHaveAttribute('aria-current', 'page')
      assert.deepEqual(errors, [])
      assert.deepEqual(unexpected, [])
      console.log(`PASS ${width}x${height} ${theme}${large ? ' large text' : ''}: pinned footer, ${volumes} volumes, scroll isolation, keyboard navigation${mobile ? ', drawer closes' : ''}`)
    } finally { await context.close() }
  }
} finally { await browser.close() }
