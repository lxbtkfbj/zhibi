/** Real-app prompt workspace acceptance with complete in-memory API fixtures.
 * Run: ZHIBI_CHROMIUM=<installed Chromium> node tests/prompts-workspace.browser.mjs
 * No production backend, author book, global prompt, or service port is accessed.
 * The private Vite server, optimizer cache and screenshots live under data/prompts-workspace.
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
const output = path.join(root, 'data/prompts-workspace')
const base = `http://127.0.0.1:${Number(process.env.PROMPTS_TEST_PORT || 4377)}`
await fs.mkdir(output, { recursive: true })
const fingerprint = async () => Object.fromEntries(await Promise.all(['frontend/src/pages/PromptsPage.tsx', 'frontend/src/pages/PromptCallDetail.tsx', 'frontend/src/pages/prompts.css', 'frontend/src/pages/SettingsPage.tsx', 'frontend/src/lib/promptNavigation.ts', 'frontend/src/pages/workspace/Workspace.tsx', 'frontend/src/main.tsx'].map(async (file) => [file, createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex')])))
const evidence = { base, startedAt: new Date().toISOString(), sourceSha256: await fingerprint(), isolation: 'Real index/main router; Vite proxy disabled, private cache, server API fail-closed; every API endpoint mocked in Playwright.', checks: [], screenshots: [], requests: [], unexpectedRequests: [], pageErrors: [] }
const check = (name, extra = {}) => { evidence.checks.push({ name, ...extra }); console.log(`PASS ${name}`) }
const server = await createServer({
  configFile: false,
  root: path.join(root, 'frontend'),
  cacheDir: path.join(output, 'vite-cache'),
  plugins: [react(), tailwindcss(), { name: 'no-real-api', configureServer(vite) {
    vite.middlewares.use((req, res, next) => {
      if (req.url?.startsWith('/api/')) { res.statusCode = 503; res.end('Live backend access is forbidden in this test'); return }
      next()
    })
  } }],
  server: { host: '127.0.0.1', port: Number(new URL(base).port), strictPort: true, proxy: {}, hmr: false, watch: null, open: false },
})
await server.listen()
console.log(`ISOLATED_REAL_APP ${base}`)

const book = { id: 'mockbook', title: '雾港来信', source: 'new', genre: '悬疑', status: 'ready', idea: '码头旧信的秘密', logline: '一封旧信牵动整座港口。', job_status: null, created_at: '2026-10-19T07:00:00Z', updated_at: '2026-10-19T08:00:00Z', style_reference: '', concept: { title: '雾港来信', story: '雨落在旧码头。沈九拾起一封没有署名的信。', genre: '悬疑', channel: '男频', tags: [], target_length: 30 }, protagonist: {}, world: {}, spine: {}, setup_progress: {}, requirements: [], trial_read_done: true, active_job: null, chapters_final: 0, words_final: 0, chapter_words: 2500, card_layouts: {} }
const settings = { settings: { setup_mode: 'puzzle', title_style: 'chief', title_custom: '', person: 'third', intimacy: 'fade', intimacy_custom: '', chapter_words: 2500, other_rules: '', playbook: 'auto', effort_preset: 'balanced', max_rewrites: 2, pitches: 3, review_strictness: 'standard', volume_audit: true, volume_approval: true, chapters_approval: false, segment_approval: true, trial_read: true }, rules_text: '' }
const info = (name, title, group, role, when, variables = []) => ({ name, title, group, role, when, variables, customized: false, updated_at: null, default_changed: false, new_variables: [], last_call: null })
const initialPrompts = [
  { ...info('chief_chat', '主编群聊', '编辑部对话', 'chief', '主编在群聊中接话时', [{ name: 'book_title', label: '书名' }, { name: 'author_message', label: '作者的话' }]), content: '你是长篇小说的主编。\n\n当前书名：{{book_title}}\n作者的话：{{author_message}}\n\n先分清作者是在讨论还是明确要求改书。尊重作者已有设定，确认后再动笔。', default_content: '你是长篇小说的主编。\n\n当前书名：{{book_title}}\n作者的话：{{author_message}}\n\n先分清作者是在讨论还是明确要求改书。尊重作者已有设定，确认后再动笔。', last_call: { id: 300, created_at: '2026-10-19T09:20:00Z' } },
  { ...info('plan_chapter', '规划章节', '写作流程', 'chief', '每次准备写新一章时', [{ name: 'outline', label: '章纲' }]), content: '根据{{outline}}规划这一章的场景与情绪推进。', default_content: '根据{{outline}}规划这一章的场景与情绪推进。' },
  { ...info('review_chapter', '审阅章节', '写作流程', 'reviewer', '正文完成后'), content: '检查人物一致性、节奏与语言，不擅自改写作者的设定。', default_content: '检查人物一致性、节奏与语言，不擅自改写作者的设定。' },
]
initialPrompts[0].content += '\n\n## 工作边界\n把尚在讨论的想法和已经确认的要求分开。作者只是询问时，先解释取舍，不擅自修改正文、设定和大纲。\n\n## 理解上下文\n先查看当前章节、人物关系与已有伏笔。对资料中没有的信息明确说明，不把推测写成既定事实。\n\n## 回复方式\n直接回答作者此刻的问题，使用清楚自然的中文。不复述大段背景，不用空泛的评价代替具体建议。\n\n## 提出方案\n如果需要改变故事，先列出建议改动的位置、目的和影响范围。把互相冲突的选择说清楚，让作者决定。\n\n## 尊重原稿\n保留作者已经写好的句子与锁定内容。需要动到既有内容时，解释为什么，并等待明确确认。\n\n## 完成后核对\n检查回应是否解决当前问题，是否误把讨论当作执行指令，是否遗漏作者强调的限制。'
initialPrompts[0].default_content = initialPrompts[0].content
const initialCalls = [
  { id: 300, book_id: 'mockbook', book_title: '雾港来信', role: 'chief', purpose: '主编群聊：讨论第一章线索', model: 'demo-chief', profile_name: '独立测试模型', prompt_tokens: 1846, completion_tokens: 620, latency_ms: 2450, ok: true, error: null, created_at: '2026-10-19T09:20:00Z' },
  { id: 299, book_id: 'mockbook', book_title: '雾港来信', role: 'writer', purpose: '写第四章 · 灯下的回信', model: 'demo-writer', profile_name: '写手测试模型', prompt_tokens: 5000, completion_tokens: 2800, latency_ms: 12600, ok: true, error: null, created_at: '2026-10-19T09:10:00Z' },
  { id: 298, book_id: 'otherbook', book_title: '山海旧闻', role: 'reviewer', purpose: '检查人物状态与叙事视角', model: 'a-long-provider-model-identifier-for-overflow-acceptance-test', profile_name: '审稿测试模型', prompt_tokens: null, completion_tokens: null, latency_ms: 890, ok: false, error: '模拟请求失败', created_at: '2026-10-19T09:00:00Z' },
]
let fixture
const reset = (options = {}) => { fixture = { prompts: structuredClone(initialPrompts), promptsMode: 'ready', promptsDelay: 0, callsMode: 'ready', callsDelay: 0, saveDelay: false, releases: [], saves: [], callFilters: [], ...options } }
reset()
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined }).catch(async (error) => { await server.close(); throw error })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', timezoneId: 'Asia/Taipei', reducedMotion: 'reduce' })
const page = await context.newPage()
page.on('pageerror', (error) => evidence.pageErrors.push(error.message))
await context.route((url) => url.pathname.startsWith('/api/'), async (route) => {
  const request = route.request(), url = new URL(request.url()), p = url.pathname.slice(4), method = request.method()
  evidence.requests.push({ method, path: p + url.search })
  const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  if (p === '/prompts' && method === 'GET') {
    if (fixture.promptsDelay) await new Promise((resolve) => setTimeout(resolve, fixture.promptsDelay))
    if (fixture.promptsMode === 'error') return reply({ detail: '模拟列表读取失败' }, 503)
    return reply(fixture.promptsMode === 'empty' ? [] : fixture.prompts.map(({ content: _content, default_content: _default, ...value }) => value))
  }
  if (p.startsWith('/prompts/')) {
    const name = decodeURIComponent(p.slice('/prompts/'.length)), prompt = fixture.prompts.find((value) => value.name === name)
    if (!prompt) { evidence.unexpectedRequests.push(`${method} ${p}`); return reply({ detail: '提示词不存在' }, 404) }
    if (method === 'GET') return reply(prompt)
    if (method === 'PUT') {
      const submitted = request.postDataJSON().content
      fixture.saves.push({ name, content: submitted })
      if (fixture.saveDelay) await new Promise((resolve) => fixture.releases.push(resolve))
      const updated = { ...prompt, content: submitted, customized: true, updated_at: '2026-10-19T10:00:00Z' }
      fixture.prompts = fixture.prompts.map((value) => value.name === name ? updated : value)
      return reply(updated)
    }
    if (method === 'DELETE') { prompt.content = prompt.default_content; prompt.customized = false; return route.fulfill({ status: 204 }) }
  }
  if (p === '/llm-calls') {
    if (fixture.callsDelay) await new Promise((resolve) => setTimeout(resolve, fixture.callsDelay))
    fixture.callFilters.push(Object.fromEntries(url.searchParams))
    if (fixture.callsMode === 'error') return reply({ detail: '模拟调用记录读取失败' }, 503)
    const items = fixture.callsMode === 'empty' ? [] : initialCalls.filter((value) => (!url.searchParams.get('book_id') || value.book_id === url.searchParams.get('book_id')) && (!url.searchParams.get('role') || value.role === url.searchParams.get('role')))
    if (url.searchParams.has('before')) return reply({ items: [{ ...initialCalls[0], id: 280, purpose: '更早的主编讨论' }], next_before: null })
    return reply({ items, next_before: items.length ? 298 : null })
  }
  if (/^\/llm-calls\/\d+$/.test(p)) {
    const call = initialCalls.find((value) => value.id === Number(p.split('/').at(-1))) || initialCalls[0]
    return reply({ ...call, request: { system: '这是本次真正发出的系统提示。\n先保护作者的原稿。', user: '请讨论雾港的第一封信。', schema_name: 'ChiefChat', schema: { type: 'object', properties: { reply: { type: 'string' } } }, method: 'json_mode' }, response: '{"reply":"可以先讨论线索，不自动修改书稿。"}' })
  }
  if (method === 'GET') {
    if (p === '/books') return reply([book, { ...book, id: 'otherbook', title: '山海旧闻' }])
    if (p === '/books/mockbook') return reply(book)
    if (p === '/books/mockbook/events') return route.fulfill({ status: 204 })
    if (p === '/books/mockbook/library') return reply({ categories: [], characters: [], entries: [], suggestions_pending: 0 })
    if (p === '/books/mockbook/outline-tree') return reply({ arcs: [], ending: null, segmented: false })
    if (p === '/books/mockbook/outline') return reply({ volumes: [] })
    if (p === '/books/mockbook/bible') return reply({ characters: [], world_entries: [], foreshadowings: [], relationships: [] })
    if (['/books/mockbook/chapters', '/books/mockbook/suggestions', '/books/mockbook/requirements', '/books/mockbook/chat/conversations'].includes(p)) return reply([])
    if (p === '/books/mockbook/settings' || p === '/settings/new-book-defaults') return reply(settings)
    if (p === '/books/mockbook/saves') return reply({ items: [], more: false })
    if (p === '/llm/profiles') return reply([])
    if (p === '/llm/roles') return reply({ default: null, chief: null, lorekeeper: null, writer: null, reviewer: null, router: null })
    if (p === '/health') return reply({ status: 'ok', components: { fixture: { ok: true, detail: 'isolated fixture' } } })
    if (p === '/book-meta') return reply({ channels: [{ key: '男频', categories: ['悬疑'], tag_groups: [] }, { key: '女频', categories: ['言情'], tag_groups: [] }], chapter_words: 2500, max_tags: 5 })
    if (p === '/glossary') return reply({ terms: [] })
  }
  evidence.unexpectedRequests.push(`${method} ${p}`)
  console.log(`UNMOCKED ${method} ${p}`)
  return reply({ detail: `Unmocked endpoint rejected: ${method} ${p}` }, 503)
})

const editor = () => page.getByTestId('prompt-editor').locator('.cm-content')
const sourceUrl = '/desk/mockbook?tab=%E5%A4%A7%E7%BA%B2&node=book#outline'
const pageTitle = () => page.getByRole('heading', { name: '提示词与调用记录', exact: true })
const returnLink = () => page.getByRole('link', { name: /返回当前书|返回书页|返回书房|回到书房|回到书页/ }).first()
const tab = (name) => page.getByRole('tab', { name, exact: true })
const shot = async (name) => {
  if (name === '01-settings-entry') await expect(page.getByRole('dialog', { name: '系统设置', exact: true })).toBeVisible()
  else if (name !== 'FAILED-state') await expect(pageTitle()).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true })
  evidence.screenshots.push(`${name}.png`)
}
const noOverflow = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'the document must not overflow horizontally')
const enterFromBook = async () => {
  await page.goto(base + sourceUrl)
  await page.getByRole('navigation').getByRole('button', { name: '大纲', exact: true }).click()
  await expect(page.getByRole('navigation').getByRole('button', { name: '大纲', exact: true })).toHaveAttribute('aria-current', 'page')
  await page.getByRole('button', { name: '系统设置', exact: true }).click()
  const settingsDialog = page.getByRole('dialog', { name: '系统设置', exact: true })
  await expect(settingsDialog).toBeVisible()
  await shot('01-settings-entry')
  const entry = settingsDialog.getByRole('link', { name: /提示词.*调用记录/ })
  await expect(entry).toBeVisible()
  await entry.click()
  await expect(pageTitle()).toBeVisible()
  await expect(settingsDialog).toHaveCount(0)
}
const append = async (text) => { await editor().click(); await editor().press('Control+End'); await page.keyboard.insertText(text) }

try {
  await enterFromBook()
  await expect(page.getByRole('heading', { name: '主编群聊', exact: true })).toBeVisible()
  await expect(editor()).toContainText('你是长篇小说的主编')
  assert.equal(evidence.requests.some((request) => request.path.startsWith('/prompts/setup_interview')), false)
  await noOverflow()
  await shot('02-prompts-first-catalog-item')
  check('Real book settings entry opens standalone prompt workspace; first catalog item is selected without retired setup_interview request')

  await page.getByRole('textbox', { name: '搜索提示词', exact: true }).fill('审阅')
  await expect(page.getByRole('navigation', { name: '提示词列表' }).getByRole('button', { name: '审阅章节', exact: true })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '提示词列表' }).getByRole('button', { name: '规划章节', exact: true })).toHaveCount(0)
  await page.getByRole('textbox', { name: '搜索提示词', exact: true }).fill('不存在的检索词')
  await expect(page.getByText(/没有.*匹配|没有找到/)).toBeVisible()
  await page.getByRole('textbox', { name: '搜索提示词', exact: true }).fill('')
  check('Prompt search filters catalog and renders a deliberate no-match state')

  await page.getByRole('button', { name: '自定义', exact: true }).click()
  await append('\n需要保留的本地草稿')
  await expect(page.getByText(/有未保存的本地草稿/)).toBeVisible()
  await page.getByRole('button', { name: '规划章节', exact: true }).click()
  await expect(page.getByRole('heading', { name: '规划章节', exact: true })).toBeVisible()
  await page.getByRole('navigation', { name: '提示词列表' }).getByRole('button', { name: /^主编群聊/ }).click()
  await expect(editor()).toContainText('需要保留的本地草稿')
  await tab('调用记录').click()
  await expect(page.getByRole('combobox', { name: '按书筛选' })).toHaveValue('mockbook')
  await tab('提示词').click()
  await expect(editor()).toContainText('需要保留的本地草稿')
  await page.reload()
  await expect(editor()).toContainText('需要保留的本地草稿')
  check('Local drafts survive template switching, calls tab, and reload; source book defaults calls filter')

  fixture.saveDelay = true
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(editor()).toHaveAttribute('contenteditable', 'false')
  await expect(page.getByRole('button', { name: '恢复默认', exact: true })).toBeDisabled()
  await expect.poll(() => fixture.releases.length).toBe(1)
  fixture.releases.shift()()
  await expect(page.getByText('已保存，从下一步调用起对所有书生效。')).toBeVisible()
  assert.equal(await page.evaluate(() => sessionStorage.getItem('zhibi:prompt-draft:chief_chat')), null)
  await expect(editor()).toContainText('需要保留的本地草稿')
  check('Pending save locks edit/reset; success preserves submitted content and clears only its draft')

  await page.getByRole('button', { name: '自定义', exact: true }).click()
  await append('\n慢请求里的旧稿')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => fixture.releases.length).toBe(1)
  await page.getByRole('button', { name: '规划章节', exact: true }).click()
  await expect(page.getByRole('heading', { name: '规划章节', exact: true })).toBeVisible()
  await page.getByRole('navigation', { name: '提示词列表' }).getByRole('button', { name: /^主编群聊/ }).click()
  await expect(editor()).toHaveAttribute('contenteditable', 'true')
  await append('\n重新打开后继续编辑的新稿')
  fixture.releases.shift()()
  await expect.poll(() => fixture.prompts[0].content.includes('慢请求里的旧稿')).toBe(true)
  await page.reload()
  await expect(editor()).toContainText('重新打开后继续编辑的新稿')
  fixture.saveDelay = false
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('已保存，从下一步调用起对所有书生效。')).toBeVisible()
  check('A prior save completing after navigation cannot erase a newer local draft')

  await tab('调用记录').click()
  await expect(page.getByText('主编群聊：讨论第一章线索', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '按角色筛选' }).selectOption('writer')
  await expect(page.getByText('写第四章 · 灯下的回信', { exact: true })).toBeVisible()
  await expect(page.getByText('主编群聊：讨论第一章线索', { exact: true })).toHaveCount(0)
  await page.getByRole('combobox', { name: '按书筛选' }).selectOption('')
  await tab('提示词').click(); await tab('调用记录').click()
  await expect(page.getByRole('combobox', { name: '按书筛选' })).toHaveValue('')
  await expect(page.getByRole('combobox', { name: '按角色筛选' })).toHaveValue('writer')
  await page.reload()
  await expect(page.getByRole('combobox', { name: '按书筛选' })).toHaveValue('')
  await expect(page.getByRole('combobox', { name: '按角色筛选' })).toHaveValue('writer')
  await page.getByRole('combobox', { name: '按角色筛选' }).selectOption('')
  await expect(page.getByText('检查人物状态与叙事视角', { exact: true })).toBeVisible()
  await noOverflow(); await shot('03-calls-table')
  check('Calls book/role filtering and explicit All-books choice survive tab switching and reload')

  const view = page.getByRole('button', { name: /^查看(?:详情)?$/ }).first()
  await expect(page.getByText(/每.*书.*2000.*调用/).first()).toBeVisible()
  await view.click()
  const detail = page.getByRole('dialog', { name: '调用详情', exact: true })
  await expect(detail).toBeVisible()
  await expect(detail.getByText(/这是本次真正发出的系统提示/)).toBeVisible()
  await expect(detail.getByText(/请讨论雾港的第一封信/)).toBeVisible()
  await expect.poll(() => detail.evaluate((el) => el.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Shift+Tab')
  await expect.poll(() => detail.evaluate((el) => el.contains(document.activeElement))).toBe(true)
  await shot('04-call-detail')
  await page.keyboard.press('Escape')
  await expect(detail).toHaveCount(0)
  await expect(view).toBeFocused()
  await page.getByRole('button', { name: /加载更早的记录/ }).click()
  await expect(page.getByText('更早的主编讨论', { exact: true })).toBeVisible()
  check('Call detail has real request/response fields, retention scope, focus containment/Escape restoration; pagination works')

  await page.reload()
  await expect(returnLink()).toHaveAttribute('href', sourceUrl)
  await returnLink().click()
  await expect(page).toHaveURL(base + sourceUrl)
  await expect(page.getByRole('button', { name: '系统设置', exact: true })).toBeVisible()
  await expect(page.getByRole('navigation').getByRole('button', { name: '大纲', exact: true })).toHaveAttribute('aria-current', 'page')
  check('Return link survives reload and restores original book pathname, query, hash, and actual Outline page selection')

  await page.goto(`${base}/prompts`)
  await expect(pageTitle()).toBeVisible()
  await expect(returnLink()).toHaveAttribute('href', '/')
  await returnLink().click()
  await expect(page).toHaveURL(base + '/')
  await page.goto(`${base}/prompts?returnTo=${encodeURIComponent('https://example.invalid/not-allowed')}`)
  await expect(returnLink()).toHaveAttribute('href', '/')
  check('Direct prompts entry returns to library; external return destination is rejected')

  await page.goto(`${base}/prompts?template=setup_interview`)
  await expect(page.getByRole('heading', { name: '主编群聊', exact: true })).toBeVisible()
  assert.equal(evidence.requests.some((request) => request.path.startsWith('/prompts/setup_interview')), false)
  check('Retired template URL falls back to the real catalog without an invalid detail request')

  reset({ promptsDelay: 1000 })
  let before = evidence.requests.length
  await page.goto(`${base}/prompts`)
  await expect(page.getByText(/正在读取提示词/).first()).toBeVisible()
  assert.equal(evidence.requests.slice(before).some((request) => /^\/prompts\//.test(request.path)), false)
  await expect(page.getByRole('heading', { name: '主编群聊', exact: true })).toBeVisible()
  check('Prompt details wait until catalog is loaded')

  reset({ promptsMode: 'error' })
  before = evidence.requests.length
  await page.reload()
  await expect(page.getByText('模拟列表读取失败')).toBeVisible({ timeout: 10000 })
  assert.equal(evidence.requests.slice(before).some((request) => /^\/prompts\//.test(request.path)), false)
  await shot('05-prompts-error')
  check('Catalog error shows actionable error without issuing guessed prompt requests')

  reset({ promptsMode: 'empty' })
  before = evidence.requests.length
  await page.reload()
  await expect(page.getByText(/暂无.*提示词|还没有.*提示词|没有可用的提示词/).first()).toBeVisible()
  assert.equal(evidence.requests.slice(before).some((request) => /^\/prompts\//.test(request.path)), false)
  await shot('06-prompts-empty')
  check('Empty catalog shows its own state and never requests a nonexistent template')

  reset({ callsDelay: 900 })
  await page.goto(`${base}/prompts?tab=calls`)
  await expect(page.getByText(/正在读取调用记录/).first()).toBeVisible()
  await expect(page.getByText('主编群聊：讨论第一章线索', { exact: true })).toBeVisible()
  check('Calls loading state resolves to records')

  reset({ callsMode: 'error' })
  await page.goto(`${base}/prompts?tab=calls`)
  await expect(page.getByText('模拟调用记录读取失败')).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('还没有符合条件的调用记录', { exact: true })).toHaveCount(0)
  await shot('07-calls-error')
  reset({ callsMode: 'empty' })
  await page.reload()
  await expect(page.getByText(/还没有.*调用记录|没有符合条件的调用记录/).first()).toBeVisible()
  await shot('08-calls-empty')
  check('Calls error and empty states are distinct')

  reset()
  await page.setViewportSize({ width: 2560, height: 1440 })
  await page.evaluate(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ deskScale: 120, theme: 'paper' })))
  await page.goto(`${base}/prompts`)
  await expect(editor()).toBeVisible()
  await noOverflow()
  await shot('09-wide-2560-scale120-prompts')
  const editorFont = await editor().evaluate((el) => getComputedStyle(el).fontSize)
  check('2560px workspace honors desk scale and readable prompt typography without horizontal overflow', { editorFont })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ deskScale: 100, theme: 'paper' })))
  await page.reload()
  await expect(editor()).toBeVisible()
  await noOverflow(); await shot('10-mobile-prompts')
  await tab('调用记录').click()
  await expect(page.getByText('主编群聊：讨论第一章线索', { exact: true })).toBeVisible()
  await noOverflow(); await shot('11-mobile-calls')
  check('390px prompt and call views remain readable and avoid document-level overflow')

  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.evaluate(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ deskScale: 100, theme: 'ink' })))
  await page.reload()
  await expect(pageTitle()).toBeVisible()
  await expect(tab('调用记录')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText('主编群聊：讨论第一章线索', { exact: true })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ink')
  await noOverflow(); await shot('12-dark-calls')
  await tab('提示词').click()
  await expect(editor()).toBeVisible()
  await noOverflow(); await shot('13-dark-prompts')
  check('Ink theme applies consistently to prompts and call records')

  assert.deepEqual(evidence.pageErrors, [])
  assert.deepEqual(evidence.unexpectedRequests, [])
  assert.deepEqual(await fingerprint(), evidence.sourceSha256, 'production source changed during this run; rerun the stable revision')
  assert(evidence.requests.filter((request) => request.method !== 'GET').every((request) => request.method === 'PUT' && request.path.startsWith('/prompts/')))
  check('Zero page errors or unexpected APIs; only mocked prompt saves were mutated')
  evidence.ok = true
  await fs.unlink(path.join(output, 'FAILED-state.png')).catch(() => {})
} catch (error) {
  evidence.ok = false; evidence.error = error.stack || String(error)
  await shot('FAILED-state').catch(() => {})
  throw error
} finally {
  evidence.finishedAt = new Date().toISOString()
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(evidence, null, 2) + '\n')
  await browser.close(); await server.close()
}
