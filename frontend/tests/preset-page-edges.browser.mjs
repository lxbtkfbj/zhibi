/** Private real-router UI edge regression. All API endpoints are mocked and server-side API access fails closed. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const output = path.resolve(process.env.PRESET_EDGES_OUTPUT ?? path.join(root, 'data/preset-task2/edges'))
const port = Number(process.env.PRESET_EDGES_PORT ?? 4387)
assert.ok(Number.isInteger(port) && port > 1024 && ![8000, 4320].includes(port), 'Only a private non-daily port is allowed')
const base = `http://127.0.0.1:${port}`
await fs.mkdir(output, { recursive: true })
const evidence = { isolation: 'Private real-router Vite, no proxy; all API fixtures in memory; backend and models inaccessible.', checks: [], requests: [], writes: [], unexpectedRequests: [], pageErrors: [] }
const check = name => { evidence.checks.push(name); console.log(`PASS ${name}`) }
const server = await createServer({
  configFile: false, root: path.join(root, 'frontend'), cacheDir: path.join(output, 'vite-cache'),
  plugins: [react(), tailwindcss(), { name: 'fail-closed-api', configureServer(vite) { vite.middlewares.use((req, res, next) => { if (req.url?.startsWith('/api/')) { res.statusCode = 503; res.end('Live API forbidden'); return } next() }) } }],
  server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, hmr: false, watch: null, open: false },
})
await server.listen()
let browser
let delayedBase = null
let releaseHeldBase
const system1 = JSON.parse(await fs.readFile(path.join(root, 'backend/app/presets/chief_group/v1/preset.json'), 'utf8'))
system1.source = 'system'
for (const block of system1.blocks) {
  block.content = (await fs.readFile(path.join(root, `backend/app/presets/chief_group/v1/${block.id}.md`), 'utf8')).replace(/[\r\n]+$/, '')
  block.history = [{ version: 1, date: system1.date, change: block.origin ?? '' }]
}
const system2 = structuredClone(system1)
system2.version = 2; system2.date = '2026-11-01'; system2.note = '只存在内存里的系统新版，用于历史版号测试。'
system2.blocks.find(block => block.id === 'voice').content = '第二版口吻，只存在内存。'
system2.blocks.find(block => block.id === 'voice').history.push({ version: 2, date: system2.date, change: '独立测试修改口吻。' })
system2.blocks.push({ id: 'system_future', title: '系统新版多的块', role: 'system', enabled: true, required: false, when: 'always', content: '仅系统第二版有这一块。', origin: '独立测试的新增块来历。', without: '', history: [{ version: 2, date: system2.date, change: '独立测试的新增块来历。' }] })
const editableFields = blocks => blocks.map(({ id, title, role, enabled, required, when, content }) => ({ id, title, role, enabled, required, when, content }))
let mine = { id: 'mine-alive', source: 'mine', kind: 'chief_group', name: '仍存在的作者预设', based_on: { source: 'system', version: 1 }, blocks: editableFields(system1.blocks), saved: 2, created_at: '2026-10-27T01:00:00Z', updated_at: '2026-10-27T02:00:00Z', issues: [], system_newer: { version: 2, date: system2.date, note: system2.note } }
const copies = []
let active = { source: 'system' }
const book = { id: 'mockbook', title: '隔离测试书', source: 'new', genre: '悬疑', status: 'ready', idea: '', logline: '', job_status: null, created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z', style_reference: '', concept: { title: '隔离测试书', story: '', genre: '悬疑', channel: '男频', tags: [], target_length: 30 }, protagonist: {}, world: {}, spine: {}, setup_progress: {}, requirements: [], trial_read_done: true, active_job: null, chapters_final: 0, words_final: 0, chapter_words: 2500, card_layouts: {} }
const conditions = [{ when: 'always', label: '每次都发' }, { when: 'can_act', label: '能动手时' }, { when: 'ask_only', label: '只问不改时' }, { when: 'skills', label: '有手册时' }, { when: 'teardowns', label: '有拆过的书时' }, { when: 'web', label: '配了联网时' }]
const placeholders = ['资料说明', '简介', '设定库', '大纲', '写到哪了', '正在看的那一页', '等你确认的', '编辑部正在干活', '记忆', '之前聊过', '聊天记录', '选中的原文', '上次做到一半', '作者这次说的'].map(name => ({ name, description: '独立测试说明', preview: '独立测试预览' }))
const rows = [
  { id: 601, purpose: '系统第一版的历史调用', preset: { kind: 'chief_group', source: 'system', name: system1.name, version: 1, blocks: ['role', 'voice', 'note'].map(id => { const block = system1.blocks.find(item => item.id === id); return { id, title: block.title, role: block.role } }) } },
  { id: 602, purpose: '存在的作者预设调用', preset: { kind: 'chief_group', source: 'mine', id: mine.id, name: mine.name, version: 1, blocks: ['voice', 'note'].map(id => { const block = system1.blocks.find(item => item.id === id); return { id, title: block.title, role: block.role } }) } },
  { id: 603, purpose: '已经删除的作者预设调用', preset: { kind: 'chief_group', source: 'mine', id: 'mine-deleted', name: '删除前的预设名', version: 3, blocks: [{ id: 'voice', title: '历史口吻', role: 'system' }] } },
  { id: 604, purpose: '预设读取故障的调用', preset: { kind: 'chief_group', source: 'mine', id: 'mine-unavailable', name: '暂时读不到的预设', version: 2, blocks: [{ id: 'voice', title: '故障时的历史口吻', role: 'system' }] } },
].map(row => ({ book_id: book.id, book_title: book.title, role: 'chief', model: 'demo', profile_name: '全内存演示', prompt_tokens: 20, completion_tokens: 10, latency_ms: 10, ok: true, error: null, created_at: '2026-10-27T03:00:00Z', ...row }))
const summary = item => ({ ...item, block_count: item.blocks.length, enabled_count: item.blocks.filter(block => block.enabled).length, blocks: undefined, issues: undefined, system_newer: undefined })
const list = () => ({ kinds: [{ kind: 'chief_group', label: '主编群聊' }], kind: 'chief_group', active, system: system2, versions: [system1, system2].map(({ blocks: _blocks, ...version }) => version), mine: [mine, ...copies].map(summary) })
const returnTo = '/desk/mockbook?tab=outline#chapter-2'
const callsUrl = `${base}/prompts?${new URLSearchParams({ tab: 'calls', returnTo })}`
const mineUrl = `${base}/presets?${new URLSearchParams({ source: 'mine', id: mine.id, block: 'voice', returnTo })}`
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM ?? process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN', reducedMotion: 'reduce' })
  await context.addInitScript(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', reducedMotion: true })))
  const page = await context.newPage()
  page.setDefaultTimeout(7000)
  page.on('pageerror', error => evidence.pageErrors.push(error.message))
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname.slice(4), method = request.method()
    if (url.protocol.startsWith('http') && url.origin !== base) { evidence.unexpectedRequests.push(request.url()); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    evidence.requests.push(`${method} ${p}${url.search}`)
    const reply = (json, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(json) })
    if (method !== 'GET') evidence.writes.push({ method, path: p, body: request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : '[multipart fixture]' })
    if (p === '/llm-calls') return reply({ items: rows, next_before: null })
    if (/^\/llm-calls\/\d+$/.test(p)) {
      const row = rows.find(item => item.id === Number(p.split('/').at(-1)))
      return reply({ ...row, used_prompts: { parts: null, names: [] }, request: { system: '独立系统提示', user: '独立用户提示', schema: null, schema_name: null, method: 'demo', preset: row.preset }, response: '独立演示回复' })
    }
    if (p === '/presets' && method === 'GET') return reply(list())
    if (p === '/presets/system/chief_group') {
      if (url.searchParams.get('version') === '1' && delayedBase) { const gate = delayedBase; delayedBase = null; gate.started(); await gate.wait }
      return reply(url.searchParams.get('version') === '1' ? system1 : system2)
    }
    if (p === '/presets/import' && method === 'POST') return reply({ detail: '独立测试：预设文件格式不对' }, 400)
    if (p === '/presets/conditions') return reply(conditions)
    if (p === '/presets/placeholders') {
      if (url.searchParams.get('book_id') === 'teardownbook') return reply({ detail: '主编群聊预设只用于作者自己的书，拆的书照旧用原来的提示词' }, 422)
      return reply(url.searchParams.has('book_id') ? placeholders : placeholders.map(({ preview: _preview, ...placeholder }) => placeholder))
    }
    if (p === '/presets/mine' && method === 'POST') {
      const input = request.postDataJSON()
      const original = input.source === 'mine' ? [mine, ...copies].find(item => item.id === input.id) : input.version === 1 ? system1 : system2
      const created = { id: `mine-copy-${copies.length + 1}`, source: 'mine', kind: 'chief_group', name: `我的主编群聊 ${copies.length + 1}`, based_on: input.source === 'mine' ? { source: 'mine', id: original.id, saved: original.saved, system_version: original.based_on.version } : { source: 'system', version: original.version }, blocks: editableFields(original.blocks), saved: 1, created_at: '2026-10-27T04:00:00Z', updated_at: '2026-10-27T04:00:00Z', issues: [] }
      copies.push(created)
      return reply(created, 201)
    }
    if (p === '/presets/mine/mine-deleted') return reply({ detail: '这份预设不存在' }, 404)
    if (p === '/presets/mine/mine-unavailable') return reply({ detail: '独立测试模拟读取故障' }, 503)
    if (p === '/presets/mine/mine-alive') {
      if (method === 'GET') return reply(mine)
      if (method === 'PUT') {
        const input = request.postDataJSON()
        mine = { ...mine, name: input.name, blocks: input.blocks.map((block, index) => ({ ...block, id: block.id.startsWith('temporary_') ? `custom_server_${index}` : block.id })), saved: mine.saved + 1 }
        return reply(mine)
      }
    }
    if (method === 'GET' && p.startsWith('/presets/mine/mine-copy-')) return reply(copies.find(item => item.id === p.split('/').at(-1)))
    if (p === '/presets/active' && method === 'PUT') { const input = request.postDataJSON(); active = input.source === 'mine' ? { source: 'mine', id: input.id } : { source: 'system' }; return reply({ kind: 'chief_group', ...active, issues: [] }) }
    if (p === '/books') return reply([book])
    if (p === '/books/mockbook') return reply(book)
    if (p === '/books/mockbook/events') return route.fulfill({ status: 204 })
    if (p === '/books/mockbook/library') return reply({ categories: [], characters: [], entries: [], suggestions_pending: 0 })
    if (p === '/books/mockbook/outline-tree') return reply({ arcs: [], ending: null, segmented: false })
    if (p === '/books/mockbook/outline') return reply({ volumes: [] })
    if (p === '/books/mockbook/bible') return reply({ characters: [], world_entries: [], foreshadowings: [], relationships: [] })
    if (p === '/books/mockbook/settings') return reply({ settings: { setup_mode: 'puzzle', title_style: 'chief', title_custom: '', person: 'third', intimacy: 'fade', intimacy_custom: '', chapter_words: 2500, other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 3, review_strictness: 'standard', volume_audit: true, volume_approval: true, chapters_approval: false, segment_approval: true, trial_read: true }, rules_text: '' })
    if (p === '/books/mockbook/saves') return reply({ items: [], more: false })
    if (['/books/mockbook/chapters', '/books/mockbook/suggestions', '/books/mockbook/requirements', '/books/mockbook/chat/conversations', '/books/mockbook/threads', '/books/mockbook/nodes', '/books/mockbook/secrets'].includes(p)) return reply([])
    if (p === '/glossary') return reply({ terms: [] })
    if (p === '/llm/profiles') return reply([])
    if (p === '/llm/roles') return reply({})
    if (p === '/llm/web-search') return reply({ has_key: false })
    if (p === '/health') return reply({ status: 'ok', components: {} })
    evidence.unexpectedRequests.push(`${method} ${p}`)
    return reply({ detail: `Unmocked API forbidden: ${method} ${p}` }, 503)
  })
  const popup = () => page.getByRole('dialog', { name: '这份改了还没保存。', exact: true })
  const button = name => page.getByRole('button', { name, exact: true })
  const openCall = async purpose => { await page.goto(callsUrl); await page.getByRole('row').filter({ hasText: purpose }).getByRole('button', { name: '查看', exact: true }).click(); await expect(page.getByTestId('call-used-preset')).toBeVisible() }
  const selectMine = async () => { await button(`选择预设：${mine.name}`).click(); await expect(page.getByLabel('预设块内容', { exact: true })).toBeEditable() }
  const fillVoice = async content => { await page.locator('[data-block-id="voice"] .preset-block-select').click(); await page.getByLabel('预设块内容', { exact: true }).fill(content) }

  await openCall('已经删除的作者预设调用')
  const deleted = page.getByTestId('call-used-preset')
  await expect(deleted).toContainText('删除前的预设名（已经删了） · 我的 · 第 3 次保存')
  await expect(deleted.getByRole('link')).toHaveCount(0)
  await expect(deleted).toContainText('历史口吻')
  check('删除的作者预设仅显示历史名称与实际发送块，不提供可点击入口')

  await openCall('预设读取故障的调用')
  await expect(page.getByTestId('call-used-preset')).toContainText('独立测试模拟读取故障')
  await expect(page.getByText('（已经删了）', { exact: false })).toHaveCount(0)
  check('预设读取故障不会误报已经删除')

  await openCall('系统第一版的历史调用')
  await page.getByTestId('call-used-preset').getByRole('link', { name: '口吻：老主编', exact: true }).click()
  await expect(page).toHaveURL(/\/presets\?/)
  let current = new URL(page.url())
  assert.equal(current.pathname, '/presets'); assert.equal(current.searchParams.get('version'), '1'); assert.equal(current.searchParams.get('block'), 'voice'); assert.equal(current.searchParams.get('returnTo'), returnTo)
  await expect(page.getByLabel('预设块内容', { exact: true })).toHaveValue(system1.blocks.find(block => block.id === 'voice').content)
  await expect(page.locator('.preset-selected-description .preset-active')).toHaveCount(0)
  check('系统历史调用定位记录的版号与块，保留原书路径，旧版不误标正在用')

  await openCall('存在的作者预设调用')
  await page.getByTestId('call-used-preset').getByRole('link', { name: '口吻：老主编', exact: true }).click()
  await expect(page).toHaveURL(/\/presets\?/)
  await expect(page.getByLabel('预设块标题', { exact: true })).toHaveValue('口吻：老主编')
  current = new URL(page.url()); assert.equal(current.searchParams.get('id'), mine.id); assert.equal(current.searchParams.get('block'), 'voice'); assert.equal(current.searchParams.get('version'), null); assert.equal(current.searchParams.get('returnTo'), returnTo)
  check('存在的作者预设调用定位当前那份及实际发送块')

  await page.locator('.preset-origin summary').click()
  await expect(page.locator('.preset-origin')).toContainText('从系统预设第 1 版复制')
  await expect(page.locator('.preset-origin')).toContainText(system1.blocks.find(block => block.id === 'voice').origin)
  await page.locator('[data-block-id="role"] .preset-block-select').click()
  await expect(page.locator('.preset-required-note')).toHaveText(`必须的块。关了它：${system1.blocks.find(block => block.id === 'role').without}`)
  check('作者块缺metadata时按系统ID恢复必须块说明与对应系统版来历')

  await fillVoice('再看看保留的未保存口吻')
  await button(`选择预设：${system2.name}`).click()
  await expect(popup()).toBeVisible(); await popup().getByRole('button', { name: '再看看', exact: true }).click()
  await expect(page.getByLabel('预设块内容', { exact: true })).toHaveValue('再看看保留的未保存口吻')
  assert.equal(new URL(page.url()).searchParams.get('id'), mine.id)
  check('同页换预设：再看看留在当前稿且不丢修改')

  await button(`选择预设：${system2.name}`).click()
  await popup().getByRole('button', { name: '不保存', exact: true }).click()
  await expect(page.locator('.preset-selected-description p')).toContainText('系统预设 · 第 2 版')
  await selectMine(); await fillVoice('换预设前保存的口吻')
  await button(`选择预设：${system2.name}`).click()
  await popup().getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.preset-selected-description p')).toContainText('系统预设 · 第 2 版')
  assert.equal(mine.blocks.find(block => block.id === 'voice').content, '换预设前保存的口吻')
  check('同页换预设：不保存与保存都正确到原先选中的目标，保存不覆盖目标导航')

  await selectMine(); await fillVoice('设为正在用前保存的口吻')
  const beforeWrites = evidence.writes.length
  await button('设为正在用').click(); await expect(popup()).toBeVisible()
  await popup().getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.preset-selected-description .preset-active')).toHaveText('正在用')
  assert.deepEqual(evidence.writes.slice(beforeWrites).map(write => write.path), ['/presets/mine/mine-alive', '/presets/active'])
  check('设为正在用前先保存，再调用活动项接口')

  await fillVoice('SPA返回前保存的口吻')
  await page.getByRole('link', { name: '返回当前书', exact: true }).click()
  await popup().getByRole('button', { name: '保存', exact: true }).click()
  await expect(page).toHaveURL(base + returnTo)
  assert.equal(mine.blocks.find(block => block.id === 'voice').content, 'SPA返回前保存的口吻')
  check('SPA返回当前书：保存之后到原来的完整URL，不被保存时块定位覆盖')

  await page.goto(mineUrl)
  await expect(page.getByLabel('预设块内容', { exact: true })).toBeEditable()
  await button(`选择预设：${system2.name}`).click(); await selectMine()
  await fillVoice('浏览器后退前保存的口吻')
  await page.goBack({ waitUntil: 'domcontentloaded' })
  await expect(popup()).toBeVisible()
  await popup().getByRole('button', { name: '再看看', exact: true }).click()
  await expect(page.getByLabel('预设块内容', { exact: true })).toHaveValue('浏览器后退前保存的口吻')
  await page.goBack({ waitUntil: 'domcontentloaded' })
  await popup().getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.preset-selected-description p')).toContainText('系统预设 · 第 2 版')
  assert.equal(mine.blocks.find(block => block.id === 'voice').content, '浏览器后退前保存的口吻')
  check('浏览器后退：再看看与保存正确保留稿件或完成原后退目标')

  await selectMine(); await fillVoice('SPA返回不保存的口吻')
  await page.getByRole('link', { name: '返回当前书', exact: true }).click()
  await popup().getByRole('button', { name: '再看看', exact: true }).click()
  await expect(page.getByLabel('预设块内容', { exact: true })).toHaveValue('SPA返回不保存的口吻')
  await page.getByRole('link', { name: '返回当前书', exact: true }).click()
  await popup().getByRole('button', { name: '不保存', exact: true }).click()
  await expect(page).toHaveURL(base + returnTo)
  assert.equal(mine.blocks.find(block => block.id === 'voice').content, '浏览器后退前保存的口吻')
  check('SPA返回当前书：再看看保留修改，不保存离开但不写后台')

  await page.goto(mineUrl)
  await expect(page.getByLabel('预设块内容', { exact: true })).toBeEditable()
  await button(`选择预设：${system2.name}`).click(); await selectMine()
  await fillVoice('浏览器后退不保存的口吻')
  await page.goBack({ waitUntil: 'domcontentloaded' })
  await popup().getByRole('button', { name: '不保存', exact: true }).click()
  await expect(page.locator('.preset-selected-description p')).toContainText('系统预设 · 第 2 版')
  assert.equal(mine.blocks.find(block => block.id === 'voice').content, '浏览器后退前保存的口吻')
  check('浏览器后退：不保存完成原目标且后台仍保留旧稿')

  await selectMine()
  await button('添加预设块').click()
  const temporary = new URL(page.url()).searchParams.get('block')
  assert.ok(temporary.startsWith('temporary_'))
  await page.getByLabel('预设块内容', { exact: true }).fill('保存后还选中这一块')
  await button('保存').click()
  await expect(button('放弃修改')).toHaveCount(0)
  const assigned = new URL(page.url()).searchParams.get('block')
  assert.ok(assigned.startsWith('custom_server_'))
  await expect(page.getByLabel('预设块标题', { exact: true })).toHaveValue('新的块')
  await expect(page.getByLabel('预设块内容', { exact: true })).toHaveValue('保存后还选中这一块')
  assert.equal(mine.blocks.find(block => block.id === assigned).content, '保存后还选中这一块')
  check('保存新块采用后台重新发的ID并保持这块选中')

  await button('比一比').click()
  const comparison = page.getByRole('dialog', { name: '比一比', exact: true })
  await expect(comparison).toContainText('系统新版多的块')
  await expect(comparison).toContainText('新的块')
  await expect(comparison).toContainText('另外 18 块一样')
  await comparison.locator('.preset-full-comparison > details').filter({ has: page.locator('summary', { hasText: /^口吻：老主编$/ }) }).locator('summary').click()
  await expect(comparison.locator('.preset-comparison section').nth(0).locator('pre')).toHaveText('第二版口吻，只存在内存。')
  await expect(comparison.locator('.preset-comparison section').nth(1).locator('pre')).toHaveText(mine.blocks.find(block => block.id === 'voice').content)
  await comparison.getByRole('button', { name: '关闭', exact: true }).click()
  check('系统新版比对显示新版独有、作者独有、改变全文与相同块计数')

  await page.locator('[data-block-id="voice"] .preset-block-select').click()
  await page.locator('.preset-origin summary').click()
  const origin = page.locator('.preset-origin')
  await expect(origin).toContainText('从系统预设第 1 版复制，后来改过')
  await expect(origin.locator('article')).toHaveCount(2)
  await expect(origin).toContainText('第 1 版 · 10-27')
  await expect(origin).toContainText('第 2 版 · 11-01')
  await origin.getByRole('button', { name: '跟系统的比一比', exact: true }).click()
  const copiedComparison = page.getByRole('dialog', { name: '比一比', exact: true })
  await expect(copiedComparison.locator('.preset-comparison section').nth(0)).toContainText('系统预设 · 第 1 版')
  await expect(copiedComparison.locator('.preset-comparison section').nth(0).locator('pre')).toHaveText(system1.blocks.find(block => block.id === 'voice').content)
  await copiedComparison.getByRole('button', { name: '关闭', exact: true }).click()
  await origin.locator('article').nth(1).getByRole('button', { name: '看这一版', exact: true }).click()
  const historical = page.getByRole('dialog', { name: '第 2 版 · 口吻：老主编', exact: true })
  await expect(historical.locator('pre')).toHaveText('第二版口吻，只存在内存。')
  await historical.getByRole('button', { name: '关闭', exact: true }).click()
  check('来历展示系统后续历史，作者修改比对仍钉在复制的第1版，历史全文按所选版读取')

  const unchangedOriginal = structuredClone(mine)
  await button('复制新版').click()
  await expect(page.locator('.preset-name h2')).toHaveText('我的主编群聊 1')
  assert.equal(copies.length, 1)
  assert.deepEqual(copies[0].blocks, editableFields(system2.blocks))
  assert.deepEqual(copies[0].based_on, { source: 'system', version: 2 })
  assert.deepEqual(mine, unchangedOriginal)
  assert.equal(new URL(page.url()).searchParams.get('id'), copies[0].id)
  check('复制新版从最新系统创建并打开新副本，原作者预设逐字段不变')

  const beforeTeardown = evidence.requests.length
  await page.goto(`${base}/presets?${new URLSearchParams({ returnTo: '/desk/teardownbook?tab=essence' })}`)
  await expect(page.getByRole('heading', { name: '预设管理', exact: true })).toBeVisible()
  await expect(page.locator('.preset-placeholders > div')).toHaveCount(14)
  await expect(page.locator('.preset-placeholder-preview')).toHaveCount(0)
  assert.ok(evidence.requests.slice(beforeTeardown).some(request => request.includes('/presets/placeholders?kind=chief_group&book_id=teardownbook')))
  assert.ok(evidence.requests.slice(beforeTeardown).some(request => request === 'GET /presets/placeholders?kind=chief_group'))
  await expect(page.getByText('主编群聊预设只用于作者自己的书，拆的书照旧用原来的提示词', { exact: true })).toHaveCount(0)
  check('拆书占位符422降级为无书说明，保留14项且不显示现在预览或报错')

  mine = { ...mine, blocks: mine.blocks.map(block => block.id === 'voice' ? { ...block, content: system1.blocks.find(item => item.id === 'voice').content } : block) }
  let baseStarted
  const started = new Promise(resolve => { baseStarted = resolve })
  delayedBase = { started: baseStarted, wait: new Promise(resolve => { releaseHeldBase = resolve }) }
  await page.goto(mineUrl)
  await expect(page.getByLabel('预设块标题', { exact: true })).toHaveValue('口吻：老主编')
  await started
  await page.locator('.preset-origin summary').click()
  const delayedOrigin = page.locator('.preset-origin')
  await expect(delayedOrigin).not.toContainText('后来改过')
  const pendingCompare = delayedOrigin.getByRole('button', { name: '跟系统的比一比', exact: true })
  assert.equal(await pendingCompare.evaluateAll(items => items.some(item => !item.disabled)), false, '基版未到前不能用新版正文代替旧版进行比对')
  const baseDelivered = page.waitForResponse(response => new URL(response.url()).pathname === '/api/presets/system/chief_group' && new URL(response.url()).searchParams.get('version') === '1')
  releaseHeldBase(); releaseHeldBase = undefined
  await baseDelivered
  await expect(delayedOrigin).not.toContainText('后来改过')
  await fillVoice('基版迟到后才修改的口吻')
  await expect(delayedOrigin).toContainText('后来改过')
  await delayedOrigin.getByRole('button', { name: '跟系统的比一比', exact: true }).click()
  const afterDelay = page.getByRole('dialog', { name: '比一比', exact: true })
  await expect(afterDelay.locator('.preset-comparison section').nth(0)).toContainText('系统预设 · 第 1 版')
  await expect(afterDelay.locator('.preset-comparison section').nth(0).locator('pre')).toHaveText(system1.blocks.find(block => block.id === 'voice').content)
  await expect(afterDelay.locator('.preset-comparison section').nth(1).locator('pre')).toHaveText('基版迟到后才修改的口吻')
  await afterDelay.getByRole('button', { name: '关闭', exact: true }).click()
  await button('放弃修改').click()
  check('复制基版延迟到达时不误标后来改过或借新版比对，响应后准确显示第1版全文')

  await page.setViewportSize({ width: 1100, height: 800 })
  const compact = page.locator('.preset-compact-library')
  await expect(compact).toBeVisible()
  const choosingFile = page.waitForEvent('filechooser')
  await compact.getByRole('button', { name: '导入预设', exact: true }).click()
  await (await choosingFile).setFiles({ name: '坏预设.json', mimeType: 'application/json', buffer: Buffer.from('{}') })
  const importError = compact.locator('.preset-import-error')
  await expect(importError).toHaveText('独立测试：预设文件格式不对')
  const errorBox = await importError.boundingBox(), importBox = await compact.getByRole('button', { name: '导入预设', exact: true }).boundingBox()
  assert.ok(errorBox && importBox && errorBox.y + errorBox.height <= importBox.y + 1, '1100宽导入错误必须摆在导入按钮上面')
  check('1100宽导入失败原样显示后台原因，错误行位于导入按钮上面')
  assert.deepEqual(evidence.unexpectedRequests, [])
  assert.deepEqual(evidence.pageErrors, [])
  check('无页面错误、意外API或外部请求')
} catch (error) {
  evidence.failure = error.stack
  console.error(error)
  throw error
} finally {
  releaseHeldBase?.()
  evidence.completedAt = new Date().toISOString()
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  await browser?.close()
  await server.close()
}
