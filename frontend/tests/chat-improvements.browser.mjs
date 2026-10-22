/** 聊天改进任务 1：真实独立后端 + 演示模型；产品写入只经鼠标/键盘，GET 仅核对。
 * TEST_BASE_URL=http://127.0.0.1:4381 CHAT_FIXTURE=<fixture.json> node tests/chat-improvements.browser.mjs
 * fixture: {new_book_id, teardown_book_id, fixtures:{new:{chat_note_id, failed_note_id,
 * requirement_note_id, requirement_id, changed_note_id, too_late_note_id?},teardown:{chat_note_id}}}
 * 失败发送/剪贴板拒绝仅作明确的故障注入，不替代主路径 demo 验收。只产出任务规定的三张截图。
 */
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect as baseExpect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const base = process.env.TEST_BASE_URL
assert.ok(base, '必须指定独立 TEST_BASE_URL')
const origin = new URL(base)
assert.ok(['127.0.0.1', 'localhost'].includes(origin.hostname))
assert.ok(origin.port && !['8000', '4320'].includes(origin.port), '禁止连接日常服务')
const fixturePath = resolve(process.env.CHAT_FIXTURE || resolve(root, 'data/chat-improvements-task1/fixture.json'))
const fixture = JSON.parse(await readFile(fixturePath, 'utf8'))
const books = [{ kind: 'new', id: fixture.new_book_id }, { kind: 'teardown', id: fixture.teardown_book_id }]
assert.ok(books.every(book => typeof book.id === 'string' && book.id.length))
assert.notEqual(books[0].id, books[1].id)
const data = resolve(process.env.TEST_ARTIFACT_DIR || dirname(fixturePath))
const output = resolve(process.env.TEST_SCREENSHOT_DIR || resolve(root, 'docs/聊天改进验收'))
const profile = resolve(data, `browser-profile-${Date.now()}`)
await Promise.all([mkdir(data, { recursive: true }), mkdir(output, { recursive: true })])
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.ZHIBI_CHROMIUM || ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync)
const expect = baseExpect.configure({ timeout: 30_000 })
const evidence = { base, fixture: fixturePath, checks: [], screenshots: [], requests: [], errors: [], blocked: [], faults: [], demoCalls: [] }
let context, page
const record = (name, detail = {}) => { evidence.checks.push({ name, ...detail }); console.log(`PASS ${name}`) }

