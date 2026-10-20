/** 拆书第一批任务 2：仅允许独立演示端口；桌面 TXT 只读上传。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = 'http://127.0.0.1:14324'
assert.equal(process.env.TEST_BASE_URL, base, '只在独立验收前端运行')
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/拆书第一批验收')
const stateFile = path.join(root, 'data/teardown-task2/browser.json')
const storageFile = path.join(root, 'data/teardown-task2/browser-storage.json')
await fs.mkdir(output, { recursive: true })
const evidence = await fs.readFile(stateFile, 'utf8').then(JSON.parse).catch(() => ({ books: [], screenshots: [], checks: {}, errors: [], mutations: [] }))
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM })
const context = await browser.newContext({ viewport: { width: 1720, height: 1100 }, reducedMotion: 'reduce', storageState: await fs.access(storageFile).then(() => storageFile).catch(() => undefined) })
const page = await context.newPage()
const expect = baseExpect.configure({ timeout: 30000 })
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => { if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) evidence.mutations.push({ method: request.method(), url: request.url(), body: request.postData()?.slice(0, 2000) }) })
const save = async () => { await fs.writeFile(stateFile, JSON.stringify(evidence, null, 2)); await context.storageState({ path: storageFile }) }
const api = async route => { const result = await page.request.get(`${base}/api${route}`); assert.equal(result.status(), 200, route); return result.json() }
const tab = name => page.locator('header nav').getByRole('button', { name, exact: true })
const shot = async (name, fullPage = false) => {
  const collapseChat = page.getByTestId('editorial-header').getByRole('button', { name: '收起', exact: true })
  if (await collapseChat.count()) await collapseChat.click()
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(150)
  const file = `task2-${name}.png`
  await page.screenshot({ path: path.join(output, file), fullPage })
  if (!evidence.screenshots.includes(file)) evidence.screenshots.push(file)
}
const home = async () => { await page.goto(base); await expect(page.getByRole('button', { name: '拆一本书', exact: true }).first()).toBeVisible() }
const shelfOpen = async book => { await home(); await page.locator(`a[href="/desk/${book.id}"]`).last().click(); await expect(page.locator('main').getByText(`已导入 ${book.chapters} 章 · 还没开拆`, { exact: true })).toBeVisible() }
const readBody = () => page.locator('main [data-spot^="t|"]')
const current = async () => readBody().getAttribute('data-spot')
const send = async (id, text) => {
  await page.getByRole('textbox', { name: '给编辑部发消息', exact: true }).fill(text)
  const response = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/books/${id}/notes`))
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const result = await response
  assert.ok(result.ok())
  const note = await result.json()
  await expect.poll(async () => (await api(`/books/${id}/meeting?limit=100`)).some(row => row.payload?.reply_to?.includes(note.id) && !['thinking', 'streaming'].includes(row.payload?.state) && row.content)).toBe(true)
  return note
}
const measured = async (run, ready) => {
  const start = await page.evaluate(() => performance.now())
  await run()
  await ready()
  await page.evaluate(() => new Promise(requestAnimationFrame))
  return Math.round((await page.evaluate(() => performance.now())) - start)
}

try {
  const phase = process.argv[2] ?? 'import'
  if (phase === 'shots') {
    await home()
    await page.getByRole('region', { name: '拆的书', exact: true }).scrollIntoViewIfNeeded()
    await shot('书房-拆的书')
    for (const book of evidence.books) {
      await shelfOpen(book)
      if (book.title === '逆天邪神') {
        await tab('简介').click()
        await expect(page.locator('main').getByText('原书简介', { exact: true })).toBeVisible()
        await shot(`${book.title}-简介`)
      }
      await tab('大纲').click()
      await page.getByRole('button', { name: '还没归单元', exact: true }).first().click()
      await expect(page.locator('main').getByText('这些章还没拆，拆的时候会归进单元。', { exact: true })).toBeVisible()
      await shot(`${book.title}-虚单元`)
      await tab('正文').click()
      if (book.title === '逆天邪神') await shot(`${book.title}-正文首页`)
      const word = book.title === '逆天邪神' ? '天毒珠' : '许悦'
      await page.getByPlaceholder('找章节、搜原文……').fill(word)
      await page.getByPlaceholder('找章节、搜原文……').press('Enter')
      await page.getByRole('region', { name: '原文搜索结果' }).getByRole('button').first().click()
      await expect(page.locator('main mark[data-text-match]').first()).toHaveText(word)
      await expect(page.locator('main mark[data-text-match]').first()).toBeInViewport()
      await shot(`${book.title}-搜原文`)
    }
    evidence.checks.visible_evidence = true
  }
  if (phase === 'import') {
    const profiles = await api('/llm/profiles')
    assert.ok(profiles.length && profiles.every(profile => profile.provider === 'demo' && !profile.has_key))
    for (const [name, title, count] of [['逆天邪神(1-500章).txt', '逆天邪神', 498], ['都重生了谁考公务员啊.txt', '都重生了谁考公务员啊', 669]]) {
      if (evidence.books.some(book => book.title === title && book.detail?.teardown?.stage === 'imported')) continue
      await home()
      await page.getByRole('button', { name: '拆一本书', exact: true }).first().click()
      await page.getByLabel('选择 TXT 文件').setInputFiles(`C:\\Users\\cxc\\Desktop\\${name}`)
      await expect(page.getByLabel('书名', { exact: true })).toHaveValue(title)
      const id = new URL(page.url()).pathname.split('/')[2]
      const preview = await api(`/teardown/${id}/preview`)
      const item = { id, title, file: name, preview, chapters: count }
      evidence.books.push(item)
      await save()
      await shot(`${title}-确认`, true)
      await page.getByLabel('作者', { exact: true }).fill(`${preview.author}验收手改`)
      await page.getByRole('button', { name: 'UTF-8', exact: true }).click()
      await expect(page.getByRole('button', { name: 'UTF-8', exact: true })).toBeEnabled()
      await expect(page.getByRole('button', { name: 'UTF-8', exact: true })).toHaveAttribute('aria-pressed', 'true')
      await expect(page.getByLabel('作者', { exact: true })).toHaveValue(`${preview.author}验收手改`)
      await page.getByRole('button', { name: '自动', exact: true }).click()
      await expect(page.getByRole('button', { name: '自动', exact: true })).toHaveAttribute('aria-pressed', 'true')
      await page.getByLabel('作者', { exact: true }).fill(preview.author)
      if (preview.excluded.length) {
        await page.getByRole('checkbox').first().check()
        await expect(page.getByTestId('teardown-split-summary')).toContainText(`${count} 章`)
        item.included_order = preview.excluded[0].order
      } else item.include_note = '原文件没有不像正文条目，不制造勾回项；在都重生执行勾回'
      await page.getByRole('button', { name: '导入', exact: true }).click()
      await expect(page.locator('main').getByText(`已导入 ${count} 章 · 还没开拆`, { exact: true })).toBeVisible()
      item.detail = await api(`/books/${id}`)
      assert.equal(item.detail.source, 'teardown')
      assert.equal(item.detail.teardown.chapters, count)
      assert.ok(item.detail.teardown.imported_at)
      await save()
    }
    await home()
    await expect(page.getByRole('region', { name: '拆的书', exact: true })).toBeVisible()
    await shot('书房-拆的书')
    evidence.checks.import = true
  }
  if (phase === 'read') {
    for (const book of evidence.books) {
      await shelfOpen(book)
      for (const label of ['开写', '停写', '本书设置', '改这一句']) await expect(page.getByRole('button', { name: label, exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: /^待处理/ })).toHaveCount(0)
      await expect(page.getByRole('button', { name: /^存档/ })).toBeVisible()
      await expect(page.getByRole('button', { name: '系统设置', exact: true })).toBeVisible()
      await tab('简介').click()
      await expect(page.locator('main').getByText('原书简介', { exact: true })).toBeVisible()
      await expect(page.locator('main').getByText('还没开拆。', { exact: true })).toBeVisible()
      await expect(page.locator('main').getByText(/\d{4}-\d{2}-\d{2} 导入/)).toBeVisible()
      if (book.preview.volumes.length) await expect(page.locator('main').getByText(new RegExp(`原书分了 ${book.preview.volumes.length} 卷`))).toBeVisible()
      else await expect(page.locator('main').getByText(/原书没有分卷/)).toBeVisible()
      if (book.title === '逆天邪神') await shot(`${book.title}-简介`)
      await tab('设定').click()
      await expect(page.locator('main').getByText('还没拆出设定。', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '编辑部帮写', exact: true })).toHaveCount(0)
      await tab('大纲').click()
      await page.getByRole('button', { name: '还没归单元', exact: true }).first().click()
      await expect(page.locator('main').getByText('这些章还没拆，拆的时候会归进单元。', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: /新建一|在下面加|编辑部帮拆|编辑部帮写/ })).toHaveCount(0)
      await shot(`${book.title}-虚单元`)
      await page.locator('main').getByRole('button', { name: /^第1章/ }).first().click()
      await expect(page.locator('main').getByText('还没拆出章纲', { exact: true }).first()).toBeVisible()
      await page.locator('main').getByRole('button', { name: '去读', exact: true }).click()
      await expect(readBody()).not.toBeEmpty()
      await expect(readBody()).toHaveAttribute('contenteditable', 'false')
      assert.equal(await current(), 't|c1')
      await expect(page.locator('main').getByRole('button', { name: '上一章', exact: true })).toHaveCount(0)
      await page.keyboard.press('ArrowRight')
      await expect(readBody()).toHaveAttribute('data-spot', 't|c2')
      await page.keyboard.press('ArrowRight')
      await expect(readBody()).toHaveAttribute('data-spot', 't|c3')
      await page.keyboard.press('ArrowLeft')
      await expect(readBody()).toHaveAttribute('data-spot', 't|c2')
      const input = page.getByPlaceholder('找章节、搜原文……')
      await input.focus()
      await page.keyboard.press('ArrowRight')
      assert.equal(await current(), 't|c2')
      await input.blur()
      const saved = await page.evaluate(id => JSON.parse(localStorage.getItem(`zhibi:teardown-reading:${id}`)), book.id)
      assert.equal(saved.chapter, 2)
      await shelfOpen(book)
      await expect(page.locator('main').getByRole('button', { name: /^接着读第 2 章/ })).toBeVisible()
      if (book.title === '逆天邪神') await shot(`${book.title}-正文首页`)
      await page.locator('main').getByRole('button', { name: /^接着读第 2 章/ }).click()
      await expect(readBody()).toHaveAttribute('data-spot', 't|c2')
      // 通过独立提示词页返回仍恢复本次会话位置，不被“打开书先到首页”覆盖。
      await page.goto(`${base}/prompts?returnTo=${encodeURIComponent(`/desk/${book.id}`)}`)
      await page.getByRole('link', { name: '返回当前书', exact: true }).click()
      await expect(readBody()).toHaveAttribute('data-spot', 't|c2')
      const word = book.title === '逆天邪神' ? '天毒珠' : '许悦'
      const searchInput = page.getByPlaceholder('找章节、搜原文……')
      await searchInput.fill(word)
      await searchInput.press('Enter')
      const search = page.getByRole('region', { name: '原文搜索结果' })
      await expect(search.getByRole('button').first()).toBeVisible()
      const first = await search.getByRole('button').first().innerText()
      await search.getByRole('button').first().click()
      await expect(page.locator('main mark[data-text-match]').first()).toHaveText(word)
      await expect(page.locator('main mark[data-text-match]').first()).toBeInViewport()
      await shot(`${book.title}-搜原文`)
      book.search = { word, first, result: await api(`/books/${book.id}/search?q=${encodeURIComponent(word)}`) }
      // 同一章同一个结果重复点击，也要重新滚回首次命中。
      await page.locator('main').evaluate(el => { el.scrollTop = el.scrollHeight })
      await search.getByRole('button').first().click()
      await expect(page.locator('main mark[data-text-match]').first()).toBeInViewport()
      // 选原文只留下提问，不暴露原型重写菜单。
      await readBody().evaluate(el => {
        const text = el.querySelector('[data-text-match]')?.firstChild ?? el.querySelector('p')?.firstChild
        if (!text) throw new Error('没有原文段落')
        const range = document.createRange(); range.setStart(text, 0); range.setEnd(text, Math.min(12, text.textContent.length))
        const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
        document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
      })
      await expect(page.getByRole('button', { name: '问问主编', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '改这一句', exact: true })).toHaveCount(0)
      await page.getByRole('button', { name: '问问主编', exact: true }).click()
      await expect(page.getByRole('textbox', { name: '给编辑部发消息', exact: true })).toBeVisible()
      await expect(page.getByLabel('引用原文', { exact: true })).toBeVisible()
      const beforeInputArrow = await current()
      await page.getByRole('textbox', { name: '给编辑部发消息', exact: true }).press('ArrowRight')
      assert.equal(await current(), beforeInputArrow)
      const quoted = await send(book.id, '请解释我引用的这句话。')
      assert.ok(quoted.payload.quote.text)
      assert.equal(quoted.payload.chat_role, 'chief')
      await expect(page.getByLabel('引用原文', { exact: true })).toHaveCount(0)
      book.quote_note = quoted
      // 切回群聊，问一句；浏览器只调用演示模型。
      // 新版编辑部为统一群聊，@ 点名替代旧版单独的私聊页签。
      const clearQuote = page.getByRole('button', { name: '取消引用', exact: true })
      if (await clearQuote.count()) await clearQuote.click()
      const clearMention = page.getByRole('button', { name: '不点名了', exact: true })
      if (await clearMention.count()) await clearMention.click()
      const before = await api(`/books/${book.id}/outline-tree`)
      const message = `「${word}」第一次出现在哪一章？`
      await send(book.id, message)
      assert.deepEqual(await api(`/books/${book.id}/outline-tree`), before)
      book.chat = (await api(`/books/${book.id}/meeting?limit=100`)).filter(row => ['note', 'speech'].includes(row.kind))
      book.calls = (await api(`/llm-calls?book_id=${book.id}&limit=20`)).items
      assert.ok(book.calls.length && book.calls.every(call => String(call.method).startsWith('demo') || call.model === 'demo'))
      await save()
    }
    evidence.checks.read = true
  }
  if (phase === 'errors') {
    await home()
    await page.getByRole('button', { name: '拆一本书', exact: true }).first().click()
    const picker = page.getByLabel('选择 TXT 文件')
    await picker.setInputFiles({ name: '不是TXT.pdf', mimeType: 'application/pdf', buffer: Buffer.from('abc') })
    await expect(page.getByRole('alert').getByText('只能导入 TXT 文件', { exact: true })).toBeVisible()
    await picker.setInputFiles({ name: '空文件.txt', mimeType: 'text/plain', buffer: Buffer.alloc(0) })
    await expect(page.getByRole('alert').getByText('文件里没有文字', { exact: true })).toBeVisible()
    let content = Buffer.from('第一章 初见\n这是测试正文，只用来核对编码错误和取消导入。\n')
    if (content.length % 2 === 0) content = Buffer.concat([content, Buffer.from('A')])
    await picker.setInputFiles({ name: '界面边界测试.txt', mimeType: 'text/plain', buffer: content })
    await expect(page.getByLabel('书名', { exact: true })).toBeVisible()
    const id = new URL(page.url()).pathname.split('/')[2]
    const old = await page.getByTestId('teardown-split-summary').innerText()
    await page.getByRole('button', { name: 'UTF-16', exact: true }).click()
    await expect(page.getByText('用 UTF-16 读不出来，换一种试试', { exact: true })).toBeVisible()
    assert.equal(await page.getByTestId('teardown-split-summary').innerText(), old)
    await page.getByRole('button', { name: '自动', exact: true }).click()
    await expect(page.getByText('用 UTF-16 读不出来，换一种试试', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '不导入了', exact: true }).click()
    assert.equal((await api(`/books/${id}`)).teardown.stage, 'confirming')
    await page.getByRole('button', { name: '确定不导入？再点一次', exact: true }).click()
    await expect(page).toHaveURL(base + '/')
    assert.equal((await page.request.get(`${base}/api/books/${id}`)).status(), 404)
    evidence.checks.upload_errors_encoding_failure_cancel = true
    // 浏览器禁止持久化时实际打开正文，所有读写均应安全降级。
    await context.addInitScript(() => {
      Storage.prototype.getItem = () => { throw new DOMException('禁用存储', 'SecurityError') }
      Storage.prototype.setItem = () => { throw new DOMException('禁用存储', 'SecurityError') }
    })
    const book = evidence.books[0]
    await shelfOpen(book)
    await page.locator('main').getByRole('button', { name: '从第 1 章读起', exact: true }).click()
    await expect(readBody()).not.toBeEmpty()
    await page.keyboard.press('ArrowRight')
    await expect(readBody()).toHaveAttribute('data-spot', 't|c2')
    evidence.checks.blocked_browser_storage = true
  }
  if (phase === 'perf') {
    const book = evidence.books.find(book => book.title === '都重生了谁考公务员啊')
    assert.ok(book)
    await home()
    const timings = {}
    timings.open = await measured(() => page.locator(`a[href="/desk/${book.id}"]`).last().click(), () => expect(page.locator('main').getByText(`已导入 ${book.chapters} 章 · 还没开拆`, { exact: true })).toBeVisible())
    timings.outline = await measured(() => tab('大纲').click(), () => expect(page.getByRole('button', { name: '还没归单元', exact: true }).first()).toBeVisible())
    const unit = page.getByRole('button', { name: '还没归单元', exact: true }).first()
    const row = unit.locator('..')
    const collapse = row.getByRole('button', { name: '收起', exact: true })
    if (await collapse.count()) await collapse.click()
    timings.expand = await measured(() => row.getByRole('button', { name: '展开', exact: true }).click(), () => expect(page.getByRole('button', { name: /^第669章/ }).first()).toBeAttached())
    timings.manuscript = await measured(() => tab('正文').click(), () => expect(page.locator('main').getByText(`已导入 ${book.chapters} 章 · 还没开拆`, { exact: true })).toBeVisible())
    await page.locator('main').getByRole('button', { name: /从第 1 章读起|接着读第/ }).click()
    await expect(readBody()).not.toBeEmpty()
    const old = await current()
    timings.turn = await measured(() => page.keyboard.press('ArrowRight'), () => expect.poll(current).not.toBe(old))
    timings.search = await measured(() => page.getByPlaceholder('找章节、搜原文……').fill('许悦'), () => expect(page.getByRole('region', { name: '原文搜索结果' }).getByRole('button').first()).toBeVisible())
    evidence.performance = { chapters: book.chapters, timings_ms: timings, method: 'performance.now()，动作前到目标DOM可见/附着并经过下一帧；搜索含400ms防抖；本机单次暖进程，不含模型' }
    evidence.checks.performance = true
  }
  assert.deepEqual(evidence.errors, [])
  console.log(JSON.stringify({ phase, checks: evidence.checks, books: evidence.books.map(book => ({ id: book.id, title: book.title, chapters: book.chapters })), performance: evidence.performance }, null, 2))
} finally { await save(); await browser.close() }
