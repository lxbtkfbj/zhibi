/** 新书页装修：仅独立 4351/8051 中的新建作者测试书写操作；已有作者书只读截图。无模型调用。 */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '../..')
const BASE = process.env.ZHIBI_DESK_URL ?? 'http://127.0.0.1:4351'
const API = process.env.ZHIBI_DESK_API ?? 'http://127.0.0.1:8051/api'
if (new URL(BASE).port !== '4351' || new URL(API).port !== '8051') throw new Error('作者验收只允许本次独立端口 4351/8051')
const OUT = path.join(ROOT, 'docs/新书页装修验收')
const DATA = path.join(ROOT, 'data/desk-v2')
fs.mkdirSync(OUT, { recursive: true }); fs.mkdirSync(DATA, { recursive: true })
const evidence = { at: new Date().toISOString(), base: BASE, api: API, writesOnlyNewBook: true, modelCalls: [], errors: [], checks: [], screenshots: [] }
const api = async (suffix, body, method = body === undefined ? 'GET' : 'POST') => {
  const response = await fetch(API + suffix, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const text = await response.text()
  if (!response.ok) throw new Error(`${method} ${suffix}: ${response.status} ${text}`)
  return text ? JSON.parse(text) : null
}
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex')
const originals = (await api('/books')).filter(book => book.source !== 'teardown' && !book.title.startsWith('新书页装修交互验收'))
async function snapshot(id) { return Promise.all(['', '/library', '/outline-tree', '/bible', '/chapters'].map(suffix => api(`/books/${id}${suffix}`))).then(digest) }
const before = Object.fromEntries(await Promise.all(originals.map(async book => [book.id, await snapshot(book.id)])))
const stateFile = path.join(DATA, 'author-smoke-state.json')
let state = process.env.ZHIBI_AUTHOR_REUSE && fs.existsSync(stateFile) ? JSON.parse(fs.readFileSync(stateFile, 'utf8')) : null
if (!state) {
  const { book } = await api('/books', { start_setup: false, title: `新书页装修交互验收 ${new Date().toISOString().slice(0, 19)}`, blurb: '作者亲手留下的一段简介，用于验证装修后仍能手改。', channel: '男频', genre: '玄幻', tags: ['成长'], target_length: 20 })
  const hero = await api(`/books/${book.id}/characters`, { name: '验收主角', one_line: '作者手写的主角', appearance: '灰衣少年，腰间系着旧木剑。', background: '从山村出来寻找失踪的兄长。', role_type: '主角', extra: { 所属: '青山村' } })
  const friend = await api(`/books/${book.id}/characters`, { name: '验收同伴', one_line: '一起离村的伙伴', personality: '直爽，不说假话。' })
  const volume = await api(`/books/${book.id}/volumes`, { title: '走出山村', summary: '离开故乡，找到第一条线索。', chapter_count: 0 })
  const unit = await api(`/volumes/${volume.id}/units`, { title: '夜雨中的约定', summary: '一封旧信让两位少年决定离村。', chapter_count: 0 })
  const chapter = await api(`/units/${unit.id}/chapters`, { title: '山门来客', outline: { goal: '来客带来旧信，少年决定出发。', cool_point: '木剑上的印记第一次发亮。', hook: '信封背后藏着另一行字。' } })
  state = { book: book.id, hero: hero.id, friend: friend.id, volume: volume.id, unit: unit.id, chapter: chapter.index ?? 1 }
  fs.writeFileSync(stateFile, JSON.stringify(state, null, 2))
}
evidence.testBook = state
const current = await api(`/books/${state.book}`)
assert.ok(current.title.startsWith('新书页装修交互验收') && current.source !== 'teardown')
const executablePath = process.env.ZHIBI_CHROMIUM ?? ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Users/cxc/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe'].find(fs.existsSync)
const browser = await chromium.launch({ headless: true, executablePath })
const context = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 })
await context.addInitScript(() => { localStorage.setItem('zhibi:editorial-dock', 'ball'); localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 })) })
const page = await context.newPage()
page.on('pageerror', error => evidence.errors.push(String(error)))
page.on('request', request => { if (request.method() === 'POST' && /\/(?:draft|fill|split|write|book-drafts|library\/rewrite|meeting\/messages)(?:[/?-]|$)/.test(new URL(request.url()).pathname)) evidence.modelCalls.push(request.url()) })
const check = name => { evidence.checks.push(name); console.log('PASS', name) }
const library = () => api(`/books/${state.book}/library`)
const character = async id => (await library()).characters.find(person => person.id === id)
const relationships = async () => (await api(`/books/${state.book}/bible`)).relationships
async function position(book, selected) {
  await page.goto(BASE)
  await page.evaluate(({ book, selected }) => sessionStorage.setItem(`zhibi:workspace-reading:${book}`, JSON.stringify({ tab: '简介', entry: 'overview', node: 'book', chapter: 'home', open: [], ...selected })), { book, selected })
  await page.goto(`${BASE}/desk/${book}`)
  await page.locator('.desk-v2 .page h1').waitFor()
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(250)
}
async function shot(name) { await page.mouse.move(2, 2); await page.waitForTimeout(200); const file = `extra-author-${name}.png`; await page.screenshot({ path: path.join(OUT, file) }); evidence.screenshots.push(file) }
async function blur(locator) { await locator.evaluate(element => element.blur()) }
try {
  await position(state.book, { tab: '设定', entry: state.hero })
  const card = page.locator(`section[data-entry="${state.hero}"]`)
  const appearance = card.locator('.f').filter({ has: page.getByText('外貌', { exact: true }) }).locator('[contenteditable]')
  await appearance.fill('作者亲手改过：蓝衣少年，旧木剑仍在。'); await blur(appearance)
  await expect.poll(async () => (await character(state.hero)).appearance).toBe('作者亲手改过：蓝衣少年，旧木剑仍在。')
  await card.hover(); await card.getByRole('button', { name: '置顶', exact: true }).click()
  await expect.poll(async () => !!(await character(state.hero)).pinned_at).toBe(true)
  await card.hover(); await card.getByRole('button', { name: '锁住', exact: true }).click()
  await expect.poll(async () => (await character(state.hero)).locked).toBe(true)
  await expect.poll(async () => (await character(state.hero)).appearance).toBe('作者亲手改过：蓝衣少年，旧木剑仍在。')
  await card.hover(); await card.getByRole('button', { name: '解锁', exact: true }).click()
  await expect.poll(async () => (await character(state.hero)).locked).toBe(false)
  check('角色正文手改、置顶、锁/解锁写回真实API且不丢手改')
  await card.getByRole('button', { name: '新增关系', exact: true }).click()
  await page.getByLabel('和谁', { exact: true }).selectOption(state.friend)
  await page.getByLabel('什么关系', { exact: true }).fill('伙伴')
  await page.getByLabel('关系说明', { exact: true }).fill('从青山村一同出发。')
  await page.locator('.settings-sheet').getByRole('button', { name: '新增关系', exact: true }).click()
  await expect.poll(async () => (await relationships()).length).toBe(1)
  await page.locator('.settings-sheet > .settings-close').getByRole('button', { name: '收起', exact: true }).click()
  const relation = page.locator('.rail .ds[contenteditable]')
  await relation.fill('作者补充：彼此信任，但都藏着一封信。'); await blur(relation)
  await expect.poll(async () => (await relationships())[0].description).toBe('作者补充：彼此信任，但都藏着一封信。')
  await page.locator('.rail h3').filter({ hasText: '和别人的关系' }).dblclick()
  await page.locator('.settings-sheet').getByRole('button', { name: '删掉', exact: true }).click()
  await expect.poll(async () => (await relationships()).length).toBe(0)
  await page.locator('.settings-sheet > .settings-close').getByRole('button', { name: '收起', exact: true }).click()
  check('关系新增、手改、删除均写回真实API')

  await position(state.book, { tab: '设定', entry: 'overview' })
  await page.getByRole('button', { name: '新建类别', exact: true }).click()
  await page.getByLabel('类名', { exact: true }).fill('验收遗物')
  await page.getByLabel('样式', { exact: true }).selectOption('card')
  await page.getByLabel('字段', { exact: true }).fill('来历、代价、来历')
  await page.getByRole('button', { name: '建好这一类', exact: true }).click()
  await expect(page.locator('.page h1')).toHaveText('验收遗物')
  await expect.poll(async () => (await library()).categories.find(category => category.name === '验收遗物')?.fields).toEqual(['来历', '代价'])
  check('作者新建类别：卡片样式、自定字段、去重并自动打开')
  await page.getByRole('button', { name: '调整栏目', exact: true }).click()
  const extraColumn = page.getByPlaceholder('加一栏，比如：用法、来历', { exact: true })
  await extraColumn.fill('保管方法'); await extraColumn.press('Enter')
  await expect.poll(async () => (await api(`/books/${state.book}`)).card_layouts?.[(await library()).categories.find(category => category.name === '验收遗物')?.key]?.sections?.some(field => field.label === '保管方法')).toBe(true)
  await page.locator('.settings-sheet > .settings-close').getByRole('button', { name: '收起', exact: true }).click()
  check('自定类别仍可调整栏目并真实保存')

  await position(state.book, { tab: '设定', entry: 'cat:角色列表' })
  await page.getByRole('button', { name: '调整栏目', exact: true }).click()
  const appearanceLabel = page.locator('.settings-sheet input[value="外貌"]')
  await appearanceLabel.fill('衣着')
  await page.locator('.settings-sheet').getByText('正文栏目', { exact: true }).click()
  await expect.poll(async () => (await api(`/books/${state.book}`)).card_layouts?.['角色列表']?.sections?.some(field => field.label === '衣着')).toBe(true)
  await page.locator('.settings-sheet input[value="衣着"]').locator('..').getByRole('button', { name: '往下挪', exact: true }).click()
  await page.locator('.settings-sheet > .settings-close').getByRole('button', { name: '收起', exact: true }).click()
  await page.locator('.toc .row').getByText('验收主角', { exact: true }).click()
  await expect(page.locator('.page .fields .f').filter({ has: page.getByText('衣着', { exact: true }) }).locator('[contenteditable]')).toHaveText('作者亲手改过：蓝衣少年，旧木剑仍在。')
  const renderedLabels = await page.locator('.page .fields .f > .label').allTextContents()
  const savedLabels = (await api(`/books/${state.book}`)).card_layouts['角色列表'].sections.map(field => field.label).filter(label => renderedLabels.includes(label))
  assert.deepEqual(renderedLabels, savedLabels)
  check('作者角色栏目改名/挪位保留原文，纸面按作者自定标签与顺序显示')

  // 只延迟真实创建响应 450ms，不替换请求或响应内容；确保输入跨过 draft -> server id。
  await position(state.book, { tab: '设定', entry: 'cat:角色列表' })
  await page.getByRole('button', { name: '新增人物', exact: true }).click()
  const draft = page.locator('section[data-entry^="draft-"]')
  await expect(draft).toBeVisible()
  await expect(draft.getByRole('button', { name: '置顶', exact: true })).toHaveCount(0)
  await expect(draft.getByRole('button', { name: '锁住', exact: true })).toHaveCount(0)
  await page.route(`**/api/books/${state.book}/characters`, async route => { if (route.request().method() !== 'POST') return route.continue(); const response = await route.fetch(); await new Promise(resolve => setTimeout(resolve, 450)); await route.fulfill({ response }) })
  await draft.locator('h1').fill('验收新人物')
  await draft.getByRole('button', { name: '编辑资料和空栏目', exact: true }).click()
  const oneLine = page.locator('.settings-sheet label').filter({ hasText: /^一句话/ }).locator('[contenteditable]')
  await oneLine.fill('正在输入的内容不能因新ID丢失')
  const identity = await oneLine.evaluate(element => { window.__deskAuthorEditor = element; return element.isConnected })
  assert.equal(identity, true)
  await expect.poll(async () => (await library()).characters.some(person => person.name === '验收新人物')).toBe(true)
  await page.waitForTimeout(700)
  assert.equal(await oneLine.evaluate(element => window.__deskAuthorEditor === element && document.activeElement === element), true)
  await blur(oneLine)
  await expect.poll(async () => (await library()).characters.find(person => person.name === '验收新人物')?.one_line).toBe('正在输入的内容不能因新ID丢失')
  await page.unroute(`**/api/books/${state.book}/characters`)
  await page.locator('.settings-sheet > .settings-close').getByRole('button', { name: '收起', exact: true }).click()
  check('草稿转真实ID时编辑器DOM、焦点及并行手改不丢；无名草稿不误调置顶/锁API')
  const created = (await library()).characters.find(person => person.name === '验收新人物')
  const createdCard = page.locator(`section[data-entry="${created.id}"]`)
  await createdCard.hover(); await createdCard.getByRole('button', { name: '删掉这一条', exact: true }).click()
  await createdCard.getByRole('button', { name: '再点一次删掉', exact: true }).click()
  await expect.poll(async () => (await library()).characters.some(person => person.id === created.id)).toBe(false)
  check('新增测试条目的两次确认删除真实生效')

  // 第 9.6 条：作者日常书只读截图；不改这些书，也不调用任何模型。
  const rich = originals.find(book => book.title === '万古邪帝') ?? originals[0]
  if (!rich) throw new Error('独立副本缺少作者书')
  const tree = await api(`/books/${rich.id}/outline-tree`)
  const volumes = tree.arcs.flatMap(arc => arc.volumes)
  const firstVolume = volumes.find(volume => volume.units?.length)
  const firstUnit = firstVolume?.units.find(unit => unit.chapters?.length)
  const firstChapter = firstUnit?.chapters[0]
  evidence.readonlyAuthorBook = { id: rich.id, title: rich.title }
  const views = [
    ['简介', { tab: '简介' }], ['设定', { tab: '设定', entry: 'overview' }],
    ['卷', { tab: '大纲', node: `v:${firstVolume.id}`, open: ['book', `v:${firstVolume.id}`] }],
    ['单元', { tab: '大纲', node: `u:${firstUnit.id}`, open: ['book', `v:${firstVolume.id}`, `u:${firstUnit.id}`] }],
    ['章', { tab: '大纲', node: `c${firstChapter.index}`, open: ['book', `v:${firstVolume.id}`, `u:${firstUnit.id}`] }],
    ['正文首页', { tab: '正文', chapter: 'home' }],
  ]
  for (const [name, selected] of views) { await position(rich.id, selected); await shot(name) }
  check('已有作者书简介、设定、卷、单元、章、正文首页六张只读截图')
  const after = Object.fromEntries(await Promise.all(originals.map(async book => [book.id, await snapshot(book.id)])))
  assert.deepEqual(after, before)
  evidence.originalAuthorHashes = before
  check('已有三本作者书book/library/outline/bible/chapters前后SHA256完全一致')
  assert.deepEqual(evidence.modelCalls, [])
  assert.deepEqual(evidence.errors, [])
  check('无真实/演示模型调用，无页面异常')
} catch (error) {
  evidence.failure = String(error)
  await page.screenshot({ path: path.join(OUT, 'extra-author-failure.png') }).catch(() => {})
  throw error
} finally {
  fs.writeFileSync(path.join(DATA, 'author-smoke.json'), JSON.stringify(evidence, null, 2))
  await browser.close()
}