async function launch() {
  context = await chromium.launchPersistentContext(profile, { headless: true, executablePath, viewport: { width: 1500, height: 1050 }, reducedMotion: 'reduce', serviceWorkers: 'block', permissions: ['clipboard-read', 'clipboard-write'] })
  await context.route('**/*', route => {
    const url = new URL(route.request().url())
    if (['http:', 'https:'].includes(url.protocol) && url.origin !== origin.origin) {
      evidence.blocked.push(route.request().url())
      return route.abort('blockedbyclient')
    }
    return route.continue()
  })
  context.on('page', observe)
  page = context.pages()[0] || await context.newPage()
  observe(page)
}
const observed = new WeakSet()
function observe(tab) {
  if (observed.has(tab)) return
  observed.add(tab)
  tab.on('pageerror', error => evidence.errors.push(error.message))
  tab.on('request', request => {
    if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method())) evidence.requests.push({ method: request.method(), url: request.url(), body: request.postDataJSON() })
  })
}
const get = async route => { const response = await context.request.get(`${base}/api${route}`); assert.equal(response.status(), 200, route); return response.json() }
const history = id => get(`/books/${id}/meeting?limit=2000`)
const composer = () => page.getByLabel('给编辑部发消息', { exact: true })
const composerArea = () => composer().locator('..').locator('..')
const inline = () => page.getByTestId('chat-inline-edit')
const messages = () => page.getByTestId('chat-messages')
const panel = () => page.locator('[data-testid="editorial-floating"], [data-testid="editorial-docked"]')
const draftKey = id => `zhibi.chat-draft.${id}`
const stored = id => page.evaluate(key => localStorage.getItem(key), draftKey(id))
async function type(input, text) { await input.click(); await input.press('ControlOrMeta+A'); await page.keyboard.insertText(text) }
async function open(id) {
  await page.goto(`${base}/desk/${id}`)
  const ball = page.locator('[role="button"][title="编辑部"]')
  await expect(ball.or(composer())).toBeVisible()
  if (await ball.isVisible()) await ball.click()
  await expect(composer()).toBeVisible()
}
async function role(name) {
  await composerArea().getByRole('button', { name: '点名', exact: true }).click()
  await page.getByRole('listbox', { name: '点名让谁来答', exact: true }).getByRole('option').filter({ hasText: name }).click()
  await expect(composerArea().getByText(`问${name}`, { exact: false })).toBeVisible()
}
async function send(id, text, selectedRole) {
  if (selectedRole) await role(selectedRole)
  await type(composer(), text)
  const response = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/books/${id}/notes`)
  await composer().press('Enter')
  const posted = await response
  assert.equal(posted.status(), 201)
  const note = await posted.json()
  await expect(composer()).toHaveValue('')
  return note
}
async function replyFor(id, note) {
  let reply
  await expect.poll(async () => {
    reply = (await history(id)).findLast(message => !message.payload?.dropped && message.payload?.reply_to?.includes(note.id))
    return reply?.id
  }, { timeout: 90_000 }).toBeTruthy()
  const locator = page.getByTestId(`reply-${reply.id}`)
  await expect(locator).toHaveAttribute('data-state', 'done', { timeout: 90_000 })
  reply = (await history(id)).find(message => message.id === reply.id)
  return { message: reply, locator }
}
async function shot(file) {
  assert.ok(!evidence.screenshots.includes(file), '每张验收截图只写一次')
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: resolve(output, file) })
  evidence.screenshots.push(file)
}
async function copy(locator, expected, screenshot = false) {
  await locator.scrollIntoViewIfNeeded()
  await locator.hover()
  const button = locator.getByRole('button', { name: '复制', exact: true })
  await button.click()
  await expect(locator.getByRole('button', { name: '已复制', exact: true })).toBeVisible()
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), expected)
  if (screenshot) await shot('任务1-02-复制与重新回答.png')
  await expect(button).toBeVisible({ timeout: 4000 })
}
async function edit(note) {
  const bubble = page.getByTestId(`note-${note.id}`)
  await bubble.scrollIntoViewIfNeeded()
  await bubble.hover()
  await bubble.getByRole('button', { name: '修改', exact: true }).click()
  await expect(inline()).toBeVisible()
  await expect(inline().getByLabel('修改这句话')).toHaveValue(note.content)
  return bubble
}
async function bottom() {
  const jump = page.getByRole('button', { name: /^(回到最新|有新回答)$/ })
  if (await jump.isVisible()) await jump.click()
  else {
    const box = await messages().boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, 100000)
  }
  await expect.poll(() => messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThanOrEqual(48)
}
async function wheelUp() {
  const box = await messages().boundingBox()
  assert.ok(box)
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -750)
  await expect.poll(() => messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeGreaterThan(48)
}

async function followingLatest() {
  await expect.poll(() => messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThanOrEqual(48)
  await expect(page.getByRole('button', { name: /^(回到最新|有新回答)$/ })).toHaveCount(0)
  return messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)
}

async function outcomes(book) {
  const ids = fixture.fixtures?.[book.kind] || {}
  if (ids.chat_note_id) await expect(page.getByTestId(`outcome-${ids.chat_note_id}`)).toHaveCount(0)
  {
    for (const key of ['failed_note_id', 'requirement_note_id', 'requirement_id', 'changed_note_id']) assert.ok(ids[key], `fixture 缺 ${key}`)
    const failed = page.getByTestId(`outcome-${ids.failed_note_id}`)
    await failed.scrollIntoViewIfNeeded()
    await expect(failed).toHaveText('没判断出这句话要做什么（隔离验收原因），书没改。换个说法再说一次试试。')
    await expect(failed.getByRole('button')).toHaveCount(0)
    const requirement = page.getByTestId(`outcome-${ids.requirement_note_id}`)
    await requirement.scrollIntoViewIfNeeded()
    await expect(requirement).toContainText('加了一条写作要求')
    await requirement.getByRole('button', { name: '改一下', exact: true }).click()
    const dialog = page.getByRole('dialog')
    const beforeRequirement = (await get(`/books/${book.id}/requirements`)).find(row => row.id === ids.requirement_id)
    assert.ok(beforeRequirement)
    const updated = '隔离验收：人物说话简洁，语气仍须符合身份。'
    await type(dialog.getByRole('textbox'), updated)
    const saving = page.waitForResponse(response => response.request().method() === 'PATCH' && new URL(response.url()).pathname === `/api/requirements/${ids.requirement_id}`)
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    if (book.kind === 'teardown') {
      // 拆书现有接口明确不允许新增/修改写作要求；这是保护用例，不假装能保存。
      assert.equal((await saving).status(), 409)
      await expect(dialog.getByText('拆的书里不能加写作要求：原文和大纲结构照原书来，编辑部只回答问题。', { exact: true })).toBeVisible()
      assert.deepEqual((await get(`/books/${book.id}/requirements`)).find(row => row.id === ids.requirement_id), beforeRequirement)
      await dialog.getByRole('button', { name: '取消', exact: true }).click()
    } else {
      assert.equal((await saving).status(), 200)
      await expect.poll(async () => (await get(`/books/${book.id}/requirements`)).find(row => row.id === ids.requirement_id)?.text).toBe(updated)
    }
    await expect(dialog).toHaveCount(0)
    const warningNote = page.getByTestId(`note-${ids.changed_note_id}`)
    await warningNote.scrollIntoViewIfNeeded()
    await warningNote.hover()
    await warningNote.getByRole('button', { name: '修改', exact: true }).click()
    const warning = warningNote.getByRole('alertdialog')
    await expect(warning).toContainText(/^这句和后面的话改过书（\d+ 处）。改了重发，聊天退回这里，书不跟着退：要退书，用那几处下面的「换回原来的」，或者去「存档」。/)
    await warning.getByRole('button', { name: '算了', exact: true }).click()
    await expect(inline()).toHaveCount(0)
    await warningNote.hover()
    await warningNote.getByRole('button', { name: '修改', exact: true }).click()
    await warning.getByRole('button', { name: '接着改', exact: true }).click()
    await expect(inline()).toBeVisible()
    await inline().getByRole('button', { name: '取消', exact: true }).click()
    if (ids.too_late_note_id) await expect(page.getByTestId(`outcome-${ids.too_late_note_id}`)).toHaveText('编辑部在等你拍板，这句话没改书。要改，就在拍板的地方提意见，或者说「总结一下」整理成方案。')
    record(`${book.kind}: failed无按钮、${book.kind === 'teardown' ? '要求弹框可开但保存被现有保护拒绝且原值不变' : '要求可修改'}、改过书确认可取消/接着改、等拍板新字`, { requirementSave: book.kind === 'teardown' ? 'existing-readonly-guard-409' : 'saved-200' })
  }
  await expect(page.getByRole('button', { name: '其实要记下', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '记成写作要求', exact: true })).toHaveCount(0)
  assert.equal((await page.locator('body').innerText()).includes('其实要记下'), false)
  record(`${book.kind}: 普通聊天整行不渲染、手动记下按钮不存在`)
}

async function conversation(book) {
  await bottom()
  const first = await send(book.id, '这段合成故事的主人公心情如何？', '主编')
  const firstReply = await replyFor(book.id, first)
  const second = await send(book.id, '前面的合成故事发生在什么地方？')
  const secondReply = await replyFor(book.id, second)
  await composer().click()
  await page.mouse.move(400, 100)
  await expect.poll(() => firstReply.locator.getByRole('button', { name: '复制', exact: true }).locator('..').evaluate(el => Number(getComputedStyle(el).opacity))).toBe(0)
  await expect.poll(() => secondReply.locator.getByRole('button', { name: '复制', exact: true }).locator('..').evaluate(el => Number(getComputedStyle(el).opacity))).toBe(1)
  await copy(page.getByTestId(`note-${first.id}`), first.content)
  assert.equal(first.payload.ask, 'chief')
  await copy(firstReply.locator, firstReply.message.content)
  await expect(firstReply.locator.getByRole('button', { name: '重新回答', exact: true })).toHaveCount(0)
  await expect(secondReply.locator.getByRole('button', { name: '重新回答', exact: true })).toBeVisible()
  await copy(secondReply.locator, secondReply.message.content, book.kind === 'new')
  record(`${book.kind}: 作者/早期/最新回答纯文字复制及两秒恢复`, { author: first.id, oldReply: firstReply.message.id, latestReply: secondReply.message.id })

  const draft = `${book.kind}：底下尚未发送的草稿，不参与上面修改。`
  await type(composer(), draft)
  const requestsBefore = evidence.requests.length
  const bubble = await edit(first)
  await expect(inline().getByText('问主编', { exact: false })).toBeVisible()
  await expect(composer()).toHaveValue(draft)
  const bottomSend = composerArea().getByRole('button', { name: '发送', exact: true })
  await expect(bottomSend).toBeDisabled()
  await expect(bottomSend).toHaveAttribute('title', '先发出或取消上面正在改的那句')
  await expect(page.getByTestId(`note-${second.id}`).getByRole('button', { name: '修改', exact: true })).toHaveCount(0)
  assert.equal(await bubble.locator('..').evaluate(el => Number(getComputedStyle(el).opacity)), 1)
  await expect.poll(() => secondReply.locator.locator('..').evaluate(el => Number(getComputedStyle(el).opacity))).toBe(0.35)
  if (book.kind === 'new') {
    // 用真实滚轮把原地编辑整块置于消息区中间，截图不裁掉框的上沿。
    const listBox = await messages().boundingBox(), editBox = await inline().boundingBox()
    await page.mouse.move(listBox.x + 12, listBox.y + listBox.height / 2)
    await page.mouse.wheel(0, editBox.y + editBox.height / 2 - listBox.y - listBox.height / 2)
    await expect.poll(async () => {
      const box = await inline().boundingBox(), list = await messages().boundingBox()
      return box.y >= list.y && box.y + box.height <= list.y + list.height
    }).toBe(true)
    await shot('任务1-01-作者原地修改.png')
  }
  // Chromium自动化不能启动系统中文输入法；只在此补发原生isComposing事件检查保护分支。
  const imeRequests = evidence.requests.length
  await inline().getByLabel('修改这句话').evaluate(el => el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, isComposing: true })))
  await expect(inline()).toBeVisible()
  await expect(inline().getByLabel('修改这句话')).toHaveValue(first.content)
  assert.equal(evidence.requests.length, imeRequests)
  evidence.faults.push({ kind: 'ime-native-keyboard-event', book: book.id, purpose: '合成isComposing事件不发送；其他编辑路径为真实键鼠' })
  await inline().getByLabel('修改这句话').press('ControlOrMeta+End')
  await inline().getByLabel('修改这句话').press('Shift+Enter')
  await expect(inline().getByLabel('修改这句话')).toHaveValue(`${first.content}\n`)
  await inline().getByLabel('修改这句话').press('Escape')
  await expect(inline()).toHaveCount(0)
  await expect(bubble).toContainText(first.content)
  await edit(first)
  await type(inline().getByLabel('修改这句话'), '这段取消后不应保存。')
  await inline().getByRole('button', { name: '取消', exact: true }).click()
  await expect(inline()).toHaveCount(0)
  assert.equal(evidence.requests.length, requestsBefore, 'Esc/取消不发写请求')
  await expect(composer()).toHaveValue(draft)
  record(`${book.kind}: 原地编辑、名牌、Shift+Enter、Esc/取消、底部草稿和禁发、仅后续变淡`)

  await edit(first)
  const revised = '这段合成故事的主人公为什么沉默？'
  await type(inline().getByLabel('修改这句话'), revised)
  const notesURL = `${base}/api/books/${book.id}/notes`
  await page.route(notesURL, route => route.fulfill({ status: 409, json: { detail: '隔离验收：本次发送暂未成功' } }), { times: 1 })
  await inline().getByRole('button', { name: '发送', exact: true }).click()
  await expect(panel().getByText('隔离验收：本次发送暂未成功', { exact: true })).toBeVisible()
  await expect(inline().getByLabel('修改这句话')).toHaveValue(revised)
  await expect(inline().getByText('问主编', { exact: false })).toBeVisible()
  evidence.faults.push({ kind: 'notes-409', book: book.id, purpose: '发送失败后内联字和点名不丢' })
  const responsePromise = page.waitForResponse(response => response.request().method() === 'POST' && response.url() === notesURL && response.status() === 201)
  await inline().getByLabel('修改这句话').press('Enter')
  const response = await responsePromise
  const changed = await response.json()
  assert.equal(response.request().postDataJSON().rewind_from, first.id)
  assert.equal(changed.payload.ask, 'chief')
  await expect(inline()).toHaveCount(0)
  await replyFor(book.id, changed)
  await expect(page.getByTestId(`note-${first.id}`)).toHaveCount(0)
  await expect(page.getByTestId(`note-${second.id}`)).toHaveCount(0)
  const after = await history(book.id)
  assert.equal(after.find(message => message.id === first.id).payload.dropped, true)
  assert.equal(after.find(message => message.id === second.id).payload.dropped, true)
  await expect(composer()).toHaveValue(draft)
  record(`${book.kind}: 409不丢字、Enter沿rewind发送、原点名保留、后续聊天收起`)

  await edit(changed)
  await inline().getByRole('button', { name: '不点名了', exact: true }).click()
  await expect(inline().getByText('问主编', { exact: false })).toHaveCount(0)
  await type(inline().getByLabel('修改这句话'), '@设定师 合成故事里那盏灯是什么颜色？')
  const mentionResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url() === notesURL && response.status() === 201)
  await inline().getByRole('button', { name: '发送', exact: true }).click()
  const mentioned = await (await mentionResponse).json()
  assert.equal(mentioned.payload.ask, 'lorekeeper')
  assert.equal(mentioned.content, '合成故事里那盏灯是什么颜色？')
  await replyFor(book.id, mentioned)
  record(`${book.kind}: 修改可移除原点名并识别开头@设定师`)
  await type(composer(), '')
  await expect.poll(() => stored(book.id)).toBeNull()

  await page.emulateMedia({ reducedMotion: 'no-preference' })
  for (const mode of ['float', 'side']) {
    const switcher = page.getByRole('button', { name: mode === 'float' ? '浮起来' : '贴到右边', exact: true })
    if (await switcher.isVisible()) await switcher.click()
    await bottom()
    await wheelUp()
    await expect(page.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '有新回答', exact: true })).toHaveCount(0)
    await bottom()
    const note = await send(book.id, '灯光\n影子\n人物\n街道\n场景\n是什么样？', '主编')
    const liveReply = page.locator('[data-testid^="reply-"][data-state="streaming"]').last()
    await expect(liveReply).toBeVisible()
    await expect(liveReply.getByRole('button', { name: '复制', exact: true })).toHaveCount(0)
    await wheelUp()
    const jump = page.getByRole('button', { name: '有新回答', exact: true })
    await expect(jump).toBeVisible()
    assert.ok(await messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight > 48), '流式增长不拽回底部')
    if (book.kind === 'new' && mode === 'float') await shot('任务1-03-有新回答.png')
    await jump.click()
    await expect(jump).toHaveCount(0)
    await replyFor(book.id, note)
    await expect.poll(() => messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThanOrEqual(48)
    record(`${book.kind}/${mode}: 正在写无复制、真滚轮上翻、有新回答、点后平滑回底并继续跟随`)
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
}

async function authorInitiatedReplies(book) {
  await bottom()
  await type(composer(), '合成故事里的灯光和街道有什么关系？')
  await role('主编')
  await wheelUp()
  const beforeSend = await messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  const notesURL = `${base}/api/books/${book.id}/notes`
  const sentResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url() === notesURL)
  // 滚轮不夺走底部输入框焦点；直接键盘发送，不让定位器替测试先滚到底。
  await expect(composer()).toBeFocused()
  await page.keyboard.press('Enter')
  const posted = await sentResponse
  assert.equal(posted.status(), 201)
  const note = await posted.json()
  await expect(composer()).toHaveValue('')
  const afterSend = await followingLatest()
  await replyFor(book.id, note)
  const afterReply = await followingLatest()
  record(`${book.kind}: 上翻超过48px后底部发送成功立即回底、回答跟到底、无回到最新或有新回答`, { beforeSend, afterSend, afterReply })

  await edit(note)
  const input = inline().getByLabel('修改这句话')
  await expect(input).toBeFocused()
  await expect.poll(() => input.evaluate(el => ({ start: el.selectionStart, end: el.selectionEnd, length: el.value.length })))
    .toEqual({ start: note.content.length, end: note.content.length, length: note.content.length })
  record(`${book.kind}: 点修改后原地输入框获焦、光标两端都在原话末尾`, { length: note.content.length })
  await type(input, '合成故事里的灯光为什么让街道显得安静？')
  await wheelUp()
  const beforeRewind = await messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)
  await expect(input).toBeFocused()
  const changedResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url() === notesURL)
  await page.keyboard.press('Enter')
  const changedPost = await changedResponse
  assert.equal(changedPost.status(), 201)
  assert.equal(changedPost.request().postDataJSON().rewind_from, note.id)
  const revised = await changedPost.json()
  await expect(inline()).toHaveCount(0)
  const afterRewind = await followingLatest()
  const revisedReply = await replyFor(book.id, revised)
  const afterRevisedReply = await followingLatest()
  record(`${book.kind}: 上翻超过48px后原地修改Enter成功回底、回答跟到底、无回到最新或有新回答`, { beforeRewind, afterRewind, afterRevisedReply })

  const again = revisedReply.locator.getByRole('button', { name: '重新回答', exact: true })
  await composer().click()
  // 真键盘逆向Tab聚焦最新回答的按钮，再上翻后Enter触发原生click。
  // 不能直接again.click()，它会为可见性自动滚动，让缺少产品回底逻辑也假通过。
  for (let tabs = 0; tabs < 8 && !(await again.evaluate(el => el === document.activeElement)); tabs++) {
    await page.keyboard.press('Shift+Tab')
  }
  await expect(again).toBeFocused()
  await wheelUp()
  const beforeAgain = await messages().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)
  await expect(again).toBeFocused()
  const againResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/books/${book.id}/chat/replies/${revisedReply.message.id}/again`)
  await page.keyboard.press('Enter')
  const immediatelyAfterAgain = await followingLatest()
  assert.equal((await againResponse).status(), 202)
  await expect(revisedReply.locator).toHaveAttribute('data-state', /thinking|streaming/)
  await replyFor(book.id, revised)
  const afterAgainReply = await followingLatest()
  record(`${book.kind}: 上翻超过48px后重新回答原生click立即回底、回答继续跟到底`, { beforeAgain, immediatelyAfterAgain, afterAgainReply, activation: 'keyboard-Enter-native-click' })
}

