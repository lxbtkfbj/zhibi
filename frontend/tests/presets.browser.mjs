/**
 * 预设任务 2：真实独立 API + 演示模型，七步页面验收与八张截图。
 * 先由调用者启动独立 API/Vite，准备 fixture JSON { book, profile }，再运行：
 * PRESETS_TEST_BASE=http://127.0.0.1:<vite>
 * PRESETS_TEST_API=http://127.0.0.1:<api>/api
 * PRESETS_TEST_FIXTURE=<absolute fixture.json> node tests/presets.browser.mjs
 * 可选 PRESETS_TEST_OUTPUT（默认 docs/预设管理验收）、ZHIBI_CHROMIUM。
 * 不起服务，不拦截/伪造业务 API；禁止日常端口、非本机流量与非 demo 配置。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.PRESETS_TEST_BASE
const api = process.env.PRESETS_TEST_API
assert.ok(base && api && process.env.PRESETS_TEST_FIXTURE, '请显式指定独立 BASE/API/FIXTURE')
const fixture = JSON.parse(await fs.readFile(process.env.PRESETS_TEST_FIXTURE, 'utf8'))
assert.ok(fixture.book && fixture.profile, 'fixture 必须提供独立书和演示模型 ID')
const out = process.env.PRESETS_TEST_OUTPUT ?? path.join(root, 'docs/预设管理验收')
await fs.mkdir(out, { recursive: true })
const origins = new Set([new URL(base).origin, new URL(api).origin])
for (const origin of origins) {
  const url = new URL(origin)
  assert.equal(url.hostname, '127.0.0.1', '只准本机独立环境')
  assert.ok(url.port && !['8000', '4320'].includes(url.port), '不能访问日常服务')
}
const json = async (suffix, options = {}) => {
  const response = await fetch(api + suffix, {
    ...options,
    ...(options.body ? { headers: { 'content-type': 'application/json' }, body: JSON.stringify(options.body) } : {}),
  })
  assert.ok(response.ok, `${options.method ?? 'GET'} ${suffix}: ${response.status} ${await response.clone().text()}`)
  return response.status === 204 ? null : response.json()
}
const profiles = await json('/llm/profiles')
assert.equal(profiles.find(profile => profile.id === fixture.profile)?.provider, 'demo')
assert.ok(profiles.every(profile => profile.provider === 'demo'), '独立实例不得配置真实模型')
const roles = await json('/llm/roles')
assert.ok(Object.values(roles).filter(Boolean).every(id => id === fixture.profile), '所有已分配角色必须用指定演示模型')
const initialActive = (await json('/presets?kind=chief_group')).active
const system = await json('/presets/system/chief_group')
assert.equal(system.blocks.length, 19)
assert.equal(system.blocks.filter(block => block.enabled).length, 17)
await json('/presets/active', { method: 'PUT', body: { kind: 'chief_group', source: 'system' } })

const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM ?? process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN', timezoneId: 'Asia/Taipei', reducedMotion: 'reduce', acceptDownloads: true })
await context.addInitScript(() => {
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', reducedMotion: true }))
  localStorage.setItem('zhibi:editorial-dock', 'side')
})
const page = await context.newPage()
page.setDefaultTimeout(10000)
const pageErrors = [], forbiddenRequests = [], checks = [], screenshots = [], requests = []
page.on('pageerror', error => pageErrors.push(error.message))
page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/presets')) requests.push({ method: request.method(), path: new URL(request.url()).pathname }) })
await context.route('**/*', route => {
  const url = new URL(route.request().url())
  if (url.protocol.startsWith('http') && !origins.has(url.origin)) {
    forbiddenRequests.push(url.origin + url.pathname)
    return route.abort()
  }
  return route.continue()
})
const check = name => { checks.push(name); console.log(`PASS ${name}`) }
const shot = async name => {
  await expect(page.locator('.preset-loading')).toHaveCount(0)
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, name) })
  screenshots.push(name)
}
const row = id => page.locator(`.preset-block-row[data-block-id="${id}"]`)
const selectBlock = id => row(id).locator('.preset-block-select').click()
const button = name => page.getByRole('button', { name, exact: true })
const dialog = name => page.getByRole('dialog', { name, exact: true })
const selectPreset = async (name, id) => {
  const matches = page.getByRole('button', { name: `选择预设：${name}`, exact: true })
  // 导入故意保留原名；按接口的库顺序选择对应 ID，不假设名字唯一。
  const index = id ? (await json('/presets?kind=chief_group')).mine.filter(item => item.name === name).findIndex(item => item.id === id) : 0
  assert.ok(index >= 0)
  await matches.nth(index).click()
  await expect(page.locator('.preset-block-row').first()).toBeVisible()
}
const waitWrite = (suffix, method = 'PUT') => page.waitForResponse(response => new URL(response.url()).pathname === '/api' + suffix && response.request().method() === method)
const save = async id => {
  const response = waitWrite(`/presets/mine/${id}`)
  await button('保存').click()
  assert.equal((await response).status(), 200)
  await expect(button('放弃修改')).toHaveCount(0)
  return json(`/presets/mine/${id}`)
}
const closeDialog = async name => {
  await dialog(name).getByRole('button', { name: /^关闭/ }).click()
  await expect(dialog(name)).toHaveCount(0)
}
let mine, imported, call, exportBlocks, restored, succeeded = false
try {
  // 1. 从书页系统设置入口进入，返回上下文随链接保留。
  await page.goto(`${base}/desk/${fixture.book}`)
  await button('系统设置').click()
  const settings = dialog('系统设置')
  await expect(settings.getByRole('link', { name: '预设管理', exact: true })).toBeVisible()
  await expect(settings.getByText('主编群聊发给模型的字，一块一块管', { exact: true })).toBeVisible()
  const cards = await settings.locator('.settings-tools-link').allTextContents()
  assert.ok(cards[0].includes('预设管理') && cards[1].includes('提示词与调用记录'), '新卡在提示词与调用记录上面')
  await settings.getByRole('link', { name: '预设管理', exact: true }).click()
  await expect(page).toHaveURL(/\/presets\?.*returnTo=/)
  await expect(page.getByRole('heading', { name: '预设管理', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '返回当前书', exact: true })).toBeVisible()
  await expect(page.locator('.preset-selected-description p')).toContainText('系统预设 · 第 1 版 · 19 块 · 17 块开着')
  await expect(page.getByRole('button', { name: `选择预设：${system.name}`, exact: true })).toBeVisible()
  await expect(page.locator('.preset-selected-description .preset-active')).toHaveText('正在用')
  await expect(button('解锁编辑')).toBeVisible()
  await expect(page.getByText('系统预设锁着，只能看。要改，点「解锁编辑」：会先复制一份给你，在复制出来的那份上改。', { exact: true })).toBeVisible()
  await selectBlock('tool_skills')
  await expect(row('tool_skills').getByRole('switch')).toBeDisabled()
  await expect(page.getByRole('textbox', { name: '预设块内容', exact: true })).not.toBeEditable()
  await shot('任务2-01-系统预设-1440x900.png')
  check('1 系统设置新卡在旧卡上面；保留返回当前书；系统19块17开与锁定横条')

  // 2. 解锁是复制，不修改只读系统资源。
  const copied = waitWrite('/presets/mine', 'POST')
  await button('解锁编辑').click()
  assert.equal((await copied).status(), 201)
  mine = await (await copied).json()
  await expect(page.getByRole('textbox', { name: '预设块内容', exact: true })).toBeEditable()
  assert.deepEqual((await json('/presets/system/chief_group')).blocks, system.blocks)
  check('2 解锁编辑创建作者副本并打开；系统原件逐字段未变')

  // 3. 开关警告、编辑、真实拖放、全字段新块以及保存后服务端ID替换。
  await selectBlock('reply_style')
  await row('reply_style').getByRole('switch').click()
  await expect(row('reply_style')).toContainText(`关了它：${system.blocks.find(block => block.id === 'reply_style').without}`)
  await expect(button('放弃修改')).toBeVisible()
  await shot('任务2-02-作者预设没保存-1440x900.png')
  await button('检查').click()
  await expect(dialog('检查结果')).toContainText('提醒')
  await expect(dialog('检查结果')).toContainText('回话的样子')
  await shot('任务2-03-检查结果-1440x900.png')
  await closeDialog('检查结果')
  await selectBlock('voice')
  const voice = '用简短白话直说判断，不使用老编辑的称呼。'
  await page.getByRole('textbox', { name: '预设块内容', exact: true }).fill(voice)
  await row('task').locator('[data-block-drag]').dragTo(row('voice'))
  await expect.poll(() => page.locator('.preset-block-row').evaluateAll(rows => rows.map(row => row.dataset.blockId))).toEqual(['role', 'task', ...system.blocks.map(block => block.id).filter(id => !['role', 'task'].includes(id))])
  await selectBlock('voice')
  await button('添加预设块').click()
  await expect(page.getByRole('textbox', { name: '预设块标题', exact: true })).toHaveValue('新的块')
  await expect(page.getByRole('combobox', { name: '消息角色', exact: true })).toHaveValue('system')
  await expect(page.getByRole('combobox', { name: '什么时候发', exact: true })).toHaveValue('always')
  await expect(page.getByRole('textbox', { name: '预设块内容', exact: true })).toHaveValue('')
  mine = await save(mine.id)
  const added = mine.blocks.find(block => !system.blocks.some(item => item.id === block.id))
  assert.ok(added?.id.startsWith('custom_'), '新块使用后台分配的ID')
  assert.deepEqual({ ...added, id: '' }, { id: '', title: '新的块', role: 'system', enabled: true, required: false, when: 'always', content: '' })
  await expect(page.getByRole('textbox', { name: '预设块标题', exact: true })).toHaveValue('新的块')
  assert.deepEqual(mine.blocks.slice(0, 2).map(block => block.id), ['role', 'task'])
  assert.equal(mine.blocks.find(block => block.id === 'voice').content, voice)
  assert.equal(mine.blocks.find(block => block.id === 'reply_style').enabled, false)
  await selectBlock('voice')
  // 来历验收图要看见说明全文；作者可以收起占位符腾出视野。
  await page.locator('.preset-placeholders summary').click()
  const lineage = page.locator('summary').filter({ hasText: /^来历$/ })
  await lineage.click()
  await expect(page.locator('.preset-origin')).toContainText('从系统预设第 1 版复制')
  await expect(page.getByText('后来改过', { exact: false })).toBeVisible()
  await page.locator('.preset-origin').scrollIntoViewIfNeeded()
  await shot('任务2-05-来历展开-1440x900.png')
  await button('跟系统的比一比').click()
  await expect(dialog('比一比')).toContainText(voice)
  await expect(dialog('比一比')).toContainText(system.blocks.find(block => block.id === 'voice').content)
  await shot('任务2-04-比一比-1440x900.png')
  await closeDialog('比一比')
  await page.setViewportSize({ width: 1280, height: 800 })
  await expect(page.getByRole('button', { name: `选择预设：${mine.name}`, exact: true })).toBeVisible()
  await page.locator('.preset-block-editor').evaluate(element => { element.scrollTop = 0 })
  await shot('任务2-07-作者预设-1280x800.png')
  await page.setViewportSize({ width: 1100, height: 800 })
  await expect(page.getByRole('combobox', { name: '选择预设', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: `选择预设：${mine.name}`, exact: true })).not.toBeVisible()
  await page.locator('.preset-block-editor').evaluate(element => { element.scrollTop = 0 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await shot('任务2-08-窄屏下拉框-1100x800.png')
  await page.setViewportSize({ width: 1440, height: 900 })
  check('3 必须块关闭提示、口吻编辑、任务说明拖至第2块、全字段新块保存后保留选中；来历/比一比与三种宽度截图')

  // 4. 用这份发真实群聊；调用记录只出现实际发送的块，可跳到同一块。
  const activated = waitWrite('/presets/active')
  await button('设为正在用').click()
  assert.equal((await activated).status(), 200)
  await expect(button('设为正在用')).toHaveCount(0)
  await page.getByRole('link', { name: '返回当前书', exact: true }).click()
  const before = (await json(`/llm-calls?book_id=${fixture.book}`)).items[0]?.id ?? 0
  const composer = page.getByRole('textbox', { name: '给编辑部发消息', exact: true })
  await expect(async () => {
    await composer.fill('请简单说一句，你会怎样帮助作者？')
    await expect(button('发送')).toBeEnabled({ timeout: 1000 })
  }).toPass({ timeout: 10000 })
  const sent = waitWrite(`/books/${fixture.book}/notes`, 'POST')
  await button('发送').click()
  assert.equal((await sent).status(), 201)
  await expect(button('重新回答').last()).toBeVisible({ timeout: 30000 })
  await expect.poll(async () => (await json(`/llm-calls?book_id=${fixture.book}`)).items[0]?.id ?? 0, { timeout: 30000 }).toBeGreaterThan(before)
  const calls = (await json(`/llm-calls?book_id=${fixture.book}`)).items.filter(item => item.id > before)
  const details = await Promise.all(calls.map(item => json(`/llm-calls/${item.id}`)))
  assert.ok(details.every(item => item.model === 'demo'))
  call = details.find(item => item.request?.preset?.id === mine.id)
  assert.ok(call, '真实群聊调用使用页面选中的预设')
  assert.equal(call.request.preset.name, mine.name)
  assert.ok(!call.request.preset.blocks.some(block => block.id === 'reply_style'))
  assert.ok(call.request.system.includes(voice))
  await page.goto(`${base}/prompts?tab=calls&returnTo=${encodeURIComponent(`/desk/${fixture.book}`)}`)
  await page.getByRole('tab', { name: '调用记录', exact: true }).click()
  await page.getByRole('combobox', { name: '按书筛选', exact: true }).selectOption(fixture.book)
  const callRow = page.locator('tbody tr').filter({ hasText: call.purpose }).first()
  await callRow.getByRole('button', { name: '查看', exact: true }).click()
  const presetSection = dialog('调用详情').locator('section').filter({ has: page.getByRole('heading', { name: '用的预设', exact: true }) })
  await expect(presetSection).toContainText(mine.name)
  const sentTitles = call.request.preset.blocks.map(block => block.title)
  await expect(presetSection.getByRole('link')).toHaveText(sentTitles)
  await shot('任务2-06-调用详情用的预设-1440x900.png')
  await presetSection.getByRole('link', { name: '口吻：老主编', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '预设块内容', exact: true })).toHaveValue(voice)
  check('4 正在用的作者预设真实演示群聊生效；调用详情列实际发送块且能跳到同一块')

  // 5. 正在用的隐藏激活按钮，所以先切回系统，再编辑原副本验422。
  await selectPreset(system.name)
  const activeSystem = waitWrite('/presets/active')
  await button('设为正在用').click()
  assert.equal((await activeSystem).status(), 200)
  await selectPreset(mine.name)
  await selectBlock('note')
  await button('删掉这一块').click()
  await expect(dialog('删掉「作者这次说的」？')).toContainText('这是必须的块：关了它：')
  await dialog('删掉「作者这次说的」？').getByRole('button', { name: '删掉这一块', exact: true }).click()
  await expect(row('note')).toHaveCount(0)
  mine = await save(mine.id)
  const blocked = waitWrite('/presets/active')
  await button('设为正在用').click()
  assert.equal((await blocked).status(), 422)
  await expect(dialog('这份不能用')).toContainText('没有一块放了 {{作者这次说的}}，主编看不到你这次说的话。')
  assert.equal((await json('/presets?kind=chief_group')).active.source, 'system')
  await closeDialog('这份不能用')
  check('5 删除作者这次说的后保存草稿，再激活收到422并显示这份不能用；原活动系统未被替换')

  // 6. 下载原始JSON再上传，块逐字段一致（包括ID、空白和顺序）。
  const downloadReady = page.waitForEvent('download')
  await page.getByRole('link', { name: '导出', exact: true }).click()
  const download = await downloadReady
  const exportPath = path.join(out, '任务2-导出再导入.json')
  await download.saveAs(exportPath)
  const exported = JSON.parse(await fs.readFile(exportPath, 'utf8'))
  exportBlocks = exported.blocks
  assert.deepEqual(exportBlocks, mine.blocks)
  const importing = waitWrite('/presets/import', 'POST')
  const chooserReady = page.waitForEvent('filechooser')
  await button('导入预设').click()
  await (await chooserReady).setFiles(exportPath)
  assert.equal((await importing).status(), 201)
  imported = await (await importing).json()
  assert.deepEqual(imported.blocks, exportBlocks)
  await expect(page.getByRole('button', { name: `选择预设：${imported.name}`, exact: true })).toHaveCount(2)
  check('6 页面导出下载后原文件导入，完整块逐字段一致')

  // 7. 第一份的第1次保存仍是最初的系统副本；恢复另存、不覆盖旧记录。
  await selectPreset(mine.name, mine.id)
  await button('保存记录').click()
  const history = dialog('保存记录')
  await expect(history).toContainText('第 1 次保存')
  const records = await json(`/presets/mine/${mine.id}/saves`)
  for (const record of records) {
    const snapshot = await json(`/presets/mine/${mine.id}/saves/${record.saved}`)
    await expect(history).toContainText(new RegExp(`第 ${record.saved} 次保存[^]*${snapshot.blocks.length} 块`))
  }
  const first = history.locator('article').filter({ has: page.locator('p', { hasText: /^第 1 次保存 ·/ }) })
  const firstSnapshot = await json(`/presets/mine/${mine.id}/saves/1`)
  const historyWritesBefore = requests.filter(request => request.method !== 'GET').length
  await first.getByRole('button', { name: '看这一版', exact: true }).click()
  const snapshotView = dialog('第 1 次保存')
  const snapshotRows = snapshotView.locator('.preset-block-row')
  await expect(snapshotView.locator('.preset-column-heading')).toContainText('17 / 19 开着')
  await expect(snapshotRows).toHaveCount(19)
  await expect(snapshotView.locator('.preset-block-count')).toHaveText('显示 19 / 19 块')
  const conditionLabels = new Map((await json('/presets/conditions')).map(condition => [condition.when, condition.label]))
  for (const [index, block] of firstSnapshot.blocks.entries()) {
    const historicalRow = snapshotRows.nth(index)
    await expect(historicalRow.locator('.preset-block-number')).toHaveText(String(index + 1))
    await expect(historicalRow.locator('.preset-block-select > span')).toHaveText(block.title + (block.required ? '必须' : ''))
    const role = { system: 'System', user: 'User', assistant: 'Assistant' }[block.role]
    await expect(historicalRow.locator('small')).toHaveText(`${role} · ${[...block.content].length} 字${block.when === 'always' ? '' : ` · ${conditionLabels.get(block.when)}`}`)
    await expect(historicalRow.getByRole('switch')).toBeDisabled()
    await expect(historicalRow.getByRole('switch')).toHaveAttribute('aria-checked', String(block.enabled))
    await expect(historicalRow.locator('.preset-drag-handle')).toBeDisabled()
    await historicalRow.locator('.preset-block-select').click()
    await expect(snapshotView.locator('.preset-block-heading h3')).toHaveText(block.title)
    await expect(snapshotView.locator('.preset-block-heading > span')).toHaveText(`第 ${index + 1} 块 · ${[...block.content].length} 字`)
    const roleInput = snapshotView.getByRole('combobox', { name: '保存记录的消息角色', exact: true })
    const whenInput = snapshotView.getByRole('combobox', { name: '保存记录的什么时候发', exact: true })
    await expect(roleInput).toBeDisabled()
    await expect(roleInput).toHaveValue(block.role)
    await expect(whenInput).toBeDisabled()
    await expect(whenInput).toHaveValue(block.when)
    const content = snapshotView.getByRole('textbox', { name: '保存记录的预设块内容', exact: true })
    await expect(content).not.toBeEditable()
    await expect(content).toHaveValue(block.content)
  }
  const snapshotFilters = snapshotView.getByRole('group', { name: '筛保存记录的预设块', exact: true })
  for (const [label, enabled] of [['关着的', false], ['开着的', true]]) {
    await snapshotFilters.getByRole('button', { name: label, exact: true }).click()
    const expected = firstSnapshot.blocks.map((block, index) => ({ block, index })).filter(item => item.block.enabled === enabled)
    await expect(snapshotRows).toHaveCount(expected.length)
    await expect(snapshotView.locator('.preset-block-count')).toHaveText(`显示 ${expected.length} / 19 块`)
    await expect(snapshotRows.locator('.preset-block-number')).toHaveText(expected.map(item => String(item.index + 1)))
  }
  await snapshotFilters.getByRole('button', { name: '全部', exact: true }).click()
  const snapshotSearch = snapshotView.getByRole('textbox', { name: '搜保存记录块的标题或内容', exact: true })
  for (const [needle, id] of [['工具：翻手册', 'tool_skills'], ['{{作者这次说的}}', 'note']]) {
    await snapshotSearch.fill(needle)
    const index = firstSnapshot.blocks.findIndex(block => block.id === id)
    await expect(snapshotRows).toHaveCount(1)
    await expect(snapshotRows.locator('.preset-block-number')).toHaveText(String(index + 1))
    await expect(snapshotRows.locator('.preset-block-select > span')).toHaveText(firstSnapshot.blocks[index].title + (firstSnapshot.blocks[index].required ? '必须' : ''))
  }
  for (const name of ['添加预设块', '删掉这一块', '保存', '放弃修改']) await expect(snapshotView.getByRole('button', { name, exact: true })).toHaveCount(0)
  await expect(snapshotView.getByRole('textbox', { name: '预设块标题', exact: true })).toHaveCount(0)
  assert.equal(requests.filter(request => request.method !== 'GET').length, historyWritesBefore, '只读保存记录的选择/搜索/筛选不得写入')
  await snapshotView.getByRole('button', { name: '返回保存记录', exact: true }).click()
  await expect(history).toBeVisible()
  const restoring = waitWrite(`/presets/mine/${mine.id}/saves/1/restore`, 'POST')
  await first.getByRole('button', { name: '退回这一版', exact: true }).click()
  await dialog('退回到第 1 次保存？现在的会另存一次，不会丢').getByRole('button', { name: '退回这一版', exact: true }).click()
  assert.equal((await restoring).status(), 200)
  restored = await (await restoring).json()
  assert.equal(restored.saved, mine.saved + 1)
  assert.deepEqual(restored.blocks, (await json(`/presets/mine/${mine.id}/saves/1`)).blocks)
  assert.deepEqual(restored.blocks, system.blocks.map(block => Object.fromEntries(['id', 'title', 'role', 'enabled', 'required', 'when', 'content'].map(field => [field, block[field]]))))
  check('7 保存记录逐条读取块数；第1版19块/17开、中右栏角色条件全文只读、搜索筛选保留原序号且零写入；退回第1次另存新次，原件完整恢复')
  assert.deepEqual(pageErrors, [])
  assert.deepEqual(forbiddenRequests, [])
  succeeded = true
} finally {
  if (!succeeded) await page.screenshot({ path: path.join(out, '任务2-browser-failed.png'), fullPage: true }).catch(() => {})
  await json('/presets/active', { method: 'PUT', body: { kind: 'chief_group', ...initialActive } })
  // 只保留截图/证据；此测试创建的两份预设可安全删除，绝不碰外部预设或书。
  for (const preset of [mine, imported]) if (preset?.id) await json(`/presets/mine/${preset.id}`, { method: 'DELETE' })
  await fs.writeFile(path.join(out, '任务2-浏览器验收.json'), JSON.stringify({
    base, api, book: fixture.book, profile: fixture.profile, checks, screenshots,
    created_preset: mine && { id: mine.id, name: mine.name, saved: mine.saved },
    call: call && { id: call.id, model: call.model, preset: call.request.preset, messages: call.request.messages },
    exportBlocks, restored_saved: restored?.saved, requests, pageErrors, forbiddenRequests,
    realModelCalls: 0, businessMocks: 0, activeRestored: true, createdPresetsDeleted: true, ok: succeeded,
  }, null, 2) + '\n')
  await browser.close()
}
