/** 第三包任务 5 补充：在 UI 新建独立演示书，真实展开卷并验证作者修改。只读 API 核对。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = process.env.TEST_BASE_URL
assert.equal(base, 'http://127.0.0.1:4355', '仅任务 5 隔离环境')
const data = path.resolve('../data/third-package-task5/outline-expand-browser.json')
const output = path.resolve('../docs/第三包验收')
const freshEvidence = () => ({ screenshots: [], requests: [], errors: [] })
// 默认每次 UI 新建书；仅中途排查失败时显式复用本脚本自己的演示书，不接触主验收书。
const evidence = process.env.TASK5_EXPAND_RESUME === '1' ? await fs.readFile(data, 'utf8').then(JSON.parse).catch(freshEvidence) : freshEvidence()
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM })
const page = await browser.newPage({ viewport: { width: 1720, height: 1180 }, reducedMotion: 'reduce' })
const expect = baseExpect.configure({ timeout: 120_000 })
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => { if (['POST', 'PATCH', 'DELETE'].includes(request.method())) evidence.requests.push({ method: request.method(), url: request.url(), body: request.postData() }) })
const api = async route => { const response = await page.request.get(`${base}/api${route}`); assert.equal(response.status(), 200, route); return response.json() }
const shot = async name => { await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(350); const file = `任务5-补充卷展开-${name}.png`; await page.screenshot({ path: path.join(output, file) }); evidence.screenshots.push(file); console.log(file) }
const save = () => fs.writeFile(data, JSON.stringify(evidence, null, 2))
const navigate = suffix => page.goto(`${base}/books/${evidence.book_id}/${suffix}`)
const tree = () => api(`/books/${evidence.book_id}/outline-tree`)
const volume = async () => (await tree()).arcs.flatMap(arc => arc.volumes).find(item => item.index === 2)
const visible = item => ({ title: item.title, summary: item.summary, count: item.chapter_count, locked: item.locked })

try {
  assert.ok((await api('/llm/profiles')).every(profile => profile.provider === 'demo'))
  if (!evidence.book_id) {
    await page.goto(base)
    await page.locator('textarea').first().fill('第三包任务5补充卷展开专用演示书：楚风带着轮回镜重生，寻找青云宗旧案的真相。')
    await page.getByRole('button', { name: '一口气做完再给我看', exact: true }).click()
    await page.getByRole('button', { name: '交给编辑部', exact: true }).click()
    await page.waitForURL(/\/books\//)
    evidence.book_id = new URL(page.url()).pathname.split('/')[2]
    await save()
  }
  if (!evidence.first_write) {
    await navigate('')
    await expect(page.getByRole('button', { name: '确认，开写', exact: true })).toBeVisible()
    await navigate('settings')
    await page.getByRole('button', { name: '省时', exact: true }).click()
    await page.getByRole('switch', { name: '新书前 3 章先给我试读', exact: true }).uncheck()
    await page.getByRole('spinbutton', { name: '每章字数', exact: true }).fill('600')
    await page.getByRole('heading', { name: '本书设置', exact: true }).click()
    await expect.poll(async () => (await api(`/books/${evidence.book_id}/settings`)).settings.chapter_words).toBe(600)
    await navigate('outline?node=volume-2')
    await page.getByTestId('outline-detail').getByRole('button', { name: '自己改', exact: true }).click()
    const edit = page.getByRole('dialog', { name: '自己改', exact: true })
    await edit.getByRole('textbox', { name: '名称', exact: true }).fill('作者保留的第二卷')
    await edit.getByRole('textbox', { name: '一段话', exact: true }).fill('作者指定：楚风先查清旧账，再在宗门大会上公开证据。卷名、这一段话和锁不许被展开覆盖。')
    await edit.getByRole('button', { name: '保存', exact: true }).click()
    await page.getByRole('spinbutton', { name: '章数', exact: true }).fill('6')
    await page.getByRole('button', { name: '改章数', exact: true }).click()
    await page.getByTestId('outline-detail').getByRole('button', { name: '锁住', exact: true }).click()
    await expect.poll(async () => (await volume()).locked).toBe(true)
    evidence.before = visible(await volume())
    evidence.volume_id = (await volume()).id
    await shot('01-作者卷纲基线')
    await page.getByRole('button', { name: '确认，开写', exact: true }).click()
    await expect.poll(async () => {
      const book = await api(`/books/${evidence.book_id}`)
      if (book.active_job?.status === 'failed') throw new Error(book.active_job.error)
      return book.chapters_final
    }).toBe(3)
    await expect.poll(async () => (await api(`/books/${evidence.book_id}`)).active_job?.status ?? 'idle').not.toMatch(/running|queued/)
    evidence.first_write = true
    await save()
  }
  await navigate('outline?node=volume-2')
  if (!evidence.expanded) {
    const before = await volume()
    assert.deepEqual(visible(before), evidence.before)
    if (!before.units.length) await page.getByRole('button', { name: '展开这一个', exact: true }).click()
    await expect.poll(async () => (await volume()).units.length).toBeGreaterThan(0)
    await expect.poll(async () => (await api(`/books/${evidence.book_id}`)).active_job?.status ?? 'idle').not.toMatch(/running|queued/)
    const after = await volume()
    assert.deepEqual(visible(after), evidence.before, '展开不覆盖作者已经看过的卷名、一段话、章数和锁')
    const stored = (await api(`/books/${evidence.book_id}/outline`)).volumes.find(item => item.id === after.id)
    assert.equal(stored.status, 'approved', '树的已规划展示态以外，存库状态必须已经批准，不再进入卷纲拍板')
    evidence.stored_volume = stored
    evidence.after = after
    evidence.unit_id = after.units[0].id
    const versions = await api(`/books/${evidence.book_id}/versions?target_type=volume&target_id=${after.id}`)
    const unitVersions = await api(`/books/${evidence.book_id}/versions?target_type=unit&target_id=${evidence.unit_id}`)
    assert.ok(versions.some(version => version.note === '提前展开'))
    assert.ok(unitVersions.some(version => version.note === '提前展开'))
    evidence.versions = { volume: versions, unit: unitVersions }
    await expect(page.getByRole('button', { name: '展开这一个', exact: true })).toHaveCount(0)
    await page.getByTestId('outline-writing-details').locator('summary').click()
    await shot('02-卷展开保留作者稿并记版本')
    evidence.expanded = true
    await save()
  }
  await navigate(`outline?node=unit-${evidence.unit_id}`)
  const detail = page.getByTestId('outline-detail')
  const field = detail.locator('[data-selectable-text]').first()
  await field.evaluate(element => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode)
    const node = nodes.find(item => item.textContent.length)
    const range = document.createRange(); range.setStart(node, 0); range.setEnd(node, Math.min(node.textContent.indexOf('。') + 1 || node.textContent.length, node.textContent.length))
    const selected = window.getSelection(); selected.removeAllRanges(); selected.addRange(range); document.dispatchEvent(new Event('selectionchange'))
  })
  await detail.getByRole('button', { name: '改这一句', exact: true }).click()
  await detail.getByRole('menu', { name: '选择修改方式' }).getByRole('button', { name: '给我几个写法', exact: true }).click()
  const candidates = detail.getByRole('region', { name: '候选写法', exact: true })
  await expect(candidates.getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
  await shot('03-新单元选句给三个写法')
  await candidates.getByRole('button', { name: '用这个', exact: true }).first().click()
  await expect(field.locator('mark')).toBeVisible()
  await detail.getByRole('button', { name: '锁住', exact: true }).click()
  await expect(detail.getByRole('button', { name: '解锁', exact: true })).toBeVisible()
  await detail.getByRole('spinbutton', { name: '章数', exact: true }).fill('4')
  await detail.getByRole('button', { name: '改章数', exact: true }).click()
  await expect.poll(async () => (await volume()).units.find(item => item.id === evidence.unit_id).chapter_count).toBe(4)
  evidence.unit_after_edit = (await volume()).units.find(item => item.id === evidence.unit_id)
  assert.equal(evidence.unit_after_edit.locked, true)
  await shot('04-采用写法锁住与改章数')
  await detail.getByRole('button', { name: '历史', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '版本历史' })).toContainText('提前展开')
  await shot('05-新单元完整版本历史')
  assert.deepEqual(evidence.errors, [])
  evidence.passed = true
  delete evidence.failure
  await save()
  console.log(JSON.stringify({ book_id: evidence.book_id, passed: true, screenshots: evidence.screenshots }))
} catch (error) {
  evidence.failure = String(error)
  await shot('失败现场').catch(() => {})
  await save()
  throw error
} finally { await browser.close() }