async function inFlightDrafts(book) {
  for (const change of [false, true]) {
    await bottom()
    const sent = '这段合成故事为什么安静？'
    await type(composer(), sent)
    await role('主编')
    let release, arrived
    const gate = new Promise(resolve => { release = resolve })
    const posted = new Promise(resolve => { arrived = resolve })
    const notesURL = `${base}/api/books/${book.id}/notes`
    await page.route(notesURL, async route => {
      const response = await route.fetch()
      const note = await response.json()
      arrived(note)
      await gate
      await route.fulfill({ response })
    }, { times: 1 })
    await composer().press('Enter')
    const note = await posted
    await page.getByRole('button', { name: '收起', exact: true }).first().click()
    await page.locator('[role="button"][title="编辑部"]').click()
    await expect(composer()).toHaveValue(sent)
    if (change) {
      await type(composer(), '这是发送在途时新写的下一条草稿。')
      await role('审稿')
    }
    release()
    if (change) {
      await expect(composer()).toHaveValue('这是发送在途时新写的下一条草稿。')
      await expect(composerArea().getByText('问审稿', { exact: false })).toBeVisible()
      await replyFor(book.id, note)
      await expect(composer()).toHaveValue('这是发送在途时新写的下一条草稿。')
      await expect(composerArea().getByText('问审稿', { exact: false })).toBeVisible()
    } else {
      await expect(composer()).toHaveValue('')
      await expect.poll(() => stored(book.id)).toBeNull()
      await replyFor(book.id, note)
    }
    evidence.faults.push({ kind: 'delayed-notes-response', book: book.id, newDraft: change, purpose: '真实API已接收后暂缓响应，收起重开不丢新稿且不留已发旧稿' })
    record(`${book.kind}: 发送响应在途收球重开${change ? '保留新草稿与新点名' : '成功清掉旧已发草稿'}`)
    await type(composer(), '')
    const clear = composerArea().getByRole('button', { name: '不点名了', exact: true })
    if (await clear.isVisible()) await clear.click()
  }
}

