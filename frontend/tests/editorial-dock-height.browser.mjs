/** 小修 4 回归：编辑部贴到书桌右边时，右栏的高度永远等于书桌主体那一格，聊天再长输入框也在窗口里、聊天记录自己滚。
 *  真 API、合成长聊天书（拆的书带精髓 + 写的书）、真实鼠标（点击、打字、发送、拖动、滚轮）；仅允许独立端口，
 *  禁日常 8000/4320，禁外网。发送走演示模式（模型配置为空），真实模型 0 次。
 *  ZHIBI_TALL_URL=http://127.0.0.1:<独立前端> ZHIBI_TALL_API=http://127.0.0.1:<独立API>/api
 *  ZHIBI_TALL_FIXTURE=data/import-small4-20261021/fixtures.json node tests/editorial-dock-height.browser.mjs */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const BASE = process.env.ZHIBI_TALL_URL, API = process.env.ZHIBI_TALL_API
assert.ok(BASE && API && process.env.ZHIBI_TALL_FIXTURE, '需要 ZHIBI_TALL_URL / ZHIBI_TALL_API / ZHIBI_TALL_FIXTURE')
for (const address of [BASE, API]) {
  const url = new URL(address)
  assert.ok(['127.0.0.1', 'localhost'].includes(url.hostname) && url.port && !['8000', '4320'].includes(url.port), `只能连独立本地端口：${address}`)
}
const fixture = JSON.parse(fs.readFileSync(process.env.ZHIBI_TALL_FIXTURE, 'utf8'))
const OUT = path.resolve(import.meta.dirname, '../../data/import-small4-20261021')
const SHOT = path.resolve(import.meta.dirname, '../../docs/拆书导入验收')
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.ZHIBI_CHROMIUM
  || ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Users/cxc/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe'].find(fs.existsSync)
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, colorScheme: 'light', reducedMotion: 'reduce' })
const errors = [], external = [], api = [], results = []
await context.route('**/*', route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && !['127.0.0.1', 'localhost'].includes(url.hostname)) { external.push(url.origin); return route.abort() }
  if (url.pathname.startsWith('/api/')) api.push(`${route.request().method()} ${url.pathname}`)
  return route.continue()
})
await context.addInitScript(() => {
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 }))
})
const page = await context.newPage()
page.on('pageerror', error => errors.push(String(error)))

const tab = name => page.locator('header.top nav').getByText(name, { exact: true })
const aside = () => page.getByTestId('editorial-docked')
const notes = () => page.locator('[data-testid="editorial-docked"] [data-testid^="note-"]')
const replies = () => page.locator('[data-testid="editorial-docked"] [data-testid^="reply-"]')
const composer = () => page.getByLabel('给编辑部发消息')
const CHAT = '[data-testid="editorial-docked"] div.space-y-5.overflow-y-auto'
const scrollTop = () => page.evaluate(selector => document.querySelector(selector).scrollTop, CHAT)
const scrollMax = () => page.evaluate(selector => { const el = document.querySelector(selector); return el.scrollHeight - el.clientHeight }, CHAT)
const scrollTo = top => page.evaluate(([selector, top]) => { document.querySelector(selector).scrollTop = top }, [CHAT, top])

/** 现在这本书正在聊的那一段有几句作者的话（发送以后也会变多） */
const currentNotes = async bookId => {
  const rows = await (await fetch(`${API}/books/${bookId}/chat/conversations`)).json()
  const now = rows.find(row => row.current)
  assert.ok(now, '书里该有一段正在聊的对话')
  return now.notes
}

