import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { createHash } from 'node:crypto'

// Every case is seeded in the isolated copy before this read-only browser run.
const ROOT = path.resolve(import.meta.dirname, '../..')
const BASE = process.env.ZHIBI_DESK_URL ?? 'http://127.0.0.1:4351'
const API = process.env.ZHIBI_DESK_API ?? 'http://127.0.0.1:8051/api'
const OUT = path.resolve(ROOT, process.env.ZHIBI_INTERACTIONS_OUT ?? 'docs/拆书精髓验收/页面交互')
if (!process.env.ZHIBI_ESSENCE_CASES) throw new Error('请设置 ZHIBI_ESSENCE_CASES，指向隔离验收书 ID 的 JSON 清单')
const manifest = JSON.parse(fs.readFileSync(process.env.ZHIBI_ESSENCE_CASES, 'utf8'))
const cases = manifest.nt ? { book: manifest.nt.book, author: manifest.author.book, unread: manifest.unread.book, working: manifest.running.book, done: manifest.done.book, paused: manifest.stopped.book, withIntro: manifest.intro_no_waits.book, noOpen: manifest.intro_no_waits.book, oneLineBook: manifest.one_line.book, oneLineCharacter: manifest.one_line.character, partial: manifest.partial?.book, mixed: manifest.mixed?.book } : manifest
for (const name of ['book', 'author', 'unread', 'working', 'done', 'paused', 'withIntro', 'noOpen']) assert.ok(typeof cases[name] === 'string' && cases[name], `缺少隔离书 ID: ${name}`)
const dataContext = { window: {} }
vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'docs/界面原型/精髓样张-数据.js'), 'utf8'), dataContext)
const fixture = JSON.parse(JSON.stringify(dataContext.window.DATA))
const result = { at: new Date().toISOString(), base: BASE, api: API, cases, policy: '只读隔离副本；禁止所有非 GET/HEAD/OPTIONS API 请求及外部网络；不调用模型', checks: [], failures: [], errors: [], blockedWrites: [], externalRequests: [], screenshots: [], measurements: [] }
fs.mkdirSync(OUT, { recursive: true })
const json = async (id, suffix = '') => { const response = await fetch(`${API}/books/${id}${suffix}`); if (!response.ok) throw new Error(`${id}${suffix}: ${response.status}`); return response.json() }
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value
const hashAuthor = async () => createHash('sha256').update(JSON.stringify(canonical(await Promise.all(['', '/library', '/outline-tree', '/bible', '/chapters'].map(suffix => json(cases.author, suffix)))))).digest('hex')
result.authorBefore = await hashAuthor()
const executablePath = process.env.ZHIBI_CHROMIUM ?? ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Users/cxc/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe'].find(fs.existsSync)
const browser = await chromium.launch({ executablePath })
const contexts = []
const literal = text => new RegExp('^' + text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$')
const tab = (page, name) => page.locator('.tabs a').filter({ hasText: literal(name) }).click()
const stable = async page => { await page.locator('.desk-v2 .page h1').waitFor(); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(150) }
const shot = async (page, name) => { const file = name + '.png'; await page.screenshot({ path: path.join(OUT, file) }); result.screenshots.push(file) }
const run = async (name, action) => {
  const firstContext = contexts.length
  try { await action(); result.checks.push(name); console.log(`PASS ${name}`) }
  catch (error) { result.failures.push({ name, error: String(error), stack: error.stack }); console.error(`FAIL ${name}: ${error}`) }
  finally { for (const context of contexts.slice(firstContext)) await context.close() }
}
async function open(id, position = {}, { width = 1600, height = 900, ball, essenceRequest, ready = true } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: 'light' })
  contexts.push(context)
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (essenceRequest && url.pathname === `/api/books/${id}/teardown/essence`) return essenceRequest(route)
    if (url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { result.blockedWrites.push({ method: request.method(), path: url.pathname }); return route.abort('blockedbyclient') }
    if (url.protocol.startsWith('http') && !['127.0.0.1', 'localhost'].includes(url.hostname)) { result.externalRequests.push(url.origin + url.pathname); return route.abort('blockedbyclient') }
    return route.continue()
  })
  const page = await context.newPage()
  page.on('pageerror', error => result.errors.push(String(error)))
  const saves = await json(id, '/saves?limit=1')
  if (saves.items[0]) await page.clock.setFixedTime(new Date(new Date(saves.items[0].created_at).getTime() + 8 * 60_000))
  await page.addInitScript(({ id, position, ball }) => {
    localStorage.setItem('zhibi:editorial-dock', 'ball')
    localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 }))
    const key = 'zhibi:workspace-reading:' + id
    if (!sessionStorage.getItem(key)) sessionStorage.setItem(key, JSON.stringify({ tab: '简介', essence: 'overview', entry: 'overview', node: 'book', chapter: 'home', open: [], ...position }))
    if (ball !== undefined && !sessionStorage.getItem('test:ball-seeded')) { localStorage.setItem('zhibi.ball', ball); sessionStorage.setItem('test:ball-seeded', '1') }
  }, { id, position, ball })
  await page.goto(`${BASE}/desk/${id}`, { waitUntil: 'domcontentloaded' })
  if (ready) await stable(page)
  else await page.locator('.desk-v2').waitFor()
  return page
}
const selectSection = async (page, title) => { await page.locator('.toc .row').filter({ hasText: title }).click(); await stable(page); assert.equal(await page.locator('.page h1').innerText(), title) }
const box = page => page.locator('.ball').evaluate(element => { const r = element.getBoundingClientRect(); const root = element.closest('.desk-v2'); return { x: r.x, y: r.y, width: r.width, height: r.height, zoom: Number(getComputedStyle(root).zoom), viewport: { width: innerWidth, height: innerHeight } } })
try {
  await run('精髓搜索同时过滤知识点与人物，数字随命中变化，清空恢复', async () => {
    const page = await open(cases.book, { tab: '精髓' })
    const input = page.locator('.toc .search input')
    const pointMatches = (point, q) => [point.title, ...(point.steps ?? []), point.evidence, point.note].some(value => value?.includes(q))
    const figureMatches = (figure, q) => [figure.name, figure.archetype, figure.build, figure.role, figure.arc].some(value => value?.includes(q))
    for (const q of ['余波', fixture.essence.sections.cast.figures[0].name]) {
      await input.fill(q)
      const expected = Object.fromEntries([['核心要点', fixture.essence.overview.points.filter(point => pointMatches(point, q)).length], ...Object.entries(fixture.essence.sections).map(([key, section]) => [fixture.names[key], section.points.filter(point => pointMatches(point, q)).length + (section.figures ?? []).filter(figure => figureMatches(figure, q)).length])].filter(([, count]) => count > 0))
      const rows = await page.locator('.toc .row.top1,.toc .kids .row').evaluateAll(elements => Object.fromEntries(elements.map(element => [element.textContent.replace(element.querySelector('.n')?.textContent ?? '', '').trim(), Number(element.querySelector('.n')?.textContent)])))
      assert.deepEqual(rows, expected)
    }
    await input.fill('不可能命中的验收搜索词')
    assert.equal(await page.locator('.toc .row').count(), 0)
    await input.fill('')
    assert.equal(await page.locator('.toc .kids .row').count(), 12)
    await selectSection(page, '核心要点')
    await shot(page, '精髓-核心要点')
  })
  await run('精髓章号点击打开大纲对应章', async () => {
    const page = await open(cases.book, { tab: '精髓' })
    const ref = page.locator('.page .ref').first()
    const index = Number((await ref.innerText()).match(/\d+/)[0])
    await ref.click(); await stable(page)
    assert.equal(await page.locator('.tabs .on').innerText(), '大纲')
    assert.match(await page.locator('.page .kicker').innerText(), new RegExp(`第\\s*${index}\\s*章`))
  })
  await run('精髓记住上次小节，跨标签与刷新保留', async () => {
    const page = await open(cases.book, { tab: '精髓' })
    await selectSection(page, '情节怎么想'); await shot(page, '精髓-情节怎么想')
    await tab(page, '简介'); await tab(page, '精髓'); await stable(page)
    assert.equal(await page.locator('.page h1').innerText(), '情节怎么想')
    await page.reload(); await stable(page)
    assert.equal(await page.locator('.page h1').innerText(), '情节怎么想')
    await selectSection(page, '配角与对手'); await shot(page, '精髓-配角与对手')
  })
  const absent = {
    unread: '还没开拆。拆过的章会整理成一条条知识点：情节怎么想、设定怎么设、爽点怎么造、人物怎么立。',
    working: '拆书收尾时整理精髓，到时这里就有了。',
    done: '还没整理精髓：点右上角「补上整理」，不重读原文。',
    paused: null,
  }
  for (const [name, expected] of Object.entries(absent)) await run(`无精髓状态：${name}`, async () => {
    const detail = await json(cases[name])
    const page = await open(cases[name], { tab: '精髓' })
    assert.equal(await page.locator('.page .kicker').innerText(), '精髓')
    assert.equal(await page.locator('.page h1').innerText(), '核心要点')
    assert.equal(await page.locator('.page .state').innerText(), expected ?? `还没整理精髓：点右上角「接着拆」，选「只整理前 ${detail.teardown.last_read} 章」，不重读原文。`)
  })
  await run('首次非 null 但 upto 为空的半成品按无精髓显示', async () => {
    assert.ok(cases.partial, '缺少 partial 真实副本')
    const response = await json(cases.partial, '/teardown/essence')
    assert.ok(response.essence && response.essence.upto == null)
    const page = await open(cases.partial, { tab: '精髓' })
    assert.equal(await page.locator('.page .state').innerText(), '拆书收尾时整理精髓，到时这里就有了。')
    assert.ok((await page.locator('.top .progress').innerText()).includes('主编在整理精髓：核心要点'))
    assert.equal(await page.locator('.page .kp').count(), 0)
    await tab(page, '简介'); await stable(page)
    assert.equal(await page.locator('.intro2 .state').innerText(), '精髓还没整理：拆书收尾时会整理，整理好以后这里会有一句话看懂和最值得学的几件事。')
    assert.equal(await page.locator('.intro2 .learn').count(), 0)
  })
  await run('upto 有值的重整理中间态直接显示 API 的新旧小节', async () => {
    assert.ok(cases.mixed, '缺少 mixed 真实副本')
    const response = await json(cases.mixed, '/teardown/essence')
    assert.ok(response.essence?.upto > 0)
    const sections = Object.entries(response.essence.sections)
    assert.ok(sections.length >= 2)
    const page = await open(cases.mixed, { tab: '精髓', essence: sections[0][0] })
    assert.ok((await page.locator('.top .progress').innerText()).includes('主编在整理精髓：核心要点'))
    for (const [key, section] of sections) {
      await selectSection(page, fixture.names[key])
      assert.ok((await page.locator('.page .meta').innerText()).includes(`基于前 ${response.essence.upto} 章`))
      for (const point of section.points) assert.ok((await page.locator('.page .kp h3').allTextContents()).some(title => title.includes(point.title)))
    }
    assert.equal(await page.locator('.page .state').filter({ hasText: '还没整理精髓' }).count(), 0)
  })
  await run('精髓 API 加载中和请求失败不冒充尚未整理（仅本项模拟请求）', async () => {
    const noEssenceText = ['还没开拆。', '拆书收尾时整理精髓，到时这里就有了。', '还没整理精髓：', '精髓还没整理：']
    let release
    const gate = new Promise(resolve => { release = resolve })
    let loading
    try {
      loading = await open(cases.book, { tab: '精髓' }, { ready: false, essenceRequest: async route => { await gate; return route.continue() } })
      await loading.waitForTimeout(250)
      const text = await loading.locator('.desk-v2').innerText()
      assert.ok(noEssenceText.every(value => !text.includes(value)))
      assert.equal(await loading.locator('.page .kp').count(), 0)
      result.loadingText = text
    } finally { release() }
    await loading.locator('.page .kp').first().waitFor()
    const error = await open(cases.book, { tab: '精髓' }, { ready: false, essenceRequest: route => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: '验收专用：精髓请求失败' }) }) })
    await error.locator('.page [role="alert"]').filter({ hasText: '验收专用：精髓请求失败' }).waitFor()
    const text = await error.locator('.desk-v2').innerText()
    assert.ok(noEssenceText.every(value => !text.includes(value)))
    assert.equal(await error.locator('.page .kp').count(), 0)
    result.errorText = text
  })
  await run('作者自己的书没有精髓标签，角色置顶后主角在其余之前', async () => {
    const page = await open(cases.author, { tab: '设定', entry: 'cat:角色列表', open: ['cat:角色列表'] })
    assert.deepEqual(await page.locator('.tabs a').allTextContents(), ['简介', '设定', '大纲', '正文'])
    const bible = await json(cases.author, '/bible')
    const pinned = bible.characters.filter(character => character.pinned_at).sort((a, b) => b.pinned_at.localeCompare(a.pinned_at))
    const rest = bible.characters.filter(character => !character.pinned_at)
    assert.ok(pinned.some(character => character.role_type !== '主角') && rest.some(character => character.role_type === '主角'), '作者验收副本须有置顶非主角及未置顶主角')
    const expected = [...pinned, ...rest.filter(character => character.role_type === '主角'), ...rest.filter(character => character.role_type !== '主角')].map(character => character.name)
    assert.deepEqual(await page.locator('.toc .kids .row').filter({ hasNotText: '新建一条' }).allTextContents(), expected)
  })
  await run('新简介有精髓，知识点、单元、人物、等候均能导航', async () => {
    const page = await open(cases.book)
    assert.equal(await page.locator('.intro2 .engine').count(), 0)
    assert.ok(await page.locator('.intro2 .learn li').count() > 0)
    assert.equal(await page.locator('.intro2 .label').getByText('原书简介', { exact: true }).count(), 0)
    await shot(page, '简介-有精髓')
    await page.getByText('去精髓页 ›', { exact: true }).click(); await stable(page)
    assert.equal(await page.locator('.page h1').innerText(), '核心要点')
    await tab(page, '简介'); await page.locator('.intro2 .learn li').first().click(); await stable(page)
    assert.equal(await page.locator('.page h1').innerText(), '核心要点')
    await tab(page, '简介'); await page.locator('.intro2 .ucard').first().click(); await stable(page)
    assert.equal(await page.locator('.tabs .on').innerText(), '大纲')
    await tab(page, '简介'); const name = await page.locator('.cast2 .nm').first().innerText(); await page.locator('.cast2 .nm').first().click(); await stable(page)
    assert.equal(await page.locator('.tabs .on').innerText(), '设定'); assert.equal(await page.locator('.page h1').innerText(), name)
    await tab(page, '简介'); const index = Number((await page.locator('.waits2 li').first().innerText()).match(/第\s*(\d+)\s*章/)[1]); await page.locator('.waits2 li').first().click(); await stable(page)
    assert.match(await page.locator('.page .kicker').innerText(), new RegExp(`第\\s*${index}\\s*章`))
  })
  await run('没有精髓的简介只保留书、单元、人物与说明', async () => {
    const page = await open(cases.paused)
    assert.equal(await page.locator('.intro2 .state').innerText(), '精髓还没整理：拆书收尾时会整理，整理好以后这里会有一句话看懂和最值得学的几件事。')
    assert.equal(await page.locator('.intro2 .learn,.intro2 .bars,.intro2 .feelstrip').count(), 0)
    assert.equal(await page.getByText('一句话看懂', { exact: true }).count(), 0)
    assert.equal(await page.locator('.cast2 .chip').count(), 0)
    assert.ok((await page.locator('.cast2 .ct').allTextContents()).every(text => text.trim() === ''))
    await shot(page, '简介-没精髓')
  })
  await run('简介有原书简介且保留换行；没有等候时整块不显示', async () => {
    const page = await open(cases.withIntro)
    const detail = await json(cases.withIntro)
    assert.ok(detail.teardown.intro.includes('\n'), '验收简介须包含换行')
    const paragraph = page.locator('.intro2 .sec').filter({ has: page.getByText('原书简介', { exact: true }) }).locator('.lead')
    assert.equal(await paragraph.innerText(), detail.teardown.intro)
    assert.equal(await paragraph.evaluate(element => getComputedStyle(element).whiteSpace), 'pre-line')
    const noOpen = await open(cases.noOpen)
    assert.equal(await noOpen.getByText('读者还在等', { exact: true }).count(), 0)
  })
  await run('设定和大纲分类再点收起，小箭头只切展开不导航', async () => {
    for (const id of [cases.book, cases.author]) {
      const page = await open(id, { tab: '设定', entry: 'cat:角色列表', open: ['cat:角色列表'] })
      const row = page.locator('.toc .row.unit').filter({ hasText: '角色列表' })
      assert.ok(!(await row.getAttribute('class')).includes('closed'))
      const title = await page.locator('.page h1').innerText()
      await row.click(); assert.ok((await row.getAttribute('class')).includes('closed')); assert.equal(await page.locator('.page h1').innerText(), title)
      await row.locator('.chev').click(); assert.ok(!(await row.getAttribute('class')).includes('closed')); assert.equal(await page.locator('.page h1').innerText(), title)
      await page.locator('.toc .row.top1').filter({ hasText: '设定总览' }).click(); const overview = await page.locator('.page h1').innerText()
      await row.locator('.chev').click(); assert.equal(await page.locator('.page h1').innerText(), overview)
      await tab(page, '大纲'); await stable(page)
      const volume = page.locator('.toc .row.top1').filter({ has: page.locator('.chev') }).nth(1)
      await volume.click(); await stable(page); const volumeTitle = await page.locator('.page h1').innerText()
      await volume.click(); assert.ok((await volume.getAttribute('class')).includes('closed')); assert.equal(await page.locator('.page h1').innerText(), volumeTitle)
      await volume.locator('.chev').click(); assert.equal(await page.locator('.page h1').innerText(), volumeTitle)
      const unit = page.locator('.toc .row.unit').first()
      await unit.click(); await stable(page); const unitTitle = await page.locator('.page h1').innerText()
      await unit.click(); assert.ok((await unit.getAttribute('class')).includes('closed')); assert.equal(await page.locator('.page h1').innerText(), unitTitle)
      await unit.locator('.chev').click(); assert.equal(await page.locator('.page h1').innerText(), unitTitle)
    }
  })
  await run('拆书角色按 position 排，一句话卡正文及右栏完整，变化不改原字段', async () => {
    const bible = await json(cases.book, '/bible')
    const expected = [...bible.characters].sort((a, b) => a.position - b.position).map(character => character.name)
    const page = await open(cases.book, { tab: '设定', entry: 'cat:角色列表', open: ['cat:角色列表'] })
    assert.deepEqual(await page.locator('.toc .kids .row').allTextContents(), expected)
    const oneLineBook = cases.oneLineBook ?? cases.book
    const oneLineBible = oneLineBook === cases.book ? bible : await json(oneLineBook, '/bible')
    const oneLinePage = oneLineBook === cases.book ? page : await open(oneLineBook, { tab: '设定', entry: 'cat:角色列表', open: ['cat:角色列表'] })
    const contentFields = ['gender', 'age', 'appearance', 'personality', 'background', 'abilities', 'goal', 'want', 'location', 'condition', 'notes', 'relation']
    const empty = value => !value || value === '（记录里没有）'
    const one = oneLineBible.characters.find(character => (!cases.oneLineCharacter || character.id === cases.oneLineCharacter) && character.one_line && character.is_alive && contentFields.every(field => empty(character[field])) && Object.entries(character.extra ?? {}).every(([key, value]) => ['别名', '定位'].includes(key) || empty(value)))
    assert.ok(one, '验收副本须有只记一句话的角色')
    await oneLinePage.locator('.toc .kids .row').filter({ hasText: literal(one.name) }).click(); await stable(oneLinePage)
    assert.equal(await oneLinePage.locator('.page .lead').first().innerText(), one.one_line)
    const rb = oneLinePage.locator('.rail .rb').filter({ has: oneLinePage.getByRole('heading', { name: '只记一句话', exact: true }) })
    const seen = await json(oneLineBook, `/teardown/appearances?character=${one.id}`)
    assert.equal(await rb.locator('.small').innerText(), `出场 ${seen.chapters.length} 章。出场 5 章以上或者有名场面的人才写全卡，其余的只记一句话。`)
    assert.equal(await oneLinePage.getByText('记录里没有', { exact: true }).count(), 0)
    await shot(oneLinePage, '角色-只记一句话')
    await page.locator('.toc .kids .row').filter({ hasText: literal('茉莉') }).click(); await stable(page)
    assert.equal(await page.getByText('成长与结局', { exact: true }).count(), 0)
    assert.ok(await page.getByText('变化', { exact: true }).count() > 0)
  })
  await run('印章单击打开、拖动不打开、左右贴边及刷新记忆、坏存储默认、放大换算', async () => {
    for (const width of [1600, 2560]) {
      const page = await open(cases.book, {}, { width, height: width === 1600 ? 900 : 1312 })
      const ball = page.locator('.ball')
      let before = await box(page)
      await ball.click(); await page.getByTestId('editorial-floating').waitFor(); await page.getByRole('button', { name: '收起', exact: true }).click(); await ball.waitFor()
      before = await box(page)
      await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2); await page.mouse.down(); await page.mouse.move(90, 300, { steps: 12 }); await page.mouse.up(); await page.waitForTimeout(200)
      assert.equal(await page.getByTestId('editorial-floating').count(), 0)
      let after = await box(page)
      assert.ok(Math.abs(after.x - 24 * after.zoom) <= .5, JSON.stringify(after))
      assert.ok(after.y >= 70 * after.zoom - .5 && after.y + after.height <= after.viewport.height - 16 * after.zoom + .5)
      const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('zhibi.ball')))
      assert.equal(saved.side, 'left'); assert.ok(Number.isFinite(saved.top)); result.measurements.push({ width, before, after, saved })
      if (width === 1600) await shot(page, '按钮-拖到左边')
      await page.reload(); await stable(page); const restored = await box(page)
      assert.ok(Math.abs(restored.x - after.x) <= .5 && Math.abs(restored.y - after.y) <= .5, JSON.stringify({ after, restored }))
      await page.mouse.move(restored.x + restored.width / 2, restored.y + restored.height / 2); await page.mouse.down(); await page.mouse.move(width - 60, 500, { steps: 12 }); await page.mouse.up(); await page.waitForTimeout(200)
      after = await box(page); assert.ok(Math.abs(width - after.x - after.width - 24 * after.zoom) <= .5, JSON.stringify(after))
      assert.equal(await page.getByTestId('editorial-floating').count(), 0)
      const rightSaved = await page.evaluate(() => JSON.parse(localStorage.getItem('zhibi.ball')))
      await page.setViewportSize({ width: width === 1600 ? 2560 : 1600, height: width === 1600 ? 1312 : 900 }); await page.waitForTimeout(200)
      after = await box(page); assert.ok(Math.abs(after.viewport.width - after.x - after.width - 24 * after.zoom) <= .5, JSON.stringify(after))
      const cssHeight = after.viewport.height / after.zoom
      const expectedTop = Math.min(Math.max(70, rightSaved.top * cssHeight), cssHeight - after.height / after.zoom - 16)
      assert.ok(Math.abs(after.y / after.zoom - expectedTop) <= .5, JSON.stringify({ after, rightSaved, expectedTop }))
      result.measurements.push({ resizeFrom: width, rightSaved, after, expectedTopCssPx: expectedTop })
    }
    for (const value of ['{broken', JSON.stringify({ side: 'sideways', top: .2 }), JSON.stringify({ side: 'left', top: 'bad' })]) {
      const page = await open(cases.book, {}, { ball: value })
      const actual = await box(page)
      assert.ok(Math.abs(actual.viewport.width - actual.x - actual.width - 24 * actual.zoom) <= .5)
      assert.ok(Math.abs(actual.viewport.height - actual.y - actual.height - 22 * actual.zoom) <= .5)
    }
  })
} finally {
  for (const context of contexts) await context.close()
  await browser.close()
  result.authorAfter = await hashAuthor()
  result.authorUnchanged = result.authorBefore === result.authorAfter
  if (!result.authorUnchanged) result.failures.push({ name: '作者副本只读保护', error: '打开前后 API 指纹不同' })
  fs.writeFileSync(path.join(OUT, 'interactions-summary.json'), JSON.stringify(result, null, 2))
}
if (result.failures.length || result.errors.length || result.blockedWrites.length || result.externalRequests.length) throw new Error(JSON.stringify({ failures: result.failures, errors: result.errors, blockedWrites: result.blockedWrites, externalRequests: result.externalRequests }))
