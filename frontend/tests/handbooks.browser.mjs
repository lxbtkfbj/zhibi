/** 手册管理：独立真实 API + 演示模型，不拦截业务响应。
 * HANDBOOKS_TEST_BASE / HANDBOOKS_TEST_API / HANDBOOKS_TEST_FIXTURE 必须显式指定。
 * fixture 至少包含 { book, profile }，只能使用这一包自己建的合成书和演示模型。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.HANDBOOKS_TEST_BASE
const api = process.env.HANDBOOKS_TEST_API
const fixturePath = process.env.HANDBOOKS_TEST_FIXTURE
assert.ok(base && api && fixturePath, '显式指定本包独立前后端地址和合成书 fixture')
const fixture = JSON.parse(await fs.readFile(fixturePath, 'utf8'))
const out = process.env.HANDBOOKS_TEST_OUTPUT ?? path.join(root, 'docs/手册管理验收')
const allowedOrigins = new Set([new URL(base).origin, new URL(api).origin])
assert.ok([...allowedOrigins].every(origin => {
  const url = new URL(origin)
  return url.hostname === '127.0.0.1' && url.port && !['8000', '4320'].includes(url.port)
}), '只允许独立本机环境，不能访问日常服务')
assert.ok(fixture.book && fixture.profile, 'fixture 必须明确指定合成书和演示模型')
await fs.mkdir(out, { recursive: true })
const json = async (suffix, options) => {
  const response = await fetch(api + suffix, options)
  assert.ok(response.ok, `${suffix}: ${response.status} ${await response.clone().text()}`)
  return response.status === 204 ? null : response.json()
}
const post = (suffix, body) => json(suffix, { method: 'POST', ...(body === undefined ? {} : { headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }) })
const put = (suffix, body) => json(suffix, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
const fingerprint = async () => Object.fromEntries(await Promise.all([
  'frontend/src/pages/HandbooksPage.tsx', 'frontend/src/api/handbooks.ts',
  'frontend/src/pages/PromptsPage.tsx', 'frontend/src/pages/PresetsPage.tsx',
  'frontend/src/lib/handbookDrafts.ts', 'frontend/src/lib/handbookEditor.ts',
  'frontend/src/lib/handbookNavigation.ts', 'frontend/src/pages/handbooks.css',
  'frontend/src/lib/promptNavigation.ts', 'frontend/src/lib/presetNavigation.ts',
  'frontend/src/pages/SettingsPage.tsx', 'frontend/src/main.tsx',
].map(async file => [file, createHash('sha256').update(await fs.readFile(path.join(root, file))).digest('hex')])))
const sourceSha256 = await fingerprint()
const original = await json('/handbooks/opening')
const originalStandards = await json('/handbooks/standards')
const initial = await json('/handbooks')
assert.deepEqual(initial.items.map(item => item.key), ['opening', 'standards'], '在本包新建的独立库运行')
assert.ok(initial.items.every(item => item.enabled && item.source === 'system' && !item.modified && item.saved === 0))
const marker = '手册管理独立验收：这段只在测试库，主编翻到的全文末尾必须保留。'
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN', timezoneId: 'Asia/Taipei', reducedMotion: 'reduce' })
const page = await context.newPage()
const pageErrors = [], forbiddenRequests = [], checks = [], screenshots = [], mutations = []
page.on('pageerror', error => pageErrors.push(error.message))
page.on('request', request => {
  if (request.method() !== 'GET') mutations.push({ method: request.method(), path: new URL(request.url()).pathname, body: request.postData() })
})
await context.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && !allowedOrigins.has(url.origin)) {
    forbiddenRequests.push(url.origin + url.pathname)
    return route.abort()
  }
  return route.continue()
})
await context.addInitScript(() => {
  localStorage.setItem('zhibi:editorial-dock', 'side')
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', reducedMotion: true }))
})
const check = name => { checks.push(name); console.log(`PASS ${name}`) }
const row = key => page.locator(`[data-handbook-key="${key}"]`)
const editor = () => page.getByTestId('prompt-editor').locator('.cm-content[contenteditable="true"]')
const editorEnd = async () => { await editor().click(); await editor().press('Control+End') }
const expectMarker = async () => { await editorEnd(); await expect(editor()).toContainText(marker) }
const heading = () => page.getByRole('heading', { name: '手册管理', exact: true })
const choose = key => row(key).getByRole('button', { name: key === 'opening' ? '开书' : key === 'standards' ? '写书的标准' : undefined, exact: true }).first().click()
const catalog = () => page.getByTestId('handbook-catalog')
const requestIs = (suffix, method) => response => new URL(response.url()).pathname === '/api' + suffix && response.request().method() === method
const save = async key => {
  const response = page.waitForResponse(requestIs(`/handbooks/${key}`, 'PUT'))
  await page.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal((await response).status(), 200)
  await expect(page.getByRole('button', { name: '保存', exact: true })).toHaveCount(0)
}
const toggle = async (key, enabled, status = 200) => {
  const response = page.waitForResponse(requestIs(`/handbooks/${key}/enabled`, 'PUT'))
  await row(key).getByRole('switch').click()
  assert.equal((await response).status(), status)
  await expect(row(key).getByRole('switch')).toHaveAttribute('aria-checked', String(enabled))
}
const shot = async name => {
  if (await heading().isVisible()) await page.locator('.handbook-editor').evaluate(element => { element.scrollTop = 0 })
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, name) })
  screenshots.push(name)
}
const confirm = message => page.once('dialog', async dialog => { assert.equal(dialog.message(), message); await dialog.accept() })
const closeDialog = async title => {
  await page.getByRole('dialog', { name: title, exact: true }).getByRole('button', { name: '关闭', exact: true }).click()
}
let createdKey
let ok = false
let noteId, replyId
try {
  const roles = await json('/llm/roles')
  assert.ok(Object.values(roles).filter(Boolean).every(id => id === fixture.profile), '所有分工都使用这一包的演示模型')
  assert.equal((await json('/llm/profiles')).find(item => item.id === fixture.profile)?.provider, 'demo')

  // 1. 从书页系统设置进入，返回链路与目录均来自真实 API。
  const source = `/desk/${fixture.book}?tab=${encodeURIComponent('大纲')}&node=book#outline`
  await page.goto(base + source)
  await page.getByRole('button', { name: '系统设置', exact: true }).click()
  const settings = page.getByRole('dialog', { name: '系统设置', exact: true })
  await expect(settings).toBeVisible()
  assert.deepEqual(await settings.locator('.settings-tools-link').evaluateAll(items => items.map(item => item.getAttribute('aria-label'))), ['预设管理', '手册管理', '提示词与调用记录'])
  await settings.getByRole('link', { name: '手册管理', exact: true }).click()
  await expect(heading()).toBeVisible()
  await expect(page.getByRole('link', { name: '返回当前书', exact: true })).toHaveAttribute('href', source)
  await expect(row('opening').getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  await expect(row('standards').getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByText('这本是程序带的。直接改，存了就是你的版本；改坏了，随时能换回程序带的。', { exact: true })).toBeVisible()
  await shot('01-程序带的开书.png')
  await page.getByText('主编看到的目录', { exact: true }).click()
  await expect(catalog()).toHaveText(initial.catalog)
  assert.ok((await catalog().textContent()).includes('开书') && (await catalog().textContent()).includes('写书的标准'))
  await shot('06-主编看到的目录.png')
  check('设置入口、两本默认开着、原样目录、回书路径')

  // 2. 正文草稿在切换、刷新、离开再回来后仍在；保存才发给后台。
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('开书草稿')
  await page.getByRole('textbox', { name: '什么时候翻', exact: true }).fill('草稿目录：' + original.when)
  await editor().click()
  await editor().press('Control+A')
  await page.keyboard.insertText(original.body + '\n\n' + marker)
  await choose('standards')
  await expect(page.getByRole('textbox', { name: '名称', exact: true })).toHaveValue('写书的标准')
  await choose('opening')
  await expectMarker()
  await expect(row('opening').getByLabel('有没保存的改动', { exact: true })).toBeVisible()
  await page.reload()
  await expectMarker()
  await expect(page.getByRole('textbox', { name: '名称', exact: true })).toHaveValue('开书草稿')
  await expect(page.getByRole('textbox', { name: '什么时候翻', exact: true })).toHaveValue('草稿目录：' + original.when)
  assert.equal(new URL(page.url()).searchParams.get('key'), 'opening')
  await expect(page.getByText('有没保存的改动：切到别的手册、刷新页面都还在，点「保存」才给主编用。', { exact: true })).toBeVisible()
  await shot('02-开书未保存草稿.png')
  assert.equal((await json('/handbooks/opening')).content, original.content, '未保存草稿不能影响主编')
  await page.goto(`${base}/prompts`)
  await page.goto(`${base}/handbooks?key=opening`)
  await expectMarker()
  await expect(page.getByRole('textbox', { name: '名称', exact: true })).toHaveValue('开书草稿')
  await expect(page.getByRole('textbox', { name: '什么时候翻', exact: true })).toHaveValue('草稿目录：' + original.when)
  await page.getByRole('textbox', { name: '名称', exact: true }).fill(original.name)
  await page.getByRole('textbox', { name: '什么时候翻', exact: true }).fill(original.when)
  await save('opening')
  const changed = await json('/handbooks/opening')
  assert.equal(changed.content, original.content + '\n\n' + marker)
  await expect(page.getByText(new RegExp('程序带的 · 你改过 · 保存过 1 次 ·'))).toBeVisible()
  check('切换、刷新、离开都保留三字段草稿；保存第1次，正文原样生效')

  // 3. 按段落比较，一样的默认收起，加的整段只在右侧。
  await page.getByRole('button', { name: '跟程序带的比一比', exact: true }).click()
  const diff = page.getByRole('dialog', { name: '跟程序带的比一比', exact: true })
  await expect(diff).toBeVisible()
  await expect(diff.getByText('改了 0 段，加了 1 段，删了 0 段', { exact: true })).toBeVisible()
  await expect(diff.getByText('你加的', { exact: true })).toBeVisible()
  await expect(diff.getByText(marker, { exact: true })).toBeVisible()
  await expect(diff.getByText(/^一样的 \d+ 段$/)).toBeVisible()
  await shot('03-跟程序带的比一比.png')
  await closeDialog('跟程序带的比一比')
  await editor().click()
  await editor().press('Control+End')
  await page.keyboard.insertText('\n\n这段是要放弃的草稿。')
  page.once('dialog', async dialog => { assert.equal(dialog.message(), '改的还没保存，确定不要了吗？'); await dialog.dismiss() })
  await page.getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(editor()).toContainText('这段是要放弃的草稿。')
  confirm('改的还没保存，确定不要了吗？')
  await page.getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(editor()).not.toContainText('这段是要放弃的草稿。')
  await expectMarker()
  assert.equal((await json('/handbooks/opening')).saved, 1)
  check('段落比较0改1加0删、相同段落折叠；放弃草稿先确认、不改保存版')

  // 4. 真实群聊、demo工具来回、DB记录与展开的全文逐字一致。
  await post(`/books/${fixture.book}/chat/conversations`)
  const callsBefore = await json(`/llm-calls?book_id=${fixture.book}`)
  const beforeId = callsBefore.items[0]?.id ?? 0
  const conversations = page.waitForResponse(requestIs(`/books/${fixture.book}/chat/conversations`, 'GET'))
  await page.goto(`${base}/desk/${fixture.book}`)
  await conversations
  await expect(async () => {
    const input = page.getByRole('textbox', { name: '给编辑部发消息', exact: true })
    await input.fill('开书先定什么')
    await expect(input).toHaveValue('开书先定什么')
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled({ timeout: 1000 })
  }).toPass({ timeout: 10000 })
  const sent = page.waitForResponse(requestIs(`/books/${fixture.book}/notes`, 'POST'))
  await page.getByRole('button', { name: '发送', exact: true }).click()
  assert.equal((await sent).status(), 201)
  noteId = (await (await sent).json()).id
  await expect(page.getByRole('button', { name: '查了：手册《开书》', exact: true })).toBeVisible({ timeout: 30000 })
  const meeting = await json(`/books/${fixture.book}/meeting?limit=2000`)
  const reply = meeting.find(item => item.payload?.reply_to?.includes(noteId))
  replyId = reply?.id
  assert.ok(reply)
  assert.equal(reply.payload.tools.find(tool => tool.label === '手册《开书》')?.text, changed.content)
  const rendered = page.getByTestId(`reply-${reply.id}`)
  await expect(rendered).toHaveAttribute('data-state', 'done')
  await rendered.getByRole('button', { name: '查了：手册《开书》', exact: true }).click()
  assert.equal(await rendered.getByText(changed.content, { exact: true }).textContent(), changed.content)
  await rendered.getByText(changed.content, { exact: true }).scrollIntoViewIfNeeded()
  await rendered.getByText(changed.content, { exact: true }).evaluate(element => { element.scrollTop = element.scrollHeight })
  await shot('07-群聊查了手册全文.png')
  const newCalls = (await json(`/llm-calls?book_id=${fixture.book}`)).items.filter(call => call.id > beforeId)
  assert.ok(newCalls.length > 0 && newCalls.every(call => call.model === 'demo'), '只调用演示模型')
  const callDetails = await Promise.all(newCalls.map(call => json(`/llm-calls/${call.id}`)))
  assert.ok(callDetails.some(call => call.request.user.includes(changed.content)), '工具来回携带当前全文')
  check('群聊真实翻手册、查了完整原文、演示模型调用记录')

  // 5. 开关即刻生效，不记一次保存。
  await page.goto(`${base}/handbooks?key=standards`)
  await expect(heading()).toBeVisible()
  await toggle('standards', false)
  await page.getByText('主编看到的目录', { exact: true }).click()
  const enabledCatalog = await json('/handbooks')
  await expect(catalog()).toHaveText(enabledCatalog.catalog)
  assert.ok(!enabledCatalog.catalog.includes('写书的标准'))
  assert.equal((await json('/handbooks/standards')).saved, 0)
  check('关闭写书的标准立即退出目录，开关不记保存')

  // 6. 新建、未写完/重名被拦回；写完改成打斗以后才能打开。
  const createdResponse = page.waitForResponse(requestIs('/handbooks', 'POST'))
  await page.getByRole('button', { name: '新建手册', exact: true }).click()
  const created = await (await createdResponse).json()
  createdKey = created.key
  assert.ok(createdKey.startsWith('mine_'))
  assert.equal(created.saved, 1)
  await expect(page.getByRole('textbox', { name: '名称', exact: true })).toHaveValue('新手册')
  await expect(row(createdKey).getByRole('switch')).toHaveAttribute('aria-checked', 'false')
  await expect(page.getByText('还没写完：名称、什么时候翻、正文都写上，才能打开给主编翻。', { exact: true })).toBeVisible()
  await toggle(createdKey, false, 422)
  await expect(row(createdKey).getByText('名称、什么时候翻、正文都写上，才能打开。', { exact: true })).toBeVisible()
  await shot('05-新建未写完开关被拦.png')
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('开书')
  await page.getByRole('textbox', { name: '什么时候翻', exact: true }).fill('聊到打斗场景怎么写的时候翻')
  await editor().click()
  await page.keyboard.insertText('先写清双方的目标，再用行动表现攻防。')
  await save(createdKey)
  await toggle(createdKey, false, 422)
  await expect(row(createdKey).getByText('已经有一本开着的「开书」。先关掉那本，或者给这本改个名。', { exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('打斗')
  await save(createdKey)
  await toggle(createdKey, true)
  assert.ok((await json('/handbooks')).catalog.includes('打斗'))
  check('新建第1次、未写完和重名422原话、开关回弹、完成后打开')

  // 7. 换回程序带的也是一次保存；退回第1次另存第3次。
  await choose('opening')
  confirm('换回程序带的？你改的这份会留在保存记录里，随时能退回来。')
  const reset = page.waitForResponse(requestIs('/handbooks/opening/use-system', 'POST'))
  await page.getByRole('button', { name: '换回程序带的', exact: true }).click()
  assert.equal((await reset).status(), 200)
  assert.equal((await json('/handbooks/opening')).content, original.content)
  await page.getByRole('button', { name: '保存记录', exact: true }).click()
  const saves = page.getByRole('dialog', { name: '保存记录', exact: true })
  await expect(saves).toBeVisible()
  const records = await json('/handbooks/opening/saves')
  assert.equal(records.length, 2)
  assert.equal(records[0].kind, 'use_system')
  await expect(saves.locator('[data-handbook-save]').first()).toContainText('换回程序带的')
  await shot('04-开书保存记录.png')
  await saves.locator('[data-handbook-save="1"]').getByRole('button', { name: '看这一版', exact: true }).click()
  const snapshot = page.getByRole('dialog', { name: '第 1 次保存', exact: true })
  await expect(snapshot).toBeVisible()
  await expect(snapshot).toContainText(marker)
  await closeDialog('第 1 次保存')
  // 关闭快照返回保存记录列表；若产品是两个对话框，列表仍在。
  if (!(await saves.isVisible())) await page.getByRole('button', { name: '保存记录', exact: true }).click()
  confirm('退回到第 1 次保存？现在的会另存一次，不会丢。')
  const restored = page.waitForResponse(requestIs('/handbooks/opening/saves/1/restore', 'POST'))
  await saves.locator('[data-handbook-save="1"]').getByRole('button', { name: '退回这一版', exact: true }).click()
  assert.equal((await restored).status(), 200)
  assert.equal((await json('/handbooks/opening')).content, changed.content)
  assert.equal((await json('/handbooks/opening')).saved, 3)
  if (await saves.isVisible()) await closeDialog('保存记录')
  await expectMarker()
  check('保存记录倒序、只读查看、换回第2次、退回第1次另存第3次')

  // 8. 删除你写的，连保存记录一起消失。
  await row(createdKey).getByRole('button', { name: '打斗', exact: true }).click()
  confirm('删掉「打斗」？保存记录也一起删，删了找不回来。')
  const deleted = page.waitForResponse(requestIs(`/handbooks/${createdKey}`, 'DELETE'))
  await page.getByRole('button', { name: '删除', exact: true }).click()
  assert.equal((await deleted).status(), 204)
  await expect(row(createdKey)).toHaveCount(0)
  assert.equal((await fetch(api + `/handbooks/${createdKey}/saves`)).status, 404)
  createdKey = undefined
  check('只删除本包新建手册，保存记录随之删除')

  // 9. 提示词不再管手册，预设提示与三页导航保留回书上下文。
  const returnTo = new URLSearchParams({ returnTo: source }).toString()
  await page.goto(`${base}/prompts?${returnTo}`)
  await expect(page.getByRole('heading', { name: '提示词与调用记录', exact: true })).toBeVisible()
  await expect(page.locator('[data-prompt-group="手册"]')).toHaveCount(0)
  assert.ok((await json('/prompts')).every(item => item.group !== '手册' && !item.name.startsWith('skills.')))
  assert.equal((await fetch(api + '/prompts/skills.opening')).status, 404)
  await page.getByRole('link', { name: '手册管理', exact: true }).click()
  await expect(heading()).toBeVisible()
  await expect(page.getByRole('link', { name: '返回当前书', exact: true })).toHaveAttribute('href', source)
  await page.getByRole('button', { name: '系统设置', exact: true }).click()
  await settings.getByRole('link', { name: '预设管理', exact: true }).click()
  await expect(page.getByRole('heading', { name: '预设管理', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '返回当前书', exact: true })).toHaveAttribute('href', source)
  await page.locator('.preset-block-select').filter({ hasText: '工具：翻手册' }).click()
  await expect(page.getByText('手册的目录在「手册管理」里管。', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '手册管理', exact: true })).toHaveCount(2)
  await page.getByRole('link', { name: '手册管理', exact: true }).first().click()
  await expect(heading()).toBeVisible()
  await expect(page.getByRole('link', { name: '返回当前书', exact: true })).toHaveAttribute('href', source)
  await page.setViewportSize({ width: 1100, height: 800 })
  await page.goto(`${base}/handbooks?key=opening&${returnTo}`)
  await expect(editor()).toBeVisible()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, '1100px不应整页横向溢出')
  const listWidth = await page.locator('.handbook-list-panel').evaluate(element => element.getBoundingClientRect().width)
  assert.ok(listWidth >= 235 && listWidth <= 245, `1100px左栏应约240宽，实际${listWidth}`)
  await shot('08-1100宽双栏.png')
  check('提示词除册、预设工具提示、三页往返回书路径、1100宽双栏')

  assert.deepEqual(pageErrors, [])
  assert.deepEqual(forbiddenRequests, [])
  assert.deepEqual(await fingerprint(), sourceSha256, '验收时产品源码改变，需重跑稳定版本')
  check('0页面错误、0外网请求、0真实模型调用')
  ok = true
  await fs.unlink(path.join(out, 'FAILED.png')).catch(() => {})
} catch (error) {
  await page.screenshot({ path: path.join(out, 'FAILED.png') }).catch(() => {})
  throw error
} finally {
  // 仅清理本包独立库中的自己的变更，不触碰作者资料。
  if (createdKey) await json(`/handbooks/${createdKey}`, { method: 'DELETE' }).catch(() => {})
  await post('/handbooks/opening/use-system').catch(() => {})
  await put('/handbooks/standards/enabled', { enabled: originalStandards.enabled }).catch(() => {})
  await fs.writeFile(path.join(out, '浏览器验收.json'), JSON.stringify({ ok, base, api, book: fixture.book, profile: fixture.profile, sourceSha256, checks, screenshots, noteId, replyId, pageErrors, forbiddenRequests, mutations, realModelCalls: 0 }, null, 2) + '\n')
  await browser.close()
}