/** 一格一格量：书桌主体、右栏、其余贴在网格里的栏、输入框、聊天列表 */
const measure = () => page.evaluate(() => {
  const body = document.querySelector('.desk-v2 .body')
  const bodyHeight = body.getBoundingClientRect().height
  const columns = [...body.children].map(el => ({ tag: `${el.tagName.toLowerCase()}${el.className ? `.${String(el.className).split(' ')[0]}` : ''}`, height: el.getBoundingClientRect().height }))
  const docked = document.querySelector('[data-testid="editorial-docked"]')
  const box = document.querySelector('[aria-label="给编辑部发消息"]')?.getBoundingClientRect()
  const chat = docked?.querySelector('div.space-y-5.overflow-y-auto')
  return {
    body: bodyHeight, columns,
    docked: docked?.getBoundingClientRect().height ?? null,
    maxColumn: Math.max(...columns.map(c => c.height)),
    composer: box ? { top: box.top, bottom: box.bottom } : null,
    chat: chat ? { client: chat.clientHeight, scroll: chat.scrollHeight, top: chat.scrollTop, max: chat.scrollHeight - chat.clientHeight } : null,
    grid: getComputedStyle(body).gridTemplateColumns,
  }
})
const seenInChat = which => page.evaluate(([selector, which]) => {
  const box = document.querySelector(selector)
  const all = [...box.querySelectorAll('[data-testid^="note-"],[data-testid^="reply-"]')]
  const el = which === 'first' ? all[0] : all.at(-1)
  const r = el.getBoundingClientRect(), b = box.getBoundingClientRect()
  return { id: el.dataset.testid, inBox: r.bottom > b.top + 1 && r.top < b.bottom - 1 }
}, [CHAT, which])

/** 贴右不变量：右栏=书桌主体；网格里别的栏不被撑高；输入框整个在窗口里；聊天列表出滚动条、能到顶也能到底 */
async function checkDocked(name) {
  await expect.poll(async () => {
    const value = await measure()
    return value.docked !== null && value.composer !== null && value.chat !== null ? value.docked : null
  }, { timeout: 15_000 }).toBeTruthy()
  const h = await measure()
  assert.ok(Math.abs(h.docked - h.body) <= 1.5, `${name}：右栏高 ${h.docked} 应等于书桌主体高 ${h.body}`)
  assert.ok(h.maxColumn <= h.body + 1.5, `${name}：网格里最高的栏 ${h.maxColumn} 不该超过书桌主体 ${h.body}（${h.columns.map(c => `${c.tag}:${Math.round(c.height)}`).join(' ')}）`)
  assert.ok(h.composer.top >= -0.5 && h.composer.bottom <= page.viewportSize().height + 0.5, `${name}：输入框（${h.composer.top}–${h.composer.bottom}）该整个在 ${page.viewportSize().height} 高的窗口里`)
  assert.ok(h.chat.scroll > h.chat.client + 200, `${name}：聊天内容 ${h.chat.scroll} 远高于可见 ${h.chat.client}，该自己滚`)
  await scrollTo(0)
  assert.equal(await scrollTop(), 0, `${name}：能滚到最上面`)
  const first = await seenInChat('first')
  assert.ok(first.inBox, `${name}：滚到顶看见第一句 ${first.id}`)
  await scrollTo(1e9)
  assert.ok(Math.abs((await scrollTop()) - (await scrollMax())) <= 1, `${name}：能滚到最下面`)
  const last = await seenInChat('last')
  assert.ok(last.inBox, `${name}：滚到底看见最后一句 ${last.id}`)
  return { name, body: Math.round(h.body * 10) / 10, docked: Math.round(h.docked * 10) / 10, columns: h.columns, composer: { top: Math.round(h.composer.top), bottom: Math.round(h.composer.bottom) }, chat: h.chat, grid: h.grid }
}

const check = async (name, run) => { const detail = await run(); results.push({ name, passed: true, detail }); console.log('PASS', name) }

/** 真鼠标把编辑部从小球开成浮窗再贴到右边 */
async function dockByMouse() {
  await expect(page.locator('[role="button"][title="编辑部"]')).toBeVisible()
  await page.locator('[role="button"][title="编辑部"]').click()
  await expect(page.getByTestId('editorial-floating')).toBeVisible()
  await page.getByRole('button', { name: '贴到右边', exact: true }).click()
  await expect(aside()).toBeVisible()
}