async function drafts(book) {
  const text = `${book.kind}独立草稿：这句话刷新后再讨论。`
  await type(composer(), text)
  await role('审稿')
  const check = async () => {
    await expect(composer()).toHaveValue(text)
    await expect(composerArea().getByText('问审稿', { exact: false })).toBeVisible()
    assert.ok(await stored(book.id))
  }
  await check()
  await page.getByRole('button', { name: '收起', exact: true }).first().click()
  await page.locator('[role="button"][title="编辑部"]').click()
  await check()
  for (const name of ['浮起来', '贴到右边']) {
    const button = page.getByRole('button', { name, exact: true })
    if (await button.isVisible()) await button.click()
    await check()
  }
  for (const tab of ['简介', '设定', '大纲', '正文']) {
    await page.locator('.desk-v2 .top .tabs').getByText(tab, { exact: true }).click()
    await check()
  }
  await page.reload()
  await check()
  await context.close()
  await launch()
  await open(book.id)
  await check()
  record(`${book.kind}: 草稿与点名经小球、浮侧栏、四书页、刷新、关闭浏览器重开仍在`)
  const note = await send(book.id, text)
  await replyFor(book.id, note)
  await expect(composer()).toHaveValue('')
  await expect(composerArea().getByText('问审稿', { exact: false })).toHaveCount(0)
  await expect.poll(() => stored(book.id)).toBeNull()
  await type(composer(), '删除测试草稿')
  assert.ok(await stored(book.id))
  await type(composer(), '')
  await expect.poll(() => stored(book.id)).toBeNull()
  record(`${book.kind}: 正常发送清草稿/点名、删光清localStorage`)
}

