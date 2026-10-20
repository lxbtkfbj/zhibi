/** 真文件补完后的「接着拆」：只连接此次独立副本，使用假模型 worker。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const input = JSON.parse(await fs.readFile(process.env.ZHIBI_APPEND_INPUT, 'utf8'))
const { base, api, civil: { id } } = input
assert.equal(new URL(base).origin, 'http://127.0.0.1:4353')
assert.equal(new URL(api).origin, 'http://127.0.0.1:8053')
const out = path.resolve(import.meta.dirname, '../../docs/拆书补章节验收')
const evidence = { at: new Date().toISOString(), errors: [], start: null }
const browser = await chromium.launch({ executablePath: process.env.ZHIBI_CHROMIUM || 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const page = await browser.newPage({ viewport: { width: 1720, height: 1100 }, reducedMotion: 'reduce' })
const expect = baseExpect.configure({ timeout: 30000 })
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => {
  if (request.method() === 'POST' && request.url().endsWith(`/teardown/${id}/start`)) evidence.start = request.postDataJSON()
})
const get = async suffix => {
  const response = await page.request.get(`${api}/books/${id}${suffix}`)
  assert.equal(response.status(), 200)
  return response.json()
}
try {
  const before = await get('')
  assert.equal(before.teardown.stop_reason, 'added')
  assert.equal(before.teardown.upto, 300)
  assert.equal(before.teardown.chapters, 668)
  await page.addInitScript(id => {
    localStorage.setItem('zhibi:editorial-dock', 'ball')
    sessionStorage.setItem('zhibi:workspace-reading:' + id, JSON.stringify({ tab: '简介', entry: 'overview', node: 'book', chapter: 'home', open: [] }))
  }, id)
  await page.goto(`${base}/desk/${id}`)
  await page.locator('header .progress').getByText('接着拆', { exact: true }).click()
  const dialog = page.getByRole('dialog')
  // added 的旧 upto 是后台上次目标，不应再填成这次接着拆的目标。
  await expect(dialog.getByRole('spinbutton', { name: '拆到第几章', exact: true })).toHaveValue('')
  await expect(dialog.getByRole('spinbutton')).toHaveAttribute('placeholder', '不填就是全本（668 章）')
  await dialog.getByRole('button', { name: '开始拆', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect.poll(async () => (await get('')).teardown.stage, { timeout: 240000, intervals: [500, 1000, 2000] }).toBe('done')
  const after = await get('')
  assert.equal(after.teardown.read, 668)
  assert.equal(after.teardown.settings.upto, 668)
  assert.deepEqual(evidence.start, { upto: null })
  await page.reload()
  await page.locator('header nav').getByText('简介', { exact: true }).click()
  await expect(page.locator('.page .statline')).toContainText('已拆 668 / 668 章')
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, 'civil-接着拆到668.png') })
  evidence.book_id = id
  evidence.before = { stage: before.teardown.stage, upto: before.teardown.upto, read: before.teardown.read }
  evidence.after = { stage: after.teardown.stage, upto: after.teardown.upto, read: after.teardown.read, settings: after.teardown.settings }
  assert.deepEqual(evidence.errors, [])
} finally {
  await fs.writeFile(path.join(out, '接着拆浏览器验收.json'), JSON.stringify(evidence, null, 2))
  await browser.close()
}
console.log(JSON.stringify(evidence, null, 2))
