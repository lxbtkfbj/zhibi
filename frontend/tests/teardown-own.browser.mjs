/** 拆书第一批任务 2：作者书回归与 40 章小拆书性能。只允许独立验收环境，模型须全为 demo。
 * TEST_BASE_URL=http://127.0.0.1:14324 ZHIBI_CHROMIUM=<Chrome路径> node tests/teardown-own.browser.mjs [own|perf]
 * 作者书 UI 新建、UI 开写；通过独立 API 添加一篇文字及本书演示设置，不直接写数据库、不伪造模型结果。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = process.env.TEST_BASE_URL
assert.equal(base, 'http://127.0.0.1:14324', '只允许任务 2 独立前端，禁止操作日常服务')
const root = fileURLToPath(new URL('../../', import.meta.url))
const data = path.join(root, 'data/teardown-task2')
const output = path.join(root, 'docs/拆书第一批验收')
await fs.mkdir(data, { recursive: true })
await fs.mkdir(output, { recursive: true })
const evidencePath = path.join(data, 'own.json')
const evidence = await fs.readFile(evidencePath, 'utf8').then(JSON.parse).catch(() => ({ checks: {}, errors: [], requests: [] }))
if (evidence.failure) {
  evidence.failures = [...(evidence.failures ?? []), evidence.failure]
  delete evidence.failure
}
const phase = process.argv[2]
const wanted = name => !phase || phase === name
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const page = await browser.newPage({ viewport: { width: 1720, height: 1100 }, reducedMotion: 'reduce' })
const expect = baseExpect.configure({ timeout: 60_000 })
const persist = () => fs.writeFile(evidencePath, JSON.stringify(evidence, null, 2))
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => {
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) evidence.requests.push({ method: request.method(), url: request.url(), body: request.postData() })
})
const api = async (route, { method = 'GET', body, multipart } = {}) => {
  const response = await page.request.fetch(`${base}/api${route}`, { method, data: body, multipart })
  if (method !== 'GET') evidence.api_requests = [...(evidence.api_requests ?? []), { method, route, body, multipart: multipart ? 'synthetic TXT buffer' : undefined, status: response.status() }]
  assert.ok(response.ok(), `${method} ${route}: ${response.status()} ${await response.text()}`)
  if (response.status() === 204) return null
  return response.json()
}
const tab = name => page.getByRole('button', { name, exact: true }).first()
const nextFrame = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => resolve(performance.now()))))
const time = async (name, action, ready) => {
  const start = await page.evaluate(() => performance.now())
  await action()
  await ready()
  const duration = Math.round((await nextFrame() - start) * 10) / 10
  evidence.small_performance_ms[name] = duration
  console.log(`${name}: ${duration} ms`)
  return duration
}

try {
  const profiles = await api('/llm/profiles')
  assert.ok(profiles.length > 0 && profiles.every(profile => profile.provider === 'demo'), '验收只能使用演示模式')
  evidence.environment = { base, profiles: profiles.map(profile => ({ id: profile.id, provider: profile.provider })), timestamp: new Date().toISOString() }

  if (wanted('own')) {
    let id = evidence.own_book_id
    if (!id) {
      await page.goto(`${base}/new`)
      await page.getByRole('textbox', { name: '书名', exact: true }).fill('任务 2 作者自己的书')
      await page.getByLabel('简介', { exact: true }).fill('楚风重生后，凭轮回镜辨认旧案，在小城坊市追查害死自己的真凶。')
      await page.getByRole('button', { name: '下一步', exact: true }).click()
      await page.waitForURL(/\/desk\/[0-9a-f-]+$/)
      id = new URL(page.url()).pathname.split('/')[2]
      evidence.own_book_id = id
      await persist()
    } else await page.goto(`${base}/desk/${id}`)

    const detail = await api(`/books/${id}`)
    assert.equal(detail.source, 'new')
    await expect(page.getByRole('button', { name: '本书设置', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '本书设置', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '本书设置', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: '本书设置', exact: true })).toHaveCount(0)
    evidence.checks.own_settings = true

    await tab('大纲').click()
    // 已写完一章后默认可能选中已完成的卷；选全书核对仍可帮写结局。
    await page.getByRole('button', { name: /^全书/ }).first().click()
    await expect(page.getByRole('button', { name: /编辑部帮写/ }).first()).toBeVisible()
    evidence.checks.own_outline_help = true
    const tree = await api(`/books/${id}/outline-tree`)
    if (!tree.arcs.some(arc => arc.node_id || arc.volumes.length)) {
      await api(`/books/${id}/arcs`, { method: 'POST', body: { title: '小城追凶', text: '小城坊市；楚风要追回旧案证据；掌柜阻挠；他用轮回镜识破假账，在坊市拿到线索。' } })
    }
    await api(`/books/${id}/settings`, { method: 'PATCH', body: { effort_preset: 'quick', chapter_words: 600, trial_read: false, volume_approval: false, chapters_approval: false, segment_approval: false } })
    evidence.own_preparation = 'UI 新建作者书；独立 API 添加一篇大纲文字、600 字与不暂停的演示设置；正文通过 UI 开写，由 demo 写作流程生成；没有直接写数据库。'
    await page.reload()
    await tab('正文').click()
    if (!(await api(`/books/${id}`)).chapters_final) {
      await expect(page.getByRole('button', { name: '写 1 章', exact: true })).toBeVisible()
      await page.getByRole('button', { name: '写 1 章', exact: true }).click()
      await page.getByRole('button', { name: '开写', exact: true }).last().click()
      await expect.poll(async () => {
        const current = await api(`/books/${id}`)
        if (current.active_job?.status === 'failed') throw new Error(current.active_job.error || '演示写作任务失败')
        return current.chapters_final
      }, { timeout: 240_000 }).toBeGreaterThan(0)
    }
    await expect.poll(async () => (await api(`/books/${id}`)).active_job?.status ?? 'idle', { timeout: 120_000 }).not.toMatch(/running|queued|waiting_author/)
    const chapters = await api(`/books/${id}/chapters`)
    const first = chapters.find(chapter => chapter.status === 'final')
    assert.ok(first)
    const chapter = await api(`/books/${id}/chapters/${first.index}`)
    assert.ok(chapter.content.includes('演示模式'), '正文必须由演示模式生成')
    assert.ok(chapter.content.includes('坊市'), '演示正文含可搜索的词')
    evidence.own_chapter = { index: first.index, title: first.title, chars: chapter.word_count, demo: true }
    evidence.checks.own_write = true
    await page.reload()
    await tab('正文').click()
    await expect(page.getByPlaceholder('找章节、搜原文……')).toBeVisible()
    const search = page.getByPlaceholder('找章节、搜原文……')
    await search.fill('坊市')
    await search.press('Enter')
    await expect(page.getByText(/原文里有「坊市」的章（\d+ 章）/)).toBeVisible()
    const result = page.getByRole('button', { name: new RegExp(`第 ${first.index} 章.*次`) }).first()
    await result.click()
    const editor = page.getByRole('textbox', { name: '正文', exact: true })
    await expect(editor).toBeVisible()
    await expect(editor.locator('mark[data-text-match]').first()).toBeVisible()
    assert.equal(await editor.getAttribute('contenteditable'), 'true', '作者自己的正文仍可编辑')
    await nextFrame()
    const mark = await editor.locator('mark[data-text-match]').first().boundingBox()
    assert.ok(mark && mark.y > 0 && mark.y < 1100, '搜索点击定位到第一处词')
    evidence.checks.own_search_located = true
    evidence.own_search = await api(`/books/${id}/search?q=${encodeURIComponent('坊市')}`)
    await page.evaluate(() => document.fonts.ready)
    await page.screenshot({ path: path.join(output, 'task2-作者书搜索.png') })
    evidence.screenshot = 'docs/拆书第一批验收/task2-作者书搜索.png'
    await search.fill('任务2作者书不存在的正文词')
    await search.press('Enter')
    await expect(page.getByText('正文里没有「任务2作者书不存在的正文词」', { exact: true })).toBeVisible()
    evidence.checks.own_empty_search = true
    await search.fill('')
    await tab('正文').click()
    await page.getByRole('button', { name: /^接着写/ }).first().click()
    await expect(page.getByRole('button', { name: '写 1 章', exact: true })).toBeVisible()
    evidence.checks.own_write_controls_remain = true
    await persist()
    console.log(`作者书 ${id}：写作、设置、帮写、搜索定位及空结果通过`)
  }

  if (wanted('perf')) {
    let id = evidence.small_book_id
    if (!id) {
      const body = ['书名：任务 2 四十章性能小书', '作者：验收程序', '第一卷 小城'].concat(Array.from({ length: 40 }, (_, index) => [`第${index + 1}章 小书第${index + 1}回`, (`银杏钟在城楼上响起，这是小书第${index + 1}章。楚风走过坊市，停在旧药铺前，想起昨晚见到的信。`).repeat(20)].join('\n'))).join('\n\n')
      const preview = await api('/teardown', { method: 'POST', multipart: { file: { name: '任务2四十章性能小书.txt', mimeType: 'text/plain', buffer: Buffer.from(body, 'utf8') } } })
      assert.equal(preview.chapter_count, 40)
      const imported = await api(`/teardown/${preview.book_id}/import`, { method: 'POST', body: { title: preview.title, author: preview.author, include: [] } })
      id = imported.id
      evidence.small_book_id = id
      evidence.small_chapters = imported.teardown.chapters
      evidence.small_preparation = '程序合成 40 章 TXT，只经独立上传与导入 API 导入；不调用模型、不写日常库。'
      await persist()
    }
    evidence.small_performance_ms = {}
    await page.goto(base)
    const link = page.locator(`a[href="/desk/${id}"]`).first()
    await expect(link).toBeVisible()
    await time('打开书', () => link.click(), () => expect(page.getByRole('button', { name: '从第 1 章读起', exact: true })).toBeVisible())
    await time('切大纲', () => tab('大纲').click(), () => expect(page.getByPlaceholder('找篇、卷、单元、章……')).toBeVisible())
    const virtual = page.getByRole('button', { name: '还没归单元', exact: true })
    const volume = page.getByRole('button', { name: /第一卷.*小城/ }).first()
    if (!(await virtual.isVisible())) {
      await volume.click()
      if (!(await virtual.isVisible())) await volume.click()
    }
    await expect(virtual).toBeVisible()
    const row = virtual.locator('..')
    const expand = row.getByRole('button', { name: '展开', exact: true })
    if (!(await expand.count())) await row.getByRole('button', { name: '收起', exact: true }).click()
    await time('展开还没归单元', () => row.getByRole('button', { name: '展开', exact: true }).click(), () => expect(page.getByRole('button', { name: /第1章.*小书第1回/ }).first()).toBeVisible())
    await time('切正文', () => tab('正文').click(), () => expect(page.getByRole('button', { name: '从第 1 章读起', exact: true })).toBeVisible())
    await page.getByRole('button', { name: '从第 1 章读起', exact: true }).click()
    await expect(page.locator('.chapter-prose')).toContainText('这是小书第1章')
    await time('翻一章', () => page.keyboard.press('ArrowRight'), () => expect(page.locator('.chapter-prose')).toContainText('这是小书第2章'))
    const query = page.getByPlaceholder('找章节、搜原文……')
    await time('搜一个词', () => query.fill('银杏钟'), () => expect(page.getByText('原文里有「银杏钟」的章（40 章）', { exact: true })).toBeVisible())
    evidence.small_performance_method = '同一新建浏览器上下文；performance.now() 从真实点击/键盘动作前到目标 DOM 可见并过一次 requestAnimationFrame；搜索含 400ms 防抖、请求与绘制。开发服务器，单次量，不含模型与首冷启动。'
    await persist()
    console.log(`小拆书 ${id}：40 章六项性能完成`)
  }
  assert.deepEqual(evidence.errors, [], '浏览器不能有 pageerror')
} catch (error) {
  evidence.failure = String(error.stack || error)
  await persist()
  console.error((await page.locator('body').innerText()).slice(0, 6000))
  throw error
} finally {
  await persist()
  await browser.close()
}
