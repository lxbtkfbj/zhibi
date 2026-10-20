/** 真实 TXT、真实独立 API；输入原文与运行状态只读 git 外文件。 */
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const input = JSON.parse(await fs.readFile(process.env.ZHIBI_APPEND_INPUT, 'utf8'))
const { base, api } = input
for (const url of [base, api]) {
  const u = new URL(url)
  assert.equal(u.hostname, '127.0.0.1')
  assert.ok(!['8000', '4320'].includes(u.port), '拒绝日常服务')
}
const out = path.resolve(import.meta.dirname, '../../docs/拆书补章节验收')
await fs.mkdir(out, { recursive: true })
const evidence = { at: new Date().toISOString(), base, api, checks: {}, screenshots: [], errors: [], mutations: [] }
const browser = await chromium.launch({ executablePath: process.env.ZHIBI_CHROMIUM || 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1720, height: 1100 }, reducedMotion: 'reduce' })
await context.addInitScript(() => {
  localStorage.setItem('zhibi:editorial-dock', 'ball')
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 }))
})
const page = await context.newPage()
const expect = baseExpect.configure({ timeout: 30000 })
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => {
  if (request.url().includes('/api/') && ['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) {
    evidence.mutations.push({ method: request.method(), path: new URL(request.url()).pathname })
  }
})
const get = async route => {
  const response = await page.request.get(`${api}${route}`)
  assert.equal(response.status(), 200, route)
  return response.json()
}
const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex')
const shot = async (name, fullPage = false) => {
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, name + '.png'), fullPage })
  evidence.screenshots.push(name + '.png')
}
const intro = async id => {
  await page.goto(`${base}/desk/${id}`)
  await page.locator('.desk-v2 .page h1').waitFor()
  await page.locator('header nav').getByText('简介', { exact: true }).click()
}

try {
  const profiles = await get('/llm/profiles')
  assert.ok(profiles.every(p => p.provider === 'demo' && !p.has_key), '不能存在真实模型配置')
  for (const key of (process.env.ZHIBI_APPEND_CASE || 'xie,civil').split(',')) {
    const { id, file } = input[key]
    const before = await get(`/books/${id}`)
    const oldLibrary = hash(await get(`/books/${id}/library`))
    const oldMerits = hash(before.teardown.merits)
    const oldSettings = hash(before.teardown.settings)
    const oldNames = hash(before.teardown.names)
    await intro(id)
    await expect(page.getByRole('link', { name: '补后面的章节', exact: true })).toBeVisible()
    await page.getByRole('link', { name: '补后面的章节', exact: true }).click()
    await expect(page.getByRole('heading', { name: '补后面的章节', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: '回书页', exact: true })).toHaveAttribute('href', `/desk/${id}`)
    await expect(page.locator('#teardown-title,#teardown-author')).toHaveCount(0)
    await shot(`${key}-上传前`)
    await page.getByLabel('选择 TXT 文件', { exact: true }).setInputFiles(file)
    await expect(page.getByTestId('teardown-append-summary')).toBeVisible()
    const preview = await get(`/teardown/${id}/append`)
    assert.equal(preview.mode, 'append')
    const count = preview.chapter_count
    assert.ok(count > 0)
    await expect(page.getByTestId('teardown-append-summary')).toHaveText(`新文件分出 ${count} 章，接在第 ${before.teardown.chapters} 章「${preview.previous.last.title}」后面，补上以后一共 ${before.teardown.chapters + count} 章。`)
    if (key === 'xie') {
      assert.equal(preview.previous.original_volumes, true)
      assert.ok(preview.duplicates.leading.length >= 2)
      assert.ok(preview.volumes.some(v => v.continued && v.index === 2))
      assert.ok(preview.number_issue_total > 0)
    } else {
      assert.equal(before.teardown.stage, 'done')
      assert.equal(before.teardown.chapters, 300)
      assert.equal(count, 368)
      assert.ok(preview.reopen.some(r => r.kind === 'unit'))
      assert.ok(preview.reopen.some(r => r.kind === 'volume'))
      await expect(page.getByText(/最后一个单元「.*」.*会和新补的章一起重新归/)).toBeVisible()
      await expect(page.getByText(/最后一卷「.*」会和新补的章一起重新归，名字和那段话会重写/)).toBeVisible()
    }
    // 待确认入口与刷新恢复，换编码不制造第二份文件。
    await shot(`${key}-确认页`, true)
    await page.getByRole('link', { name: '回书页', exact: true }).click()
    await expect(page.getByRole('link', { name: '补章节还没确认', exact: true })).toBeVisible()
    await page.getByRole('link', { name: '补章节还没确认', exact: true }).click()
    await expect(page.getByTestId('teardown-append-summary')).toBeVisible()
    await page.getByRole('button', { name: 'UTF-8', exact: true }).click()
    await expect(page.getByRole('button', { name: 'UTF-8', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: '先只补上，不拆', exact: true }).click()
    await expect(page).toHaveURL(`${base}/desk/${id}`)
    const after = await get(`/books/${id}`)
    assert.equal(after.teardown.chapters, before.teardown.chapters + count)
    assert.equal(after.teardown.adding, null)
    assert.equal(after.teardown.added.at(-1).first, before.teardown.chapters + 1)
    assert.equal(after.teardown.added.at(-1).last, after.teardown.chapters)
    assert.equal(hash(await get(`/books/${id}/library`)), oldLibrary, '补章节不改设定库')
    assert.equal(hash(after.teardown.merits), oldMerits, '补章节不改好在哪')
    assert.equal(hash(after.teardown.settings), oldSettings, '补章节不改整理记录')
    assert.equal(hash(after.teardown.names), oldNames, '补章节不改人名映射')
    if (before.teardown.upto == null) assert.equal(after.teardown.upto, before.teardown.chapters)
    if (key === 'civil') {
      assert.equal(after.teardown.stage, 'stopped')
      assert.equal(after.teardown.stop_reason, 'added')
    }
    await intro(id)
    await expect(page.locator('.page .meta').last()).toContainText(`补过 1 次，最近`)
    await shot(`${key}-补完简介`)
    const chapters = await get(`/books/${id}/chapters`)
    const last = chapters.at(-1)
    await page.evaluate(({ id, last }) => sessionStorage.setItem('zhibi:workspace-reading:' + id, JSON.stringify({ tab: '大纲', entry: 'overview', node: `c${last}`, chapter: 'home', open: ['book'] })), { id, last: last.index })
    await page.reload()
    await page.locator('.desk-v2 .page h1').waitFor()
    await expect(page.locator('.page h1')).toContainText(last.title)
    await shot(`${key}-补完目录`)
    evidence.checks[key] = { id, before: before.teardown.chapters, appended: count, after: after.teardown.chapters, added: after.teardown.added.at(-1), duplicates: preview.duplicates, junction: preview.junction, numberIssues: preview.number_issues, reopen: preview.reopen, volumePlan: preview.volumes, protection: { library: oldLibrary, settings: oldSettings, merits: oldMerits, names: oldNames }, stage: after.teardown.stage, upto: after.teardown.upto }
  }
  assert.deepEqual(evidence.errors, [])
} finally {
  await fs.writeFile(path.join(out, '浏览器验收.json'), JSON.stringify(evidence, null, 2))
  await browser.close()
}
console.log(JSON.stringify(evidence.checks, null, 2))
