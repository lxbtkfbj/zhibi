/** Editorial header regression. Every API request is mocked; no author books or model calls are used.
 * Run against an isolated Vite port: TEST_BASE_URL=http://127.0.0.1:4398 node tests/chat-header.browser.mjs
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4398'
const url = new URL(baseURL)
assert.ok(['127.0.0.1', 'localhost'].includes(url.hostname), 'Use a local isolated frontend')
assert.notEqual(url.port, '4320', 'Never use the daily frontend')
const artifacts = resolve(process.env.TEST_ARTIFACT_DIR || '../data/chat-header-20261019')
await mkdir(artifacts, { recursive: true })
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.ZHIBI_CHROMIUM
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const book = { id: 'chat-header-fixture', title: '编辑部布局验收', source: 'new', status: 'ready', idea: '', genre: '', logline: '', job_status: null, active_job: null, concept: {}, spine: {}, requirements: [], style_reference: '', trial_read_done: false, chapters_final: 0, words_final: 0 }
const settings = { title_style: 'short', title_custom: '', person: 'third', intimacy: 'fade', intimacy_custom: '', chapter_words: 3000, other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 2, review_strictness: 'standard', volume_audit: true, volume_approval: true, trial_read: true }
const cases = [
  { name: 'wide', width: 1440, height: 1000, panel: 620, pending: 3 },
  { name: 'default', width: 1440, height: 1000, panel: 520, pending: 3 },
  { name: 'narrow', width: 1440, height: 1000, panel: 440, pending: 3 },
  { name: 'minimum', width: 1440, height: 1000, panel: 320, pending: 125 },
  { name: 'large-interface', width: 2560, height: 1440, panel: 320, pending: 125, large: true, theme: 'ink' },
  { name: 'mobile', width: 390, height: 844, pending: 3 },
]
const results = []

async function assertHeader(page, context) {
  const header = page.getByTestId('editorial-header')
  const title = page.getByTestId('editorial-title')
  await expect(title).toBeVisible()
  const layout = await header.evaluate(el => {
    const box = el.getBoundingClientRect()
    const title = el.querySelector('[data-testid="editorial-title"]')
    const range = document.createRange()
    range.selectNodeContents(title)
    const buttons = [...el.querySelectorAll('button')].map(button => {
      const rect = button.getBoundingClientRect()
      return { label: button.getAttribute('aria-label') || button.textContent, x: rect.x, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width }
    })
    return { x: box.x, right: box.right, top: box.top, bottom: box.bottom, scroll: el.scrollWidth, client: el.clientWidth, titleLines: range.getClientRects().length, titleRight: title.getBoundingClientRect().right, buttons }
  })
  assert.equal(layout.titleLines, 1, `${context}: title stays on one line`)
  assert.ok(layout.scroll <= layout.client + 1, `${context}: no header overflow`)
  let previousRight = layout.titleRight
  for (const button of layout.buttons) {
    assert.ok(button.x >= previousRight - 1, `${context}: ${button.label} never overlaps the preceding control`)
    assert.ok(button.x >= layout.x && button.right <= layout.right + 1, `${context}: ${button.label} stays inside the header`)
    assert.ok(button.top >= layout.top && button.bottom <= layout.bottom + 1, `${context}: ${button.label} is not vertically clipped`)
    assert.ok(button.width >= 27, `${context}: ${button.label} remains a usable target`)
    previousRight = button.right
  }
  return layout
}

try {
  for (const scenario of cases) {
    const context = await browser.newContext({ viewport: { width: scenario.width, height: scenario.height }, reducedMotion: 'reduce', serviceWorkers: 'block' })
    const page = await context.newPage()
    const errors = [], unexpected = [], mutations = []
    const suggestions = Array.from({ length: scenario.pending }, (_, i) => ({ id: `suggestion-${i}`, title: `待确认建议 ${i + 1}`, kind: 'chat', target_type: null, target_id: null, payload: {}, origin: {}, status: 'pending' }))
    let conversations = [{ id: 'current', title: '讨论第一卷的方向', notes: 2, current: true, archived: false, last_at: '2026-10-19T01:00:00Z' }]
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(({ large, theme }) => {
      localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: theme || 'paper', reducedMotion: true, uiScale: large ? 'large' : 'standard', deskScale: large ? 120 : 100 }))
      localStorage.setItem('zhibi-prototype-chat-width', '320')
    }, scenario)
    await page.route('**/api/**', route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname
      if (!path.startsWith('/api/')) return route.continue()
      if (request.method() === 'GET') {
        if (path.endsWith('/events')) return route.fulfill({ status: 204 })
        if (path === '/api/book-meta') return route.fulfill({ json: { channels: [], chapter_words: 3000, max_tags: 6 } })
        const suffix = path.replace(`/api/books/${book.id}`, '')
        const values = {
          '': book,
          '/outline': { book_id: book.id, volumes: [] },
          '/outline-tree': { arcs: [], ending: null, segmented: false },
          '/library': { categories: [], characters: [], entries: [], focus: { characters: [], entries: [] }, suggestions_pending: suggestions.length },
          '/bible': { characters: [], world_entries: [], relationships: [], foreshadowings: [] },
          '/chapters': [], '/requirements': [], '/threads': [], '/saves': { items: [] },
          '/settings': { settings, rules_text: '【这本书的写作规矩】' },
          '/chat/conversations': conversations,
          '/suggestions': url.searchParams.get('status') === 'accepted' ? [] : suggestions,
          '/suggestion-changes': {},
        }
        if (Object.hasOwn(values, suffix)) return route.fulfill({ json: values[suffix] })
      }
      if (request.method() === 'POST' && path === `/api/books/${book.id}/chat/conversations`) {
        mutations.push(path)
        const next = { id: 'new-conversation', title: '', notes: 0, current: true, archived: false, last_at: '2026-10-19T02:00:00Z' }
        conversations = [next, ...conversations.map(c => ({ ...c, current: false }))]
        return route.fulfill({ json: next })
      }
      unexpected.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected request blocked by chat header test' } })
    })
    try {
      await page.goto(`${baseURL}/desk/${book.id}`)
      await page.locator('button[title="编辑部"]').click()
      const floating = page.getByTestId('editorial-floating')
      await expect(page.getByLabel('给编辑部发消息')).toBeVisible()
      // Lock the same CSS dimensions used by native resizing so unrelated query updates cannot reset the fixture width.
      if (scenario.panel) await page.addStyleTag({ content: `[data-testid="editorial-floating"] { width: ${scenario.panel}px !important; }` })
      await page.evaluate(() => document.fonts.ready)
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      if (scenario.panel) await expect.poll(() => floating.evaluate(el => el.offsetWidth)).toBe(scenario.panel)
      const layout = await assertHeader(page, scenario.name)
      const header = page.getByTestId('editorial-header')
      assert.equal(await floating.getByText('设定师', { exact: true }).evaluate(el => {
        const range = document.createRange()
        range.selectNodeContents(el)
        return range.getClientRects().length
      }), 1, `${scenario.name}: empty-state role names remain horizontal`)
      if (scenario.name === 'wide') {
        const before = await floating.boundingBox(), title = await page.getByTestId('editorial-title').boundingBox()
        await page.mouse.move(title.x + title.width / 2, title.y + title.height / 2)
        await page.mouse.down()
        await page.mouse.move(title.x + title.width / 2 - 80, title.y + title.height / 2 - 60, { steps: 5 })
        await page.mouse.up()
        await expect.poll(async () => {
          const after = await floating.boundingBox()
          return Math.abs(after.x - before.x + 80) < 2 && Math.abs(after.y - before.y + 60) < 2
        }, { message: 'Header still drags the floating panel' }).toBe(true)
      }
      const newLabel = header.getByRole('button', { name: '新对话', exact: true }).locator('span')
      if (scenario.panel >= 520) await expect(newLabel).toBeVisible()
      else await expect(newLabel).not.toBeVisible()
      await header.getByRole('button', { name: '以前的对话', exact: true }).click()
      const menu = page.getByRole('listbox', { name: '以前的对话' })
      await expect(menu).toBeVisible()
      const bounds = await floating.boundingBox(), menuBounds = await menu.boundingBox()
      assert.ok(menuBounds.x >= bounds.x && menuBounds.x + menuBounds.width <= bounds.x + bounds.width + 1, `${scenario.name}: history menu is not clipped by narrow panel`)
      await expect(menu.getByRole('option', { name: /讨论第一卷的方向/ })).toBeVisible()
      await page.screenshot({ path: resolve(artifacts, `${scenario.name}-history.png`) })
      await header.getByRole('button', { name: '以前的对话', exact: true }).click()
      await header.getByRole('button', { name: /^待处理/ }).click()
      await expect(page.getByRole('button', { name: '回到聊天', exact: true })).toBeVisible()
      await assertHeader(page, `${scenario.name} pending`)
      await page.getByRole('button', { name: '回到聊天', exact: true }).click()
      const newChat = header.getByRole('button', { name: '新对话', exact: true })
      await newChat.focus()
      await newChat.press('Enter')
      await expect.poll(() => mutations.length).toBe(1)
      await expect(newChat).toBeEnabled()
      await page.screenshot({ path: resolve(artifacts, `${scenario.name}.png`) })
      if (scenario.name === 'narrow') await header.screenshot({ path: resolve(artifacts, 'narrow-header.png') })
      if (scenario.name !== 'mobile') {
        // Dock/float and collapse are still reachable even at the minimum supported width.
        await header.getByRole('button', { name: '贴到右边', exact: true }).click()
        await expect(page.getByTestId('editorial-docked')).toBeVisible()
        await assertHeader(page, `${scenario.name} docked 320`)
        await header.getByRole('button', { name: '浮起来', exact: true }).click()
      }
      await header.getByRole('button', { name: '收起', exact: true }).click()
      await expect(header).not.toBeVisible()
      await page.locator('button[title="编辑部"]').click()
      await expect(header).toBeVisible()
      if (scenario.name === 'wide') {
        await page.getByRole('button', { name: /^存档/ }).click()
        const saves = page.getByRole('dialog', { name: '存档', exact: true })
        await expect(saves).toBeVisible()
        const bounds = await saves.boundingBox()
        assert.ok(Math.abs(bounds.x + bounds.width / 2 - scenario.width / 2) < 2, 'Saves dialog centers inside the real workspace')
        await page.screenshot({ path: resolve(artifacts, 'saves-in-workspace.png') })
        await page.keyboard.press('Escape')
        await expect(saves).not.toBeVisible()
        await expect(page.getByRole('button', { name: /^存档/ })).toBeEnabled()
      }
      assert.deepEqual(unexpected, [], 'All network traffic stayed within explicit mocks')
      assert.deepEqual(errors, [], 'No page errors')
      results.push({ scenario: scenario.name, viewport: { width: scenario.width, height: scenario.height }, layout, errors, unexpected, mockedMutations: mutations.length })
      console.log(`PASS ${scenario.name}: single-line title/roles, all tools, contained history, keyboard new chat, pending/back, dock/float/collapse${scenario.name === 'wide' ? ', header drag' : ''}`)
    } catch (error) {
      await page.screenshot({ path: resolve(artifacts, `${scenario.name}-failure.png`) }).catch(() => {})
      console.error({ errors, unexpected })
      throw error
    } finally { await context.close() }
  }
  await writeFile(resolve(artifacts, 'results.json'), JSON.stringify(results, null, 2))
} finally { await browser.close() }
