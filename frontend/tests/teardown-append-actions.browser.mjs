/** 仅在独立验收环境新建合成书：取消双确认、待确认入口、primary补上接着拆。 */
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { promisify } from 'node:util'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:4353'
const api = process.env.TEST_API_URL || 'http://127.0.0.1:8053/api'
for (const value of [base, api]) {
  const url = new URL(value)
  assert.ok(['127.0.0.1', 'localhost'].includes(url.hostname), '只许独立本地验收服务')
  assert.ok(url.port && !['8000', '4320'].includes(url.port), '拒绝日常服务')
}
const dsn = process.env.ZHIBI_APPEND_ACTIONS_DSN
assert.ok(dsn?.includes('zhibi_append_accept') && /(?:localhost|127\.0\.0\.1):5553\//.test(dsn), '只读核查仅允许本次5553独立验收库')
const out = path.resolve(import.meta.dirname, '../../docs/拆书补章节验收')
await fs.mkdir(out, { recursive: true })
const evidence = { at: new Date().toISOString(), base, api, policy: '只新建本脚本的合成书；不访问两本真实验收书；独立demo模型；数据库只读核查', checks: [], screenshots: [], requests: [], pageErrors: [] }
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1500, height: 1100 }, reducedMotion: 'reduce' })
await context.addInitScript(() => {
  localStorage.setItem('zhibi:editorial-dock', 'ball')
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 }))
})
const page = await context.newPage()
const expect = baseExpect.configure({ timeout: 30000 })
page.on('pageerror', error => evidence.pageErrors.push(error.message))
page.on('request', request => {
  if (request.url().includes('/api/') && request.method() !== 'GET') evidence.requests.push({ method: request.method(), path: new URL(request.url()).pathname })
})
let id
const url = route => `${api}${route}`
const get = async route => {
  const response = await context.request.get(url(route))
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`)
  return response.json()
}
const post = async (route, data = {}) => {
  assert.ok(!id || route.includes(id), '前置之后只操作本脚本创建的书')
  const response = await context.request.post(url(route), { data })
  assert.ok(response.ok(), `${route}: ${await response.text()}`)
  return response.json()
}
const intro = async () => {
  await page.goto(`${base}/desk/${id}`)
  await page.locator('.desk-v2 .page h1').waitFor()
  await page.locator('header nav a').filter({ hasText: /^简介$/ }).click()
}
const shot = async name => {
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true })
  evidence.screenshots.push(`${name}.png`)
}
const waitDone = async () => {
  let latest
  await expect.poll(async () => {
    latest = await get(`/books/${id}`)
    if (latest.active_job?.status === 'failed') throw new Error(latest.active_job.error)
    return latest.teardown.stage
  }, { timeout: 120000, intervals: [300, 600, 1000] }).toBe('done')
  return latest
}
const readDb = async () => {
  const code = `import asyncio,json,os,sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
async def main():
    engine=create_async_engine(os.environ['ZHIBI_APPEND_ACTIONS_DSN'])
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            p={'id':sys.argv[1]}
            jobs=(await conn.execute(text('SELECT id::text,status,params FROM jobs WHERE book_id=CAST(:id AS uuid) ORDER BY created_at,id'),p)).mappings().all()
            chapters=(await conn.execute(text('SELECT index,title,unit_id::text,teardown FROM chapters WHERE book_id=CAST(:id AS uuid) ORDER BY index'),p)).mappings().all()
            print(json.dumps({'jobs':[dict(r) for r in jobs],'chapters':[dict(r) for r in chapters]},ensure_ascii=False,default=str))
    finally:
        await engine.dispose()
if sys.platform=='win32':
    asyncio.run(main(),loop_factory=asyncio.SelectorEventLoop)
else:
    asyncio.run(main())`
  const { stdout } = await promisify(execFile)('uv', ['run', '--project', 'backend', 'python', '-c', code, id], {
    cwd: path.resolve(import.meta.dirname, '../..'), env: { ...process.env, NO_PROXY: 'localhost,127.0.0.1,::1', PYTHONIOENCODING: 'utf-8' }, maxBuffer: 8 * 1024 * 1024,
  })
  return JSON.parse(stdout.trim())
}
const nextText = '第四章 灯下的新线索\n林舟在灯下找到第四枚木牌，他沿着河岸继续追查。\n第五章 渡口相逢\n林舟赶到渡口，和守船的人核对木牌，终于找到了下一条路。'
const uploadNext = async () => {
  await intro()
  await page.getByTestId('teardown-append-entry').click()
  await expect(page.getByRole('heading', { name: '补后面的章节', exact: true })).toBeVisible()
  await page.getByLabel('选择 TXT 文件', { exact: true }).setInputFiles({ name: '动作合成-后2章.txt', mimeType: 'text/plain', buffer: Buffer.from(nextText) })
  await expect(page.getByTestId('teardown-append-summary')).toContainText('新文件分出 2 章')
}

try {
  const profiles = await get('/llm/profiles')
  assert.ok(profiles.every(profile => profile.provider === 'demo' && !profile.has_key), '不允许真实模型配置')
  const title = `补章节动作合成-${Date.now()}`
  const original = '第一章 雨夜来客\n林舟走进雨夜的旧屋，门后传来木牌落地的声音。\n第二章 河边的脚印\n林舟跟着脚印走向河边，他认出了旧友留下的记号。\n第三章 旧桥上的约定\n林舟在旧桥上等到朋友，两人决定一起追查木牌的来历。'
  const uploaded = await context.request.post(url('/teardown'), { multipart: { file: { name: `${title}.txt`, mimeType: 'text/plain', buffer: Buffer.from(original) } } })
  assert.equal(uploaded.status(), 201, await uploaded.text())
  const initialPreview = await uploaded.json()
  assert.equal(initialPreview.chapter_count, 3)
  id = initialPreview.book_id
  evidence.book = { id, title }
  await post(`/teardown/${id}/import`, { title, include: [] })
  await post(`/teardown/${id}/start`, { upto: null })
  const before = await waitDone()
  assert.equal(before.teardown.chapters, 3)
  assert.equal(before.teardown.upto, null)
  const beforeDb = await readDb()
  assert.ok(beforeDb.chapters.every(chapter => chapter.teardown.read_version === 1))
  evidence.before = { chapters: 3, stage: before.teardown.stage, upto: before.teardown.upto, readVersions: beforeDb.chapters.map(chapter => chapter.teardown.read_version) }
  evidence.checks.push('仅API创建合成3章书，独立demo worker拆完；upto为空，旧章read_version均为1')

  await uploadNext()
  await page.getByRole('link', { name: '回书页', exact: true }).click()
  await expect(page.getByTestId('teardown-append-entry')).toHaveText('补章节还没确认')
  await shot('动作-待确认入口')
  await page.getByTestId('teardown-append-entry').click()
  await expect(page.getByTestId('teardown-append-summary')).toContainText('一共 5 章')
  await page.getByRole('button', { name: '不补了', exact: true }).click()
  await expect(page.getByRole('button', { name: '确定不补了？再点一次', exact: true })).toBeVisible()
  assert.equal((await get(`/teardown/${id}/append`)).chapter_count, 2, '第一次点击不能删除待确认文件')
  await shot('动作-取消二次确认')
  const deleted = page.waitForResponse(response => response.request().method() === 'DELETE' && response.url().endsWith(`/teardown/${id}/append`))
  await page.getByRole('button', { name: '确定不补了？再点一次', exact: true }).click()
  assert.equal((await deleted).status(), 204)
  await expect(page).toHaveURL(`${base}/desk/${id}`)
  const cancelled = await get(`/books/${id}`)
  assert.equal(cancelled.teardown.chapters, 3)
  assert.equal(cancelled.teardown.adding, null)
  const noPending = await context.request.get(url(`/teardown/${id}/append`))
  assert.equal(noPending.status(), 404)
  assert.equal((await noPending.json()).detail, '没有待确认的补章节')
  evidence.cancel = { firstClickKeptPending: true, status: 204, bookSurvives: true, chapters: cancelled.teardown.chapters, adding: cancelled.teardown.adding }
  evidence.checks.push('待确认入口文字正确；取消第一次只确认，第二次DELETE 204；原书3章仍在，待确认GET 404')

  await uploadNext()
  const primary = page.getByRole('button', { name: '补上并接着拆', exact: true })
  await expect(primary).toBeEnabled()
  await expect(page.getByRole('spinbutton', { name: '拆到第几章', exact: true })).toHaveAttribute('placeholder', '不填就是全本（5 章）')
  await shot('动作-补上并接着拆')
  const appended = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/teardown/${id}/append/import`))
  await primary.click()
  const appendedResponse = await appended
  assert.equal(appendedResponse.status(), 200, await appendedResponse.text())
  assert.deepEqual(appendedResponse.request().postDataJSON(), { include: [], start: { upto: null } })
  await expect(page).toHaveURL(`${base}/desk/${id}`)
  const after = await waitDone()
  assert.equal(after.teardown.chapters, 5)
  assert.equal(after.teardown.read, 5)
  assert.equal(after.teardown.added.length, 1)
  assert.deepEqual([after.teardown.added[0].first, after.teardown.added[0].last], [4, 5])
  const afterDb = await readDb()
  assert.equal(afterDb.jobs.length, 2)
  const job = afterDb.jobs.at(-1)
  assert.equal(job.status, 'succeeded')
  assert.equal(job.params.retry_failed_only, false)
  assert.equal(job.params.previous_teardown.upto, 3)
  assert.equal(job.params.previous_teardown.stage, 'stopped')
  assert.equal(job.params.previous_teardown.stop_reason, 'added')
  assert.equal(afterDb.chapters.length, 5)
  assert.ok(afterDb.chapters.every(chapter => chapter.teardown.read_version === 1 && chapter.unit_id), '旧章不重读，新章各读一次，五章都归单元')
  evidence.after = { chapters: 5, read: 5, stage: after.teardown.stage, added: after.teardown.added, jobs: afterDb.jobs.map(({ id, status, params }) => ({ id, status, retry_failed_only: params.retry_failed_only, previous_upto: params.previous_teardown.upto, previous_stage: params.previous_teardown.stage })), chapterVersions: afterDb.chapters.map(chapter => ({ index: chapter.index, read_version: chapter.teardown.read_version, unit_id: chapter.unit_id })) }
  evidence.checks.push('真实点击primary后返回书页，demo worker完成5章；只读DB核previous_upto=3、retry_failed_only=false、旧3章仍读1次、新2章各读1次且全部归单元')
  await intro()
  await expect(page.locator('.page .meta').nth(1)).toContainText('补过 1 次，最近')
  await expect(page.getByTestId('teardown-append-entry')).toHaveText('补后面的章节')
  await shot('动作-完成五章')
  assert.deepEqual(evidence.pageErrors, [])
  evidence.passed = true
} catch (error) {
  evidence.passed = false
  evidence.failure = { message: error.message, stack: error.stack }
  await shot('动作-失败诊断').catch(() => {})
  throw error
} finally {
  await fs.writeFile(path.join(out, '追加动作.json'), JSON.stringify(evidence, null, 2))
  await browser.close()
}
console.log(JSON.stringify({ passed: evidence.passed, book: evidence.book, checks: evidence.checks, screenshots: evidence.screenshots }, null, 2))
