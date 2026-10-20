/** 第二批任务 2 实际浏览器验收：只允许 4407/8047 独立演示环境，业务动作全部点击 UI。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = 'http://127.0.0.1:4407'
const apiBase = 'http://127.0.0.1:8047'
assert.equal(process.env.TEST_BASE_URL, base, '只允许独立验收前端 4407')
assert.equal(process.env.TEST_API_URL, apiBase, '只允许独立验收后端 8047')
const root = fileURLToPath(new URL('../../', import.meta.url))
const data = path.join(root, 'data/teardown2-task2')
const output = path.join(root, 'docs/拆书第二批验收')
const stateFile = path.join(data, 'ui-acceptance.json')
const storageFile = path.join(data, 'ui-storage.json')
await fs.mkdir(output, { recursive: true })
const evidence = await fs.readFile(stateFile, 'utf8').then(JSON.parse).catch(() => ({ checks: {}, screenshots: [], events: [], errors: [], mutations: [] }))
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const context = await browser.newContext({ viewport: { width: 1720, height: 1100 }, reducedMotion: 'reduce', storageState: await fs.access(storageFile).then(() => storageFile).catch(() => undefined) })
await context.addInitScript(() => {
  window.__teardownEvents = []
  const Source = window.EventSource
  window.EventSource = class extends Source {
    constructor(...args) {
      super(...args)
      for (const type of ['job', 'teardown_saved']) this.addEventListener(type, event => {
        window.__teardownEvents.push({ at: new Date().toISOString(), type, data: JSON.parse(event.data) })
      })
    }
  }
})
const page = await context.newPage()
const expect = baseExpect.configure({ timeout: 30000 })
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => {
  if (request.url().startsWith(`${base}/api/`) && ['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) evidence.mutations.push({ at: new Date().toISOString(), method: request.method(), url: request.url(), body: request.postData()?.slice(0, 1000) })
})
const api = async route => {
  const response = await page.request.get(`${apiBase}/api${route}`)
  assert.equal(response.status(), 200, route)
  return response.json()
}
const save = async () => {
  evidence.events.push(...await page.evaluate(() => window.__teardownEvents.splice(0)))
  await fs.writeFile(stateFile, JSON.stringify(evidence, null, 2))
  await context.storageState({ path: storageFile })
}
const collapseChat = async () => {
  const close = page.getByTestId('editorial-header').getByRole('button', { name: '收起', exact: true })
  if (await close.count()) await close.click()
}
const shot = async name => {
  const file = `task2-${name}.png`
  await page.screenshot({ path: path.join(output, file) })
  if (!evidence.screenshots.includes(file)) evidence.screenshots.push(file)
}
const strip = () => page.getByTestId('teardown-progress-strip')
const tab = name => page.locator('header nav').getByRole('button', { name, exact: true })

try {
  const profiles = await api('/llm/profiles')
  assert.ok(profiles.every(profile => profile.provider === 'demo' && !profile.has_key), '验收库不能留有真实模型配置')
  evidence.checks.demoOnly = true
  if (!evidence.bookId) {
    await page.goto(base)
    await page.getByRole('button', { name: '拆一本书', exact: true }).first().click()
    await page.getByLabel('选择 TXT 文件', { exact: true }).setInputFiles(path.join(data, '合成48章.txt'))
    await expect(page.getByLabel('书名', { exact: true })).toHaveValue('拆书界面验收合成书')
    evidence.bookId = new URL(page.url()).pathname.split('/')[2]
    const preview = await api(`/teardown/${evidence.bookId}/preview`)
    assert.equal(preview.chapter_count, 48)
    evidence.preview = { chapters: preview.chapter_count, title: preview.title, chars: preview.chars }
    await expect(page.getByRole('spinbutton', { name: '拆到第几章', exact: true })).toHaveAttribute('placeholder', '不填就是全本（48 章）')
    await page.getByRole('spinbutton', { name: '拆到第几章', exact: true }).fill('20')
    await expect(page.getByText('现在是 演示模式', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: '开始拆', exact: true }).click()
    await expect(page).toHaveURL(`${base}/desk/${evidence.bookId}`)
    await expect(strip()).toContainText('排队中：前面还有书在拆')
    await collapseChat()
    await page.evaluate(() => document.fonts.ready)
    evidence.checks.importAndQueue = true
    evidence.phase = 'queued'
    await save()
    await fs.writeFile(path.join(data, 'queued.json'), JSON.stringify({ bookId: evidence.bookId, stage: 'queued', upto: 20, at: new Date().toISOString() }, null, 2))
    console.log(`QUEUED ${evidence.bookId}`)
  } else {
    await page.goto(`${base}/desk/${evidence.bookId}`)
    await expect(strip()).toBeVisible()
    await collapseChat()
    await page.evaluate(() => document.fonts.ready)
  }

  if (evidence.phase === 'queued') {
    await expect(strip()).toContainText('设定师在读第', { timeout: 240000 })
    await expect(strip()).toContainText('／20 章（拆到第 20 章）')
    await shot('demo-进度-读原文')
    evidence.checks.reading = true
    await expect(strip()).toContainText('主编在归单元', { timeout: 120000 })
    await shot('demo-进度-归单元')
    evidence.checks.groupingUnits = true
    // 等单元结果落盘后在归卷时停；归单元中途取消按既有后台规则不会采用未返回的结果。
    await expect(strip()).toContainText('主编在归卷', { timeout: 120000 })
    evidence.stopClickedWhile = await strip().innerText()
    await strip().getByRole('button', { name: '停下', exact: true }).click()
    const stopping = strip().getByRole('button', { name: '正在停：读完手上这几章就停', exact: true })
    await expect(stopping).toBeDisabled()
    evidence.checks.stoppingImmediate = true
    await expect(strip().getByRole('button', { name: '接着拆', exact: true })).toBeVisible({ timeout: 120000 })
    const stopped = await api(`/books/${evidence.bookId}`)
    assert.equal(stopped.teardown.stage, 'stopped')
    assert.equal(stopped.teardown.upto, 20)
    evidence.stopped = stopped.teardown
    evidence.phase = 'stopped'
    await save()
    console.log('STOPPED after unit save')
  }

  if (evidence.phase === 'stopped') {
    const tree = await api(`/books/${evidence.bookId}/outline-tree`)
    const units = tree.arcs.flatMap(arc => arc.volumes).flatMap(volume => volume.units).filter(unit => !unit.virtual)
    assert.ok(units.length, '真实拆出单元')
    evidence.unitsAtStop = units.map(unit => ({ title: unit.title, chapters: unit.chapters.map(chapter => chapter.index) }))
    await tab('大纲').click()
    await page.getByPlaceholder('找篇、卷、单元、章……').fill(units[0].title)
    await page.locator('button[title]').filter({ hasText: units[0].title }).first().click()
    await expect(page.locator('main')).toContainText(units[0].summary)
    await shot('demo-大纲单元')
    await tab('正文').click()
    await page.getByPlaceholder('找章节、搜原文……').fill('青灯旅途1')
    await page.getByTitle('第1章　青灯旅途1', { exact: true }).click()
    await page.getByPlaceholder('找章节、搜原文……').fill('')
    const fold = page.getByRole('button', { name: '这一章记下的', exact: true })
    await expect(fold).toHaveAttribute('aria-expanded', 'false')
    await fold.click()
    await expect(fold).toHaveAttribute('aria-expanded', 'true')
    await page.locator('main').evaluate(element => { element.scrollTop = element.scrollHeight })
    await expect(page.getByRole('button', { name: '下一章', exact: true })).toBeInViewport()
    await shot('demo-这一章记下的')
    const chapter = await api(`/books/${evidence.bookId}/chapters/1`)
    assert.ok(chapter.teardown.read_version)
    evidence.demoRecord = chapter.teardown.read
    evidence.checks.chapterRecordCollapsedThenExpanded = true
    await strip().getByRole('button', { name: '接着拆', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '开始拆《拆书界面验收合成书》', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('spinbutton', { name: '拆到第几章', exact: true })).toHaveValue('20')
    await dialog.getByRole('spinbutton', { name: '拆到第几章', exact: true }).fill('')
    await dialog.getByRole('button', { name: '开始拆', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    evidence.checks.resumeDialogDefault20AndWholeBook = true
    evidence.phase = 'resuming'
    await save()
    console.log('RESUMING whole book')
  }
  if (evidence.phase === 'resuming') {
    await expect(strip()).toContainText('拆完了 · 48 章', { timeout: 240000 })
    const done = await api(`/books/${evidence.bookId}`)
    assert.equal(done.teardown.stage, 'done')
    assert.equal(done.teardown.upto, null)
    const chapters = await api(`/books/${evidence.bookId}/chapters`)
    assert.equal(chapters.filter(chapter => chapter.teardown?.read).length, 48)
    assert.equal(chapters.filter(chapter => chapter.teardown?.failed).length, 0)
    evidence.done = done.teardown
    evidence.doneText = await strip().innerText()
    evidence.checks.done48 = true
    await tab('正文').click()
    await page.getByPlaceholder('找章节、搜原文……').fill('')
    await page.getByRole('button', { name: /^正文首页/ }).click()
    await shot('demo-拆完了')
    await page.getByRole('button', { name: '系统设置', exact: true }).click()
    await expect(page.getByLabel('拆书使用的模型', { exact: true })).toBeVisible()
    await expect(page.getByText('拆书时读原文、归单元归卷都用它：一本书要调几百次，挑便宜快、格式稳的', { exact: true })).toBeVisible()
    await page.locator('.settings-row').filter({ has: page.getByLabel('拆书使用的模型', { exact: true }) }).scrollIntoViewIfNeeded()
    await shot('模型分工')
    evidence.checks.teardownModelRole = true
    evidence.phase = 'complete'
    await save()
  }
  if (evidence.phase === 'complete' && process.argv[2] === 'settings') {
    // 可单独重取取景；不再导入、开拆或调用模型。
    await page.getByRole('button', { name: '系统设置', exact: true }).click()
    const role = page.getByLabel('拆书使用的模型', { exact: true })
    await expect(role).toBeVisible()
    await page.locator('.settings-row').filter({ has: role }).scrollIntoViewIfNeeded()
    await expect(role).toBeInViewport()
    await shot('模型分工')
    await save()
  }
  if (evidence.phase === 'complete' && process.argv[2] === 'records') {
    // 只重取已经拆完的第 1 章取景：清掉检索状态、滚至页末，折叠标题与翻章都留在画面内。
    await tab('正文').click()
    await page.getByPlaceholder('找章节、搜原文……').fill('青灯旅途1')
    await page.getByTitle('第1章　青灯旅途1', { exact: true }).click()
    await page.getByPlaceholder('找章节、搜原文……').fill('')
    const fold = page.getByRole('button', { name: '这一章记下的', exact: true })
    await expect(fold).toBeVisible()
    if (await fold.getAttribute('aria-expanded') !== 'true') await fold.click()
    await expect(fold).toHaveAttribute('aria-expanded', 'true')
    await page.locator('main').evaluate(element => { element.scrollTop = element.scrollHeight })
    await expect(page.getByRole('button', { name: '下一章', exact: true })).toBeInViewport()
    await shot('demo-这一章记下的')
    await save()
  }
  assert.deepEqual(evidence.errors, [])
  console.log(JSON.stringify({ phase: evidence.phase, bookId: evidence.bookId, checks: evidence.checks, screenshots: evidence.screenshots }))
} catch (error) {
  evidence.failure = { at: new Date().toISOString(), message: error.message, url: page.url(), body: (await page.locator('body').innerText()).slice(0, 7000) }
  await save()
  console.error(JSON.stringify(evidence.failure, null, 2))
  throw error
} finally { await browser.close() }
