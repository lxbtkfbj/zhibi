/** Task 5: real isolated demo API/worker, mouse/keyboard only; no response/DOM/style replacements. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '../..')
const OUT = path.resolve(process.env.ZHIBI_APPEARANCE_OUT || path.join(ROOT, 'data/chat-improvements-task5'))
const BASE = process.env.ZHIBI_APPEARANCE_BASE || 'http://127.0.0.1:4393'
const url = new URL(BASE)
assert.equal(url.hostname, '127.0.0.1')
assert.ok(url.port && !['8000', '4320', '5433', '6380'].includes(url.port))
const fixture = JSON.parse(await fs.readFile(path.join(OUT, 'fixture.json'), 'utf8'))
assert.equal(fixture.demo_only, true)
assert.deepEqual(fixture.feedback_seed, { actual_graph: true, model_calls: 0, source: 'synthetic' })
const expect = baseExpect.configure({ timeout: 20000 })
const browser = await chromium.launch({ executablePath: process.env.ZHIBI_CHROMIUM || ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync) })
const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce', serviceWorkers: 'block', permissions: ['clipboard-read', 'clipboard-write'] })
const report = { checks: [], errors: [], externalRequests: [], requests: [], colors: [], geometry: [], screenshots: [], demoOnly: true }
await context.route('**/*', route => {
  const url = new URL(route.request().url())
  if (['http:', 'https:'].includes(url.protocol) && url.origin !== BASE) { report.externalRequests.push(url.href); return route.abort() }
  return route.continue()
})
const page = await context.newPage()
page.on('pageerror', error => report.errors.push(error.message))
page.on('request', request => {
  if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method())) report.requests.push({ method: request.method(), url: request.url(), body: request.postDataJSON() })
})
const pass = name => { report.checks.push(name); console.log(`PASS ${name}`) }
const get = async suffix => { const response = await context.request.get(`${BASE}/api${suffix}`); assert.equal(response.status(), 200, suffix); return response.json() }
const meeting = id => get(`/books/${id}/meeting?limit=2000`)
const composer = () => page.getByLabel('给编辑部发消息', { exact: true })
const panel = () => page.locator('[data-testid="editorial-floating"], [data-testid="editorial-docked"]')
async function type(input, text) { await input.click(); await input.press('ControlOrMeta+A'); await page.keyboard.insertText(text) }
async function openChat() {
  if (await composer().isVisible()) return
  await page.locator('[role="button"][title="编辑部"]').click()
  await expect(composer()).toBeVisible()
}
async function open(id) { await page.goto(`${BASE}/desk/${id}`); await openChat() }
async function replyFor(id, note) {
  let reply
  await expect.poll(async () => {
    reply = (await meeting(id)).find(row => row.payload?.reply_to?.includes(note.id) && !row.payload?.dropped)
    return !!reply?.content && !['thinking', 'streaming', 'failed'].includes(reply.payload?.state)
  }, { timeout: 120000 }).toBe(true)
  const box = page.getByTestId(`reply-${reply.id}`)
  await expect(box).toHaveAttribute('data-state', 'done')
  return { note, reply, box }
}
async function send(id, text) {
  await type(composer(), text)
  const response = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/books/${id}/notes`)
  await composer().press('Enter')
  const posted = await response
  assert.equal(posted.status(), 201, await posted.text())
  return replyFor(id, await posted.json())
}
async function shot(name) {
  await page.evaluate(async () => { await document.fonts.ready; await Promise.allSettled(document.getAnimations().filter(animation => Number.isFinite(animation.effect?.getComputedTiming().endTime)).map(animation => animation.finished)) })
  await page.screenshot({ path: path.join(ROOT, 'docs/聊天改进验收', name) })
  report.screenshots.push(name)
}
async function theme(name) {
  await page.getByRole('button', { name: '系统设置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '系统设置', exact: true })
  await dialog.getByRole('tab', { name: '外观', exact: true }).click()
  await dialog.getByRole('button', { name, exact: true }).click()
  await dialog.getByRole('button', { name: '关闭设置', exact: true }).click()
}
async function geometry(result, mode, dark = false) {
  const author = page.getByTestId(`note-${result.note.id}`)
  await author.scrollIntoViewIfNeeded()
  await composer().click()
  const actions = author.getByTestId('author-actions')
  await expect(actions).toHaveCSS('opacity', '0')
  const before = await result.box.boundingBox()
  await author.hover()
  await expect(actions).toHaveCSS('opacity', '1')
  const bubble = await author.getByTestId('author-bubble').boundingBox()
  const row = await actions.boundingBox()
  assert.ok(row.y >= bubble.y + bubble.height, '作者按钮在气泡下面')
  assert.ok(Math.abs(row.x + row.width - bubble.x - bubble.width) < 1, '右边对齐')
  const labels = await actions.locator('button').allTextContents()
  assert.deepEqual(labels, ['复制', '修改'])
  assert.equal((await result.box.boundingBox()).y, before.y, '移上去下方消息不跳')
  await composer().click()
  await expect(actions).toHaveCSS('opacity', '0')
  assert.equal((await result.box.boundingBox()).y, before.y, '移开下方消息不跳')
  const values = await author.getByTestId('author-bubble').evaluate(element => ({ bubble: getComputedStyle(element).backgroundColor, pane: getComputedStyle(element.closest('.bg-pane-mid')).backgroundColor }))
  assert.notEqual(values.bubble, values.pane)
  assert.equal(values.bubble, dark ? 'rgb(66, 56, 44)' : 'rgb(231, 222, 206)')
  assert.equal(values.pane, dark ? 'rgb(28, 25, 22)' : 'rgb(243, 236, 224)')
  const answerColor = await result.box.locator('.chat-text').evaluate(element => getComputedStyle(element).backgroundColor)
  assert.notEqual(answerColor, values.pane)
  assert.notEqual(answerColor, values.bubble)
  const footer = result.box.getByTestId('reply-footer')
  const query = footer.getByRole('button', { name: /查了：/u })
  const queryBox = await query.boundingBox()
  const copyBox = await footer.getByRole('button', { name: '复制', exact: true }).boundingBox()
  const againBox = await footer.getByRole('button', { name: '重新回答', exact: true }).boundingBox()
  assert.ok(Math.abs(queryBox.y + queryBox.height / 2 - copyBox.y - copyBox.height / 2) < 1)
  assert.ok(Math.abs(againBox.y - copyBox.y) < 1)
  assert.ok(queryBox.x + queryBox.width <= copyBox.x)
  const memory = result.box.getByTestId('chat-memory-box')
  const memoryBox = await memory.boundingBox(), answerBox = await result.box.locator('.chat-text').boundingBox(), footerBox = await footer.boundingBox()
  assert.ok(memoryBox.y >= answerBox.y + answerBox.height && memoryBox.y + memoryBox.height <= footerBox.y)
  assert.ok(Math.abs(memoryBox.x - answerBox.x) < 1 && Math.abs(footerBox.x - answerBox.x) < 1)
  await expect(memory).toHaveCSS('border-top-width', '1px')
  await expect(memory).toHaveCSS('border-radius', '8px')
  assert.equal(await query.locator('span').evaluate(element => element.scrollWidth > element.clientWidth), true, '长查阅文案截断')
  report.colors.push({ mode, dark, ...values, answer: answerColor })
  report.geometry.push({ mode, dark, bubble, row, queryBox, copyBox, againBox, memoryBox, footerBox, nextMessageY: before.y })
  return author
}
try {
  const profiles = await get('/llm/profiles')
  assert.ok(profiles.length && profiles.every(profile => profile.provider === 'demo'))
  const id = fixture.new_book_id
  await open(id)
  if (await panel().getByRole('button', { name: '贴到右边', exact: true }).isVisible()) await panel().getByRole('button', { name: '贴到右边', exact: true }).click()
  await expect(page.getByTestId('editorial-docked')).toBeVisible()
  const original = await send(id, '请看看这段故事的开头，少年在雨夜守住灯火，等着失散的同伴归来。'.repeat(4))
  const originalAuthor = page.getByTestId(`note-${original.note.id}`)
  const widths = await originalAuthor.evaluate(element => ({ row: element.getBoundingClientRect().width, bubble: element.querySelector('[data-testid="author-bubble"]').getBoundingClientRect().width }))
  assert.ok(widths.bubble / widths.row > .83 && widths.bubble / widths.row <= .851, '长气泡仍占完整85%，不为按钮扣宽')
  await originalAuthor.hover()
  await originalAuthor.getByRole('button', { name: '修改', exact: true }).click()
  const inline = page.getByTestId('chat-inline-edit')
  await expect(inline.getByLabel('修改这句话')).toBeFocused()
  const edited = '我把开头改了：少年在雨夜等一盏灯。'
  await type(inline.getByLabel('修改这句话'), edited)
  const editResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/books/${id}/notes`)
  await inline.getByRole('button', { name: '发送', exact: true }).click()
  const postedEdit = await editResponse
  assert.equal(postedEdit.status(), 201)
  const editedNote = await postedEdit.json()
  assert.equal(postedEdit.request().postDataJSON().rewind_from, original.note.id)
  await replyFor(id, editedNote)
  await expect(inline).toHaveCount(0)
  assert.equal((await meeting(id)).find(row => row.id === original.note.id).payload.dropped, true)
  pass('贴右边真实发送、85%气泡、原地修改重发，旧聊天照旧收起')

  const result = await send(id, '你记得我说过什么吗？记住，以后每章结尾都留个钩子')
  assert.ok(result.reply.payload.tools?.some(tool => tool.kind === 'query'))
  assert.ok(result.reply.payload.memories?.length)
  const author = await geometry(result, 'side')
  await author.hover()
  await shot('任务5-01-贴右边浅色.png')
  await author.getByRole('button', { name: '复制', exact: true }).click()
  await expect(author.getByRole('button', { name: '已复制', exact: true })).toBeVisible()
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), result.note.content)
  await expect(author.getByRole('button', { name: '复制', exact: true })).toBeVisible()
  await composer().click()
  let keyboardReached = false
  for (let index = 0; index < 25; index++) {
    await page.keyboard.press('Shift+Tab')
    if (await author.evaluate(element => element.contains(document.activeElement))) { keyboardReached = true; break }
  }
  assert.equal(keyboardReached, true)
  await page.mouse.move(2, 2)
  await expect(author.getByTestId('author-actions')).toHaveCSS('opacity', '1')
  pass('浅色三种底色分明，作者复制/修改右下对齐，悬停无跳动，真实Tab进入也显示')

  const query = result.box.getByRole('button', { name: /查了：/u })
  await query.click()
  await expect(query).toHaveAttribute('aria-expanded', 'true')
  const looked = result.reply.payload.tools.filter(tool => tool.kind === 'query')
  for (const item of looked) await expect(result.box.getByText(item.text, { exact: true })).toBeVisible()
  const detailBox = await result.box.getByText(looked[0].text, { exact: true }).boundingBox()
  const footerBox = await result.box.getByTestId('reply-footer').boundingBox()
  assert.ok(detailBox.y >= footerBox.y + footerBox.height)
  await query.click()
  pass('查了与复制/重新回答同一行，长字截断；记忆小框在中间，原文仍在共同行下展开')

  await theme('墨色·暗')
  const darkAuthor = await geometry(result, 'side', true)
  await darkAuthor.hover()
  await shot('任务5-02-贴右边深色.png')
  pass('同一屏深色三种底色仍分明，原深色计算值不变')
  await theme('宣纸·亮')
  await panel().getByRole('button', { name: '浮起来', exact: true }).click()
  await expect(page.getByTestId('editorial-floating')).toBeVisible()
  const floatAuthor = await geometry(result, 'float')
  await floatAuthor.hover()
  await shot('任务5-03-浮窗浅色.png')
  pass('浮窗浅色重复几何/悬停/无跳动/记忆框检查，标题栏和输入框不改')

  await send(id, '谢谢，我再想想。')
  await result.box.scrollIntoViewIfNeeded()
  await composer().click()
  const oldCopy = result.box.getByRole('button', { name: '复制', exact: true })
  await expect(oldCopy.locator('..')).toHaveCSS('opacity', '0')
  await expect(query).toHaveCSS('opacity', '1')
  await result.box.hover()
  await expect(oldCopy.locator('..')).toHaveCSS('opacity', '1')
  await expect(result.box.getByRole('button', { name: '重新回答', exact: true })).toHaveCount(0)
  const notice = result.box.locator('[data-testid^="memory-notice-"]')
  await notice.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(notice).toContainText('没记：')
  const memoryId = result.reply.payload.memories[0].memory.id
  assert.ok(!(await get(`/books/${id}/memories`)).some(memory => memory.id === memoryId))
  pass('旧回答查了常显、按钮悬停才显；小框里真实撤销后原字和原灰态保留')

  // User clarified: the current gate cannot confirm with feedback; exercise both existing paths instead.
  const gateId = fixture.feedback_volume_book_id, jobId = fixture.feedback_volume_job_id
  await page.goto(`${BASE}/desk/${gateId}`)
  await page.locator('header nav a').filter({ hasText: /^正文$/u }).click()
  const waiting = page.locator('main .state').filter({ hasText: '编辑部在等你拍板' })
  await expect(waiting).toContainText('卷纲')
  await waiting.getByText('去看看', { exact: true }).click()
  if (await panel().isVisible()) await panel().getByRole('button', { name: '收起', exact: true }).click()
  const feedback = '这一卷打斗多一点'
  await page.getByRole('button', { name: '让主编改', exact: true }).click()
  await type(page.getByPlaceholder('比如：单元三放宽到 5 章；讲经堂加一个能说话的女弟子', { exact: true }), feedback)
  const revisionResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/jobs/${jobId}/decision`)
  await page.getByRole('button', { name: '交给主编', exact: true }).click()
  assert.equal((await revisionResponse).status(), 200)
  await expect.poll(async () => {
    const job = await get(`/jobs/${jobId}`)
    if (job.status === 'failed') throw new Error(job.error)
    return job.status === 'waiting_author' && job.pending?.kind === 'volume_review'
  }, { timeout: 180000 }).toBe(true)
  const revision = (await meeting(gateId)).findLast(message => message.speaker === 'author' && message.content === feedback)
  assert.ok(revision)
  assert.equal(revision.payload.author_feedback, undefined, '原话已是正文，不重复存')
  await openChat()
  const revisionBubble = page.getByTestId(`note-${revision.id}`)
  await expect(revisionBubble.getByTestId('author-bubble')).toHaveText(feedback)
  await expect(revisionBubble.getByRole('button', { name: '修改', exact: true })).toHaveCount(0)
  await panel().getByRole('button', { name: '收起', exact: true }).click()
  await expect(page.getByRole('button', { name: '就这样，开写', exact: true })).toBeVisible()
  const approvalResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/jobs/${jobId}/decision`)
  await page.getByRole('button', { name: '就这样，开写', exact: true }).click()
  const approval = await approvalResponse
  assert.equal(approval.status(), 200)
  assert.deepEqual(approval.request().postDataJSON(), { action: 'approve', feedback: '' })
  await expect.poll(async () => (await meeting(gateId)).some(message => message.speaker === 'author' && message.content === '批准这一卷的卷纲，开写。')).toBe(true)
  const decision = (await meeting(gateId)).findLast(message => message.speaker === 'author' && message.content === '批准这一卷的卷纲，开写。')
  await openChat()
  if (await panel().getByRole('button', { name: '贴到右边', exact: true }).isVisible()) await panel().getByRole('button', { name: '贴到右边', exact: true }).click()
  const decisionBubble = page.getByTestId(`note-${decision.id}`)
  await expect(decisionBubble.getByTestId('author-bubble')).toHaveText('批准这一卷的卷纲，开写。')
  await expect(revisionBubble.getByTestId('author-bubble')).toHaveText(feedback)
  for (const box of [revisionBubble, decisionBubble]) {
    await expect(box.getByRole('button', { name: '修改', exact: true })).toHaveCount(0)
    await box.hover()
    await box.getByRole('button', { name: '复制', exact: true }).click()
    await expect(box.getByRole('button', { name: '已复制', exact: true })).toBeVisible()
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), await box.getByTestId('author-bubble').innerText())
  }
  await expect(decisionBubble.getByRole('button', { name: '复制', exact: true })).toBeVisible()
  await decisionBubble.hover()
  await shot('任务5-04-看稿拍板作者气泡.png')
  report.confirmationWithFeedback = '新界面无此入口；前端真实适配器与气泡SSR合成数据覆盖，不冒充浏览器操作'
  pass('看卷纲写意见交给主编、直接批准开写，两种作者气泡只有复制且内容不重复')
  assert.deepEqual(report.errors, [])
  assert.deepEqual(report.externalRequests, [])
} catch (error) {
  report.failure = { message: String(error), body: await page.locator('body').innerText() }
  await page.screenshot({ path: path.join(OUT, 'browser-failure.png') })
  throw error
} finally {
  await fs.writeFile(path.join(OUT, 'browser-results.json'), JSON.stringify(report, null, 2))
  await context.close()
  await browser.close()
}
