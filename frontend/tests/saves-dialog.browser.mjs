/** Isolated save-dialog acceptance. Never calls a real backend or mutates a book.
 * Run from frontend: node tests/saves-dialog.browser.mjs
 * Uses a private Vite server with all API traffic blocked except Playwright fixtures.
 * ZHIBI_CHROMIUM / PLAYWRIGHT_CHROMIUM_EXECUTABLE may select an installed browser.
 * Screenshots and machine-readable evidence: data/saves-dialog/ (git-ignored).
 */
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
const output = path.join(root, 'data/saves-dialog')
const port = Number(process.env.SAVES_TEST_PORT || 4376)
const base = `http://127.0.0.1:${port}`
await fs.mkdir(output, { recursive: true })
const fingerprint = async () => Object.fromEntries(await Promise.all(['frontend/src/pages/workspace/Saves.tsx', 'frontend/src/pages/workspace/saves.css'].map(async (file) => [file, createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex')])))
const evidence = { base, startedAt: new Date().toISOString(), sourceSha256: await fingerprint(), isolation: 'Programmatic Vite, no proxy, private optimizer cache, /api middleware fail-closed, every API response mocked in Playwright.', checks: [], screenshots: [], requests: [], pageErrors: [], unexpectedRequests: [] }
const check = (name, detail = {}) => { evidence.checks.push({ name, ...detail }); console.log(`PASS ${name}`) }
const harness = `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>存档独立 UI 验收夹具</title></head><body><div id="root"></div><script type="module">
import React, { useCallback, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SavesPanel } from '/src/pages/workspace/Saves.tsx';
import { BookContext } from '/src/pages/book/context.tsx';
import '/src/index.css';
const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
function App() {
  const [open, setOpen] = useState(false), [saveId, setSaveId] = useState(null), [job, setJob] = useState(null);
  window.savesTest = { setJob, setOpen };
  const onClose = useCallback(() => setOpen(false), []);
  return React.createElement(QueryClientProvider, {client: qc}, React.createElement(BookContext.Provider, {value:{bookId:'ui-fixture-only',book:{title:'雾港来信'},job}},
    React.createElement('main', {className:'min-h-screen bg-paper text-ink px-10 py-8'},
      React.createElement('p', {className:'text-xs text-ink-3 mb-6'}, '执笔 · 独立 UI 验收夹具（模拟数据，不连接书库）'),
      React.createElement('h1', {className:'font-serif text-3xl mb-5'}, '雾港来信'),
      React.createElement('p', {className:'max-w-xl text-ink-2 leading-8 mb-8'}, '雨落在旧码头。她把那封没有署名的信放进口袋，沿着灯火往前走。'),
      React.createElement('button', {type:'button', className:'rounded-lg bg-ink text-paper px-5 py-2', onClick:()=>{setSaveId(null);setOpen(true)}}, '打开存档'),
      React.createElement('button', {type:'button', className:'ml-4 px-4 py-2'}, '背景操作')),
    React.createElement(SavesPanel, {open,saveId,onClose,onOpenSave:setSaveId})));
}
createRoot(document.getElementById('root')).render(React.createElement(App));
</script></body></html>`

const server = await createServer({
  configFile: false,
  root: path.join(root, 'frontend'),
  cacheDir: path.join(output, 'vite-cache'),
  plugins: [react(), tailwindcss(), { name: 'isolated-saves-fixture', configureServer(vite) {
    vite.middlewares.use(async (req, res, next) => {
      if (req.url?.startsWith('/api/')) { res.statusCode = 503; res.end('Real API access is forbidden in this fixture'); return }
      if (req.url?.startsWith('/__saves-test')) { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(await vite.transformIndexHtml('/__saves-test', harness)); return }
      next()
    })
  } }],
  server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, open: false, hmr: false, watch: null },
})
await server.listen()
console.log(`ISOLATED_FIXTURE ${base}/__saves-test`)

const manual = { id: 120, created_at: '2026-10-19T10:40:00+08:00', kind: 'manual', actor: 'author', actor_name: '你', title: '开篇定稿 · 雾港的第一封来信', summary: { items: [{ table: 'characters', id: 'hero', op: 'mod', group: '人物', name: '沈九', fields: ['小传'] }] }, count: 3, chapters_final: 4, restored_from: null }
const auto = (id, title, created, actor = 'lorekeeper') => ({ ...manual, id, created_at: created, kind: 'auto', actor, actor_name: actor === 'author' ? '你' : '设定师', title, count: 2, summary: { items: [{ table: 'characters', id: 'hero', op: 'mod', group: '人物', name: '沈九', fields: ['小传'] }] } })
const firstPage = [manual, auto(119, '补上沈九与码头的来历', '2026-10-19T10:32:00+08:00'), auto(118, '调整港口的旧日规则', '2026-10-19T10:22:00+08:00', 'author'), { ...manual, id: 117, title: '回到「人物定稿」之前的样子', kind: 'restore', actor: 'system', actor_name: '系统', restored_from: 92, created_at: '2026-10-19T09:40:00+08:00' }, { ...manual, id: 116, title: '人物关系和故事走向确认 · ' + '这是一段较长的命名用来确认长档名自动换行'.repeat(2), chapters_final: 0, created_at: '2026-10-18T21:10:00+08:00' }]
const secondPage = [{ ...manual, id: 115, title: '更早的第一稿', created_at: '2026-10-17T15:10:00+08:00' }]
const difference = {
  save: manual, now_final: 6, same: false,
  groups: [
    { name: '人物', items: [{ table: 'characters', id: 'hero', op: 'mod', name: '沈九', parts: [{ label: '人物小传', then: '那时的沈九：守着旧码头的普通抄写员。', now: '现在的沈九：发现匿名信中秘密的港口调查者。', then_words: 23, now_words: 25, long: false }] }] },
    { name: '正文', items: [{ table: 'chapters', id: 'chapter-4', op: 'mod', name: '第四章 · 灯下的回信', parts: [{ label: '正文', then: '那时的正文节选：信纸上有一枚蓝色印章。', now: '现在的正文节选：灯光照见了被擦掉的名字。', then_words: 3200, now_words: 3500, long: true }] }] },
  ],
}
let fixture
function reset(mode = 'records') { fixture = { mode, items: mode === 'empty' ? [] : structuredClone(firstPage), listDelay: 0, postDelay: 0, saveCalls: 0, restoreCalls: 0, fullCalls: 0, nextCalls: 0, compareSame: false, failDetail: false, failSave: false, failRestore: false } }
reset()
const installed = process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, executablePath: installed || undefined })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Taipei', locale: 'zh-CN', reducedMotion: 'reduce' })
const page = await context.newPage()
page.on('pageerror', (err) => evidence.pageErrors.push(err.message))
await context.route((url) => url.pathname.startsWith('/api/'), async (route) => {
  const request = route.request(), url = new URL(request.url()), suffix = url.pathname.replace('/api/books/ui-fixture-only/saves', '')
  evidence.requests.push({ method: request.method(), path: url.pathname + url.search })
  const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  if (!url.pathname.startsWith('/api/books/ui-fixture-only/saves')) { evidence.unexpectedRequests.push(request.url()); return route.abort() }
  if (!suffix && request.method() === 'GET') {
    if (fixture.listDelay) await new Promise((resolve) => setTimeout(resolve, fixture.listDelay))
    if (fixture.mode === 'error') return reply({ detail: '模拟网络错误：存档暂时不可用' }, 503)
    if (url.searchParams.has('before')) { fixture.nextCalls++; return reply({ items: secondPage, more: false }) }
    return reply({ items: fixture.items, more: fixture.mode === 'records' })
  }
  if (!suffix && request.method() === 'POST') {
    fixture.saveCalls++
    if (fixture.postDelay) await new Promise((resolve) => setTimeout(resolve, fixture.postDelay))
    if (fixture.failSave) return reply({ detail: '模拟保存失败：请稍后再试' }, 503)
    const saved = { ...manual, id: 130, title: request.postDataJSON().label || '手动存档', created_at: '2026-10-19T11:10:00+08:00' }
    fixture.items.unshift(saved)
    return reply({ save: saved })
  }
  if (/^\/\d+\/restore$/.test(suffix) && request.method() === 'POST') {
    fixture.restoreCalls++
    if (fixture.postDelay) await new Promise((resolve) => setTimeout(resolve, fixture.postDelay))
    if (fixture.failRestore) return reply({ detail: '模拟恢复失败：当前存档暂不能恢复' }, 503)
    return reply({ ok: true })
  }
  if (/^\/\d+\/text$/.test(suffix)) { fixture.fullCalls++; return reply({ then: '完整旧正文。' + '旧码头仍在等待那封信。'.repeat(80), now: '完整新正文。' + '调查者找到了旧日真相。'.repeat(80) }) }
  if (/^\/\d+$/.test(suffix)) {
    if (fixture.failDetail) return reply({ detail: '模拟对照失败：无法读取这一档' }, 503)
    return reply({ ...difference, save: { ...difference.save, title: fixture.longTitle || manual.title }, same: fixture.compareSame, groups: fixture.compareSame ? [] : difference.groups })
  }
  evidence.unexpectedRequests.push(`${request.method()} ${request.url()}`)
  return route.abort()
})

const dialog = page.getByRole('dialog', { name: '存档', exact: true })
const trigger = page.getByRole('button', { name: '打开存档', exact: true })
const open = async (mode = 'records', options = {}) => {
  reset(mode); Object.assign(fixture, options)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`${base}/__saves-test`)
  await trigger.click()
  await expect(dialog).toBeVisible()
}
const shot = async (name) => {
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true })
  evidence.screenshots.push(`${name}.png`)
}
const openDetail = async () => {
  await dialog.getByRole('button', { name: new RegExp(manual.title) }).click()
  await expect(dialog.getByRole('button', { name: '所有存档', exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toBeVisible()
}
const bounds = async () => {
  const b = await dialog.boundingBox(), viewport = page.viewportSize()
  assert(b && b.x >= -1 && b.y >= -1 && b.x + b.width <= viewport.width + 1 && b.y + b.height <= viewport.height + 1, `dialog outside viewport: ${JSON.stringify({b,viewport})}`)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
  assert.equal(overflow, false, 'page must not overflow horizontally')
  return b
}
const assertTabCycle = async (scope, direction = 'Tab') => {
  await page.keyboard.press(direction)
  assert(await scope.evaluate((el) => el.contains(document.activeElement)), `${direction} must cycle inside the modal without reaching background controls or browser chrome`)
}

try {
  await open('empty')
  await expect(dialog.getByText(/还没有存档/)).toBeVisible()
  const emptyBounds = await bounds()
  assert(Math.abs(emptyBounds.x + emptyBounds.width / 2 - 720) < 2)
  assert(Math.abs(emptyBounds.y + emptyBounds.height / 2 - 450) < 2)
  await expect(dialog.getByRole('textbox', { name: '存档名称（选填）', exact: true })).toBeVisible()
  await shot('01-empty-centered')
  check('Empty state, named input, centered dialog', { bounds: emptyBounds })

  await open('error')
  await expect(dialog.getByText('模拟网络错误：存档暂时不可用')).toBeVisible()
  await expect(dialog.getByText(/还没有存档/)).toHaveCount(0)
  await shot('02-list-error')
  check('List error does not masquerade as empty state')

  await open('records', { listDelay: 850 })
  await expect(dialog.getByText(/正在读存档|正在读取/)).toBeVisible()
  await expect(dialog.getByRole('button', { name: new RegExp(manual.title) })).toBeVisible()
  await shot('03-records-desktop')
  const autoFold = dialog.getByRole('button').filter({ hasText: /2 档/ }).first()
  await expect(autoFold).toBeVisible()
  await expect(dialog.getByText('补上沈九与码头的来历', { exact: true })).toHaveCount(0)
  await autoFold.click()
  await expect(dialog.getByText('补上沈九与码头的来历', { exact: true })).toBeVisible()
  await autoFold.click()
  await expect(dialog.getByText('补上沈九与码头的来历', { exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: /^手动存档/ }).click()
  await expect(dialog.getByText('回到「人物定稿」之前的样子', { exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: new RegExp(manual.title) })).toBeVisible()
  await dialog.getByRole('button', { name: /^全部存档/ }).click()
  await expect(dialog.getByText('回到「人物定稿」之前的样子', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: /更早/ }).click()
  await expect(dialog.getByText('更早的第一稿', { exact: true })).toBeVisible()
  assert.equal(fixture.nextCalls, 1)
  check('Loading, automatic folding, manual/all filter, pagination')

  await open('records', { postDelay: 900 })
  const name = dialog.getByRole('textbox', { name: '存档名称（选填）', exact: true })
  await name.fill('  本次手动定稿  ')
  await name.press('Enter')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await expect(dialog.getByRole('button', { name: /存一档|正在保存|存档中/ })).toBeDisabled()
  await expect(dialog.getByText('本次手动定稿', { exact: true })).toBeVisible()
  await expect(name).toHaveValue('')
  assert.equal(fixture.saveCalls, 1)
  await shot('04-save-success')
  check('Trimmed manual save succeeds; repeated Enter sends one POST')

  await open('records', { failSave: true })
  await dialog.getByRole('textbox', { name: '存档名称（选填）', exact: true }).fill('失败时保留的名字')
  await dialog.getByRole('button', { name: '存一档', exact: true }).click()
  await expect(dialog.getByText('模拟保存失败：请稍后再试')).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: '存档名称（选填）', exact: true })).toHaveValue('失败时保留的名字')
  check('Failed save preserves the entered title and displays the API error')

  await open()
  await openDetail()
  await dialog.getByRole('button', { name: /沈九/ }).click()
  const oldText = dialog.getByText('那时的沈九：守着旧码头的普通抄写员。', { exact: true })
  const newText = dialog.getByText('现在的沈九：发现匿名信中秘密的港口调查者。', { exact: true })
  await expect(oldText).toBeVisible(); await expect(newText).toBeVisible()
  const oldBox = await oldText.boundingBox(), newBox = await newText.boundingBox()
  assert(oldBox.x < newBox.x && Math.abs(oldBox.y - newBox.y) < 3, 'desktop comparison should place old/new text side by side')
  await dialog.getByRole('button', { name: /第四章/ }).click()
  await dialog.getByRole('button', { name: '看全文', exact: true }).click()
  await expect(dialog.getByText(/^完整旧正文/)).toBeVisible()
  assert.equal(fixture.fullCalls, 1)
  await shot('05-comparison-side-by-side')
  check('Detail comparison has desktop side-by-side columns and loads full text')

  for (const status of ['queued', 'running', 'waiting_author']) {
    await page.evaluate((status) => window.savesTest.setJob({ id: 'mock-job', status }), status)
    await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toBeDisabled()
  }
  await page.evaluate(() => window.savesTest.setJob(null))
  await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toBeEnabled()
  check('Restore disabled for queued/running/waiting_author jobs')

  await dialog.getByRole('button', { name: '回到这一档', exact: true }).click()
  const confirm = page.getByRole('alertdialog')
  await expect(confirm).toBeVisible()
  await expect(confirm.getByText(/正文会退到第 4 章/)).toBeVisible()
  await expect(confirm.getByText(/现在的样子会先存一档/)).toBeVisible()
  const confirmBounds = await confirm.boundingBox()
  assert(confirmBounds.height < 500, 'ordinary confirmation should size to its content rather than leave a tall blank panel')
  await expect(confirm.getByRole('button', { name: '先不了', exact: true })).toBeFocused()
  await confirm.getByRole('button', { name: '回到这一档', exact: true }).focus()
  await assertTabCycle(confirm)
  await page.evaluate(() => window.savesTest.setJob({ id: 'mock-late-job', status: 'running' }))
  await expect(confirm.getByRole('button', { name: '回到这一档', exact: true })).toBeDisabled()
  await page.evaluate(() => window.savesTest.setJob(null))
  await shot('06-restore-confirmation')
  await confirm.getByRole('button', { name: '先不了', exact: true }).click()
  await expect(confirm).toHaveCount(0)
  assert.equal(fixture.restoreCalls, 0)
  await dialog.getByRole('button', { name: '回到这一档', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(confirm).toHaveCount(0); await expect(dialog).toBeVisible()
  assert.equal(fixture.restoreCalls, 0)
  check('Restore confirmation states chapter rollback and protective save; Cancel/Escape never restore')

  await dialog.getByRole('button', { name: '回到这一档', exact: true }).click()
  await confirm.getByRole('button', { name: '回到这一档', exact: true }).click()
  await expect(dialog.getByText(/书已经换回这一档了/)).toBeVisible()
  assert.equal(fixture.restoreCalls, 1)
  await dialog.getByRole('button', { name: '所有存档', exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: '存档名称（选填）', exact: true })).toBeVisible()
  check('Confirmed restore sends one request and returns to list')

  const focusables = dialog.locator('button:not([disabled]),input:not([disabled]),[tabindex="0"]')
  await focusables.last().focus()
  await assertTabCycle(dialog)
  await focusables.first().focus()
  await assertTabCycle(dialog, 'Shift+Tab')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  check('Modal Tab/Shift+Tab cannot reach background controls; Escape restores trigger focus')

  await open('records', { compareSame: true })
  await dialog.getByRole('button', { name: new RegExp(manual.title) }).click()
  await expect(dialog.getByText(/一模一样/)).toBeVisible()
  await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toHaveCount(0)
  check('Identical checkpoint does not offer an unnecessary restore')

  await open('records', { failDetail: true })
  await dialog.getByRole('button', { name: new RegExp(manual.title) }).click()
  await expect(dialog.getByText('模拟对照失败：无法读取这一档')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toHaveCount(0)
  check('Failed detail load shows error without exposing restore')

  await open('records', { failRestore: true })
  await openDetail()
  await dialog.getByRole('button', { name: '回到这一档', exact: true }).click()
  await confirm.getByRole('button', { name: '回到这一档', exact: true }).click()
  await expect(confirm.getByText('模拟恢复失败：当前存档暂不能恢复')).toBeVisible()
  await expect(confirm.getByRole('button', { name: '回到这一档', exact: true })).toBeEnabled()
  await confirm.getByRole('button', { name: '先不了', exact: true }).click()
  await expect(dialog.getByText(/书已经换回这一档了/)).toHaveCount(0)
  check('Failed restore remains in confirmation with retry/cancel and no false success')

  await open('records', { longTitle: '极长的存档标题'.repeat(80) })
  await page.setViewportSize({ width: 390, height: 844 })
  await openDetail()
  await bounds()
  await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toBeInViewport()
  await dialog.getByRole('button', { name: '回到这一档', exact: true }).click()
  await expect(confirm.getByRole('button', { name: '先不了', exact: true })).toBeInViewport()
  await expect(confirm.getByRole('button', { name: '回到这一档', exact: true })).toBeInViewport()
  await shot('11-long-title-mobile-confirmation')
  await page.evaluate(() => window.savesTest.setOpen(false))
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(dialog).toHaveCount(0)
  assert.equal(await page.evaluate(() => document.body.style.overflow), '')
  check('Over-500-character title at 390px keeps restore/cancel reachable; unmounting both modals restores body scrolling')

  await open()
  await page.setViewportSize({ width: 390, height: 844 })
  await bounds()
  await shot('07-mobile-list')
  await openDetail()
  await dialog.getByRole('button', { name: /沈九/ }).click()
  const mobileOld = await oldText.boundingBox(), mobileNew = await newText.boundingBox()
  assert(Math.abs(mobileOld.x - mobileNew.x) < 3 && mobileOld.y < mobileNew.y, 'mobile comparison must stack vertically')
  await bounds()
  await shot('08-mobile-comparison')
  check('390px narrow layout stays in viewport and stacks comparison columns')

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.evaluate(() => { document.documentElement.dataset.theme = 'ink' })
  await bounds()
  await shot('09-dark-comparison')
  check('Ink theme comparison remains visible and in bounds')

  await page.evaluate(() => { delete document.documentElement.dataset.theme })
  await page.setViewportSize({ width: 720, height: 450 })
  await bounds()
  await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toBeVisible()
  await shot('10-200percent-equivalent-layout')
  check('200% zoom-equivalent CSS viewport (720x450 from 1440x900) keeps actions reachable')

  await page.setViewportSize({ width: 2000, height: 1100 })
  await page.evaluate(() => { document.documentElement.style.setProperty('--desk-zoom', '1.1'); document.documentElement.style.setProperty('--desk-scale', '1.4') })
  await bounds()
  await expect(dialog.getByRole('button', { name: '回到这一档', exact: true })).toBeInViewport()
  await shot('12-large-workspace-scale')
  check('Workspace zoom 1.1 x scale 1.4 stays in viewport with reachable actions')

  assert.deepEqual(evidence.pageErrors, [])
  assert.deepEqual(evidence.unexpectedRequests, [])
  assert.deepEqual(await fingerprint(), evidence.sourceSha256, 'production source changed while acceptance was running; rerun the stable revision')
  check('No page errors; no unexpected API requests; no live backend access')
  evidence.ok = true
  await fs.unlink(path.join(output, 'FAILED-state.png')).catch(() => {})
} catch (error) {
  evidence.ok = false
  evidence.error = error.stack || String(error)
  await shot('FAILED-state').catch(() => {})
  throw error
} finally {
  evidence.finishedAt = new Date().toISOString()
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(evidence, null, 2) + '\n')
  await browser.close()
  await server.close()
}