async function clipboardFaults(book) {
  const note = (await history(book.id)).findLast(message => message.speaker === 'author' && message.kind === 'note' && !message.payload?.dropped)
  const bubble = page.getByTestId(`note-${note.id}`)
  await page.evaluate(() => {
    window.__clipboardOriginal = navigator.clipboard.writeText
    window.__copyOriginal = document.execCommand
    navigator.clipboard.writeText = async () => { throw new DOMException('隔离验收权限拒绝', 'NotAllowedError') }
  })
  try {
    await copy(bubble, note.content)
    await page.evaluate(() => { document.execCommand = () => false })
    await bubble.getByRole('button', { name: '复制', exact: true }).click()
    await expect(bubble.getByRole('button', { name: '没复制上，选中文字手动复制', exact: true })).toBeVisible()
    await expect(bubble.getByRole('button', { name: '复制', exact: true })).toBeVisible({ timeout: 5000 })
    evidence.faults.push({ kind: 'clipboard-rejection', purpose: '原生clipboard拒绝退到execCommand；两者失败显示三秒反馈' })
    record('new: 剪贴板权限拒绝的textarea退路与完全失败三秒反馈')
  } finally {
    await page.evaluate(() => { navigator.clipboard.writeText = window.__clipboardOriginal; document.execCommand = window.__copyOriginal; delete window.__clipboardOriginal; delete window.__copyOriginal })
  }
}