/** 真鼠标打字、点发送；句句真发到独立 API（演示模式答，真实模型 0 次） */
async function sendByMouse(tag) {
  // 两条基线都在点发送之前量好：主编答得快，量晚了就把回复算进基线
  const before = await notes().count()
  const repliesBefore = await replies().count()
  await composer().click()
  await composer().pressSequentially('这一段聊了这么长，输入框还在最下面吗？')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(notes()).toHaveCount(before + 1, { timeout: 20_000 })
  await expect(notes().last()).toContainText('这一段聊了这么长')
  await expect(replies()).toHaveCount(repliesBefore + 1, { timeout: 30_000 })
  await expect(replies().last()).toHaveAttribute('data-state', /done|stopped|failed/, { timeout: 30_000 })
  const h = await measure()
  assert.ok(h.composer.top >= -0.5 && h.composer.bottom <= page.viewportSize().height + 0.5, `${tag}：发完之后输入框还整个在窗口里`)
  return { notes: before + 1, replies: repliesBefore + 1, composer: { top: Math.round(h.composer.top), bottom: Math.round(h.composer.bottom) } }
}

try {
  const torn = fixture.teardown, written = fixture.new
  for (const [width, height] of [[1280, 800], [1700, 900]]) {
    const tag = `${width}x${height}`
    await page.setViewportSize({ width, height })
    // 拆的书：简介、精髓、设定、大纲、正文五页（简介页的网格列和别的页不一样）
    await page.goto(`${BASE}/desk/${torn.book}`)
    if (width === 1280) await dockByMouse()
    else await expect(aside()).toBeVisible()
    await expect(notes()).toHaveCount(await currentNotes(torn.book))
    for (const name of ['简介', '精髓', '设定', '大纲', '正文']) {
      await tab(name).click()
      await expect.poll(() => page.locator('header.top nav a.on').textContent()).toBe(name)
      await check(`${tag} 拆的书·${name}`, () => checkDocked(`${tag} 拆的书·${name}`))
    }
    await check(`${tag} 拆的书·打字点发送`, () => sendByMouse(`${tag} 拆的书`))
    // 写的书：简介、设定、大纲、正文四页（没有精髓）
    await page.goto(`${BASE}/desk/${written.book}`)
    await expect(aside()).toBeVisible()
    await expect(notes()).toHaveCount(await currentNotes(written.book))
    for (const name of ['简介', '设定', '大纲', '正文']) {
      await tab(name).click()
      await expect.poll(() => page.locator('header.top nav a.on').textContent()).toBe(name)
      await check(`${tag} 写的书·${name}`, () => checkDocked(`${tag} 写的书·${name}`))
    }
  }
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`${BASE}/desk/${torn.book}`)
  await expect(aside()).toBeVisible()
  await expect(notes()).toHaveCount(await currentNotes(torn.book))
  await check('1280x800 真滚轮上下滚聊天', async () => {
    const box = await page.locator(CHAT).boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, -600)
    const up = await scrollTop()
    assert.ok(up > 0, `滚轮向上该离开底部（scrollTop=${up}）`)
    await page.mouse.wheel(0, 2000)
    const down = await scrollTop()
    assert.ok(Math.abs(down - (await scrollMax())) <= 1, `滚轮向下该回到最底（scrollTop=${down}）`)
    return { up, down }
  })
  await check('1280x800 拖分隔线调宽窄：宽度变、高度不变、输入框还在', async () => {
    const before = await measure()
    const widthBefore = await aside().evaluate(el => el.getBoundingClientRect().width)
    const handle = await page.locator('[title="拖动调宽窄"]').boundingBox()
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
    await page.mouse.down()
    await page.mouse.move(handle.x + handle.width / 2 - 80, handle.y + handle.height / 2, { steps: 8 })
    await page.mouse.up()
    await expect.poll(async () => {
      const value = await measure()
      return value.docked !== null && Math.abs(value.docked - before.body) <= 1.5 ? value.docked : null
    }, { timeout: 10_000 }).toBeTruthy()
    const after = await measure()
    const widthAfter = await aside().evaluate(el => el.getBoundingClientRect().width)
    assert.ok(Math.abs(widthAfter - widthBefore - 80) < 4, `往左拖 80px 该把右栏放宽 80px（${widthBefore} → ${widthAfter}）`)
    assert.ok(Math.abs(after.docked - before.body) <= 1.5, '调宽窄不改右栏高度')
    assert.ok(after.composer.top >= -0.5 && after.composer.bottom <= page.viewportSize().height + 0.5, '输入框还在窗口里')
    const back = await page.locator('[title="拖动调宽窄"]').boundingBox()
    await page.mouse.move(back.x + back.width / 2, back.y + back.height / 2)
    await page.mouse.down()
    await page.mouse.move(back.x + back.width / 2 + 80, back.y + back.height / 2, { steps: 8 })
    await page.mouse.up()
    return { widthBefore: Math.round(widthBefore), widthAfter: Math.round(widthAfter), height: after.docked, body: after.body }
  })
  await check('1280x800 切回浮窗：能拖、能点「以前的对话」、收成小球再开', async () => {
    await page.getByRole('button', { name: '浮起来', exact: true }).click()
    const floating = page.getByTestId('editorial-floating')
    await expect(floating).toBeVisible()
    await expect(page.locator('[data-testid="editorial-floating"] div.space-y-5.overflow-y-auto')).toBeVisible()
    const was = await floating.boundingBox()
    const title = await page.getByTestId('editorial-title').boundingBox()
    await page.mouse.move(title.x + title.width / 2, title.y + title.height / 2)
    await page.mouse.down()
    // 往左上拖 140/16：离右边缘远（贴右吸附 48px）、也在 y≥64 的下限里
    await page.mouse.move(title.x + title.width / 2 - 140, title.y + title.height / 2 - 16, { steps: 8 })
    await page.mouse.up()
    const moved = await floating.boundingBox()
    assert.ok(Math.abs((moved.x - was.x) + 140) < 4 && Math.abs((moved.y - was.y) + 16) < 4, `按住标题栏空白处还能拖（${Math.round(was.x)},${Math.round(was.y)} → ${Math.round(moved.x)},${Math.round(moved.y)}）`)
    await page.getByRole('button', { name: '以前的对话', exact: true }).click()
    const list = page.getByRole('listbox', { name: '以前的对话' })
    await expect(list).toBeVisible()
    // 列表按最近在前：挑标题叫「合成旧对话」的那段（昨天的那段），不是正在聊的这段
    await list.getByRole('option').filter({ hasText: '合成旧对话' }).click()
    await expect(page.getByText(/以前的对话「合成旧对话」/)).toBeVisible()
    await page.getByRole('button', { name: '回到最近的' }).click()
    await expect(page.getByText(/以前的对话「合成旧对话」/)).toHaveCount(0)
    await page.getByRole('button', { name: '收起', exact: true }).click()
    await expect(page.locator('[role="button"][title="编辑部"]')).toBeVisible()
    await page.locator('[role="button"][title="编辑部"]').click()
    await expect(page.getByTestId('editorial-floating')).toBeVisible()
    await page.getByRole('button', { name: '贴到右边', exact: true }).click()
    await expect(aside()).toBeVisible()
    return { dragged: [Math.round(was.x), Math.round(was.y)], movedTo: [Math.round(moved.x), Math.round(moved.y)] }
  })
  // 验收截图：拆的书·设定页、1280×800、聊天滚到一半、输入框在右栏最下面
  await tab('设定').click()
  await expect.poll(() => page.locator('header.top nav a.on').textContent()).toBe('设定')
  await scrollTo((await scrollMax()) / 2)
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(SHOT, '小修4-贴右输入框.png') })
  assert.deepEqual(errors, [], `页面错误 0（实际 ${errors}）`)
  assert.deepEqual(external, [], `外网请求 0（实际 ${external}）`)
  const posts = api.filter(request => request.startsWith('POST'))
  assert.ok(posts.every(request => /\/notes$/.test(request.split(' ')[1])), `只有发消息是写请求（实际 ${posts}）`)
  fs.writeFileSync(path.join(OUT, 'editorial-dock-height-results.json'), JSON.stringify({ at: new Date().toISOString(), base: BASE, api: API, results, apiRequests: [...new Set(api)], posts }, null, 2))
  console.log(`PASS 全部 ${results.length} 组；页面错误 0；外网 0；写请求 ${posts.length} 次（都是发消息）`)
} finally {
  await browser.close()
}