try {
  await launch()
  const profiles = await get('/llm/profiles')
  assert.ok(profiles.every(profile => profile.provider === 'demo'), '独立环境只允许演示模型')
  for (const book of books) {
    assert.equal((await get(`/books/${book.id}`)).source, book.kind)
    await open(book.id)
    await outcomes(book)
    await conversation(book)
    await authorInitiatedReplies(book)
    await drafts(book)
    await inFlightDrafts(book)
    if (book.kind === 'new') await clipboardFaults(book)
  }
  // 真正换书，而不是只检查不同 key：每本书留下不同文字和不同点名后往返。
  const cross = [{ ...books[0], text: '新书专属草稿，不能串到拆书。', role: '设定师' }, { ...books[1], text: '拆书专属草稿，不能串到新书。', role: '写手' }]
  for (const item of cross) { await open(item.id); await type(composer(), item.text); await role(item.role) }
  for (const item of cross) {
    await page.getByRole('button', { name: '换一本书', exact: true }).click()
    await page.getByRole('listbox', { name: '换一本书', exact: true }).locator(`a[href="/desk/${item.id}"]`).click()
    await expect(composer()).toHaveValue(item.text)
    await expect(composerArea().getByText(`问${item.role}`, { exact: false })).toBeVisible()
  }
  record('两本书通过真实换书菜单往返：草稿和点名互不串')
  for (const book of books) {
    const calls = (await get(`/llm-calls?book_id=${book.id}&limit=100`)).items
    assert.ok(calls.length, '真实demo调用必须有记录')
    assert.ok(calls.every(call => call.model === 'demo'), '不得调用真实模型')
    evidence.demoCalls.push({ book: book.id, count: calls.length, models: [...new Set(calls.map(call => call.model))] })
  }
  assert.deepEqual(evidence.errors, [])
  assert.deepEqual(evidence.blocked, [])
  assert.equal(evidence.screenshots.length, 3)
  evidence.complete = true
  console.log(`PASS ${evidence.checks.length} 组；仅 demo；3 张截图；无页面异常`)
} catch (error) {
  evidence.failure = { message: error.message, page: page?.url(), body: await page?.locator('body').innerText().catch(() => '') }
  throw error
} finally {
  await writeFile(resolve(data, 'browser-results.json'), JSON.stringify(evidence, null, 2))
  await context?.close()
}
