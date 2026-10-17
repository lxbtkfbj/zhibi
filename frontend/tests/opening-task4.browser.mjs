/** 第三包任务4真实浏览器清单：仅明确指定的独立环境，不拦截业务响应。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = process.env.TEST_BASE_URL
assert.equal(base, 'http://127.0.0.1:4354', '只允许本任务独立网页')
const output = path.resolve('../docs/第三包验收')
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM })
const page = await browser.newPage({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce' })
const expect = baseExpect.configure({ timeout: 90_000 })
const errors = [], screenshots = [], requests = []
const evidence = { screenshots, requests, errors }
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => { if (['POST', 'PATCH', 'DELETE'].includes(request.method())) requests.push({ method: request.method(), url: request.url(), body: request.postData() }) })
const api = async route => { const response = await page.request.get(`${base}/api${route}`); assert.equal(response.status(), 200, route); return response.json() }
const shot = async name => { await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(450); const file = `任务4-${name}.png`; await page.screenshot({ path: path.join(output, file) }); screenshots.push(file) }
const selectSentence = async field => {
  const text = field.locator('[data-selectable-text]')
  await text.scrollIntoViewIfNeeded()
  await text.evaluate(element => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode)
    const first = nodes.find(node => node.textContent.length)
    const count = Math.min(first.textContent.indexOf('。') + 1 || first.textContent.length, first.textContent.length)
    const range = document.createRange(); range.setStart(first, 0); range.setEnd(first, count)
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  await field.getByRole('button', { name: '改这一句', exact: true }).click()
  await field.getByRole('menu').getByRole('button', { name: '给我几个写法', exact: true }).click()
  await expect(field.getByRole('region', { name: '候选写法' }).getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
}
const navigate = async (bookId, suffix) => {
  await page.goto(`${base}/books/${bookId}/${suffix}`)
  const manuscript = page.getByRole('tab', { name: '稿件', exact: true })
  if (await manuscript.isVisible()) await manuscript.click()
}

try {
  assert.ok((await api('/llm/profiles')).every(profile => profile.provider === 'demo'))
  await page.goto(base)
  await page.locator('textarea').first().fill('第三包任务4独立演示：楚风重生，轮回镜和前世之死同出一源。测试自建类别；对标逆世帝尊。')
  await page.getByRole('button', { name: '一步一步看', exact: true }).click()
  await page.getByRole('button', { name: '交给编辑部', exact: true }).click()
  await page.waitForURL(/\/books\//)
  const bookId = new URL(page.url()).pathname.split('/')[2]; evidence.book_id = bookId
  await fs.writeFile('../data/third-package-task4/current-book.json', JSON.stringify({ book_id: bookId }))
  const selection = page.getByRole('region', { name: '选择短版定调' })
  await expect(selection.getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
  await shot('00-三个短版完整卡片')
  await selection.getByRole('button', { name: '再来三个', exact: true }).click()
  await expect(selection).toContainText('先写一句你想怎么改')
  await selection.getByRole('radio', { name: /300/ }).check()
  const firstCard = selection.getByRole('article').first()
  await firstCard.getByRole('button', { name: /^《/ }).nth(1).click()
  evidence.selected_title = await firstCard.getByRole('textbox').inputValue()
  await shot('01-挑短版书名与300万')
  await firstCard.getByRole('button', { name: '用这个', exact: true }).click()
  await expect(page.getByTestId('story-page')).toBeVisible()
  await expect(page.getByRole('button', { name: '确认，去建设定', exact: true })).toBeVisible()
  const story = page.locator('[data-rewrite-path="story"]')
  await selectSentence(story)
  await shot('02-定调选句三种写法')
  await story.getByRole('button', { name: '用这个', exact: true }).first().click()
  await expect(story.getByTestId('rewrite-highlight')).toBeVisible()
  await shot('03-定调选用标黄')
  // 直接修改响应中的after是完整字段；非零起点也只标黄真正换入的片段。
  await story.locator('[data-selectable-text]').evaluate(element => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) if (walker.currentNode.textContent.length >= 8) {
      const range = document.createRange(); range.setStart(walker.currentNode, 4); range.setEnd(walker.currentNode, 8)
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
      document.dispatchEvent(new Event('selectionchange')); break
    }
  })
  await story.getByRole('button', { name: '改这一句', exact: true }).click()
  await story.getByRole('menu').getByRole('button', { name: '写细一点', exact: true }).click()
  await expect(story.getByTestId('rewrite-highlight')).toBeVisible()
  await shot('03a-非零起点直接改写标黄')
  const concept = (await api(`/books/${bookId}`)).concept
  assert.equal(concept.target_length, 300); assert.equal(concept.title, evidence.selected_title)
  await page.getByRole('button', { name: '确认，去建设定', exact: true }).click()
  const library = page.getByTestId('library-page')
  await expect(page.getByRole('button', { name: '设定先这样，去出大纲', exact: true })).toBeVisible()
  await expect(library.getByLabel('设定库总结')).toContainText('主编建了')
  await expect(library.getByRole('navigation', { name: '设定类别' })).toContainText('重点')
  await shot('04-设定库重点总结建议')
  await library.getByRole('navigation', { name: '设定类别' }).getByRole('button', { name: /^等级体系/ }).click()
  let snapshot = await api(`/books/${bookId}/library`)
  const ladder = snapshot.entries.find(item => item.category === '等级体系' && item.levels.some(level => level.name.includes('灵海')))
  assert.ok(ladder, '演示等级含灵海，支持确定性的改名连带演示')
  await library.getByTestId(`library-item-${ladder.id}`).click()
  const levelIndex = ladder.levels.findIndex(level => level.name.includes('灵海'))
  const level = library.locator(`[data-rewrite-path="levels.${levelIndex}.name"]`)
  await level.getByRole('button', { name: '改这一项', exact: true }).click()
  await level.getByRole('button', { name: '给我几个写法', exact: true }).click()
  await expect(level.getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
  await shot('05-等级某一级候选')
  await level.getByRole('button', { name: '用这个', exact: true }).nth(1).click()
  await expect(level.getByTestId('rewrite-highlight')).toBeVisible()
  await shot('06-等级改名标黄')
  await expect.poll(async () => (await api(`/books/${bookId}/suggestions`)).filter(item => item.kind === 'cascade' && item.status === 'pending').length).toBeGreaterThan(0)
  await library.getByText('展开建议', { exact: true }).click()
  await shot('07-连带建议')
  await library.getByRole('button', { name: '全部接受', exact: true }).click()
  await expect.poll(async () => (await api(`/books/${bookId}/suggestions`)).filter(item => item.kind === 'cascade' && item.status === 'pending').length).toBe(0)
  await shot('08-全部接受结果')
  const detail = library.getByRole('article', { name: `${ladder.name}详情` })
  await detail.getByRole('button', { name: '锁住', exact: true }).click()
  await expect(detail.getByRole('button', { name: '已锁住 · 解锁', exact: true })).toBeVisible()
  await level.getByRole('button', { name: '改这一项', exact: true }).click()
  await expect(level).toContainText('已锁：AI 不能改这一处，先解锁')
  await shot('09-锁住不能AI改')
  await detail.getByRole('button', { name: '已锁住 · 解锁', exact: true }).click()
  await detail.getByRole('button', { name: '历史', exact: true }).click()
  const history = page.getByRole('dialog', { name: '版本历史' })
  await expect(history.locator('details')).not.toHaveCount(0)
  await history.locator('details').last().locator('summary').click()
  page.once('dialog', dialog => dialog.accept())
  await history.locator('details').last().getByRole('button', { name: '退回到这一版' }).click()
  await expect.poll(async () => (await api(`/books/${bookId}/library`)).entries.find(item => item.id === ladder.id).levels[levelIndex].name).toBe(ladder.levels[levelIndex].name)
  await shot('10-历史退回')
  await history.getByRole('button', { name: '关闭', exact: true }).click()
  await library.getByRole('button', { name: '自建类别', exact: true }).click()
  const categoryModal = page.getByRole('dialog', { name: '自建类别', exact: true })
  await categoryModal.getByRole('textbox', { name: '类别名称', exact: true }).fill('契约')
  await categoryModal.getByRole('combobox', { name: '类别样式' }).selectOption('card')
  for (const [index, name] of ['约定双方', '交换条件', '违约后果'].entries()) { await categoryModal.getByRole('button', { name: '＋加一个字段' }).click(); await categoryModal.getByRole('textbox', { name: `字段 ${index + 1}`, exact: true }).fill(name) }
  await categoryModal.getByRole('textbox', { name: '这一类该写清什么' }).fill('说清约定双方、交换条件和违约后果。')
  await shot('11-自建三字段卡片类别')
  await categoryModal.getByRole('button', { name: '保存类别' }).click()
  await expect(categoryModal).not.toBeVisible()
  await library.getByRole('button', { name: '新增一条', exact: true }).click()
  const newModal = page.getByRole('dialog', { name: '新增一条' })
  await newModal.getByRole('textbox', { name: '条目名称' }).fill('青灯之约')
  await newModal.getByRole('button', { name: '建好这一条' }).click()
  await expect(library.getByRole('article', { name: '青灯之约详情' })).toBeVisible()
  await shot('12-自建类别新条目')
  await page.getByRole('button', { name: '设定先这样，去出大纲', exact: true }).click()
  const outline = page.getByTestId('outline-page')
  await expect(page.getByRole('button', { name: '确认，开写', exact: true })).toBeVisible()
  await expect(outline.getByRole('button', { name: /^收起第 1 篇/ })).toBeVisible()
  await expect(outline.getByRole('button', { name: /^收起第 1 卷/ })).toBeVisible()
  await shot('13-大纲默认展开篇卷')
  const tree = await api(`/books/${bookId}/outline-tree`)
  const unit = tree.arcs[0].volumes[0].units[0]
  await outline.getByTestId(`outline-node-unit-${unit.id}`).click()
  const summary = outline.locator('[data-rewrite-path="summary"]')
  await selectSentence(summary)
  await summary.getByRole('button', { name: '用这个', exact: true }).first().click()
  await expect(summary.getByTestId('rewrite-highlight')).toBeVisible()
  await shot('14-单元改一句标黄')
  await outline.getByRole('spinbutton', { name: '章数', exact: true }).fill(String(unit.chapter_count + 1))
  await outline.getByRole('button', { name: '改章数', exact: true }).click()
  await expect.poll(async () => (await api(`/books/${bookId}/outline-tree`)).arcs[0].volumes[0].units[0].chapter_count).toBe(unit.chapter_count + 1)
  await shot('15-改章数')
  await outline.getByTestId('outline-detail').getByText('更多', { exact: true }).click()
  await outline.getByRole('button', { name: '在后面加一个单元' }).click()
  const addUnit = page.getByRole('dialog', { name: '加一个单元', exact: true })
  await addUnit.getByRole('textbox', { name: '名称', exact: true }).fill('独立验收新增单元')
  await addUnit.getByRole('textbox', { name: '一段话', exact: true }).fill('主角守住青灯，查清约定的代价。')
  await addUnit.getByRole('button', { name: '保存', exact: true }).click()
  await expect(outline.getByTestId('outline-detail')).toContainText('独立验收新增单元')
  await shot('16-新增单元')
  await outline.getByTestId('outline-detail').getByText('更多', { exact: true }).click()
  await outline.getByRole('button', { name: '删掉这个单元', exact: true }).click()
  await page.getByRole('dialog', { name: '删掉这个单元？' }).getByRole('button', { name: '确认删除' }).click()
  await expect(outline.getByRole('tree')).not.toContainText('独立验收新增单元')
  await shot('17-删除新增单元')
  await outline.getByRole('button', { name: '地图', exact: true }).click(); await shot('18-大纲地图')
  await outline.getByRole('button', { name: '线索', exact: true }).click(); await shot('19-大纲线索')
  await outline.getByRole('button', { name: '确认，开写', exact: true }).click()
  await expect.poll(async () => (await api(`/books/${bookId}`)).chapters_final, { timeout: 300_000 }).toBe(3)
  await navigate(bookId, 'chapter/3'); await expect(page).toHaveURL(new RegExp(`/books/${bookId}/chapter/3$`)); await expect(page.locator('#manuscript-pane')).toContainText('第 三 章'); await shot('20-前3章已定稿')
  await navigate(bookId, 'concept')
  await selectSentence(page.locator('[data-rewrite-path="story"]'))
  await page.locator('[data-rewrite-path="story"]').getByRole('button', { name: '用这个', exact: true }).first().click()
  await expect.poll(async () => (await api(`/books/${bookId}/suggestions`)).filter(item => item.kind === 'concept' && item.status === 'pending').length).toBeGreaterThan(0)
  await navigate(bookId, 'library'); await page.getByText('展开建议', { exact: true }).click(); await shot('21-开写后定调改了建议')
  for (const [old, next] of [['protagonist', 'library'], ['spine', 'outline'], ['world', 'library']]) { await navigate(bookId, old); await expect(page).toHaveURL(new RegExp(`/books/${bookId}/${next}\\?`)); await shot(`22-${old}旧路由跳转`) }
  const legacy = process.env.THIRD_PACKAGE_LEGACY_BOOK_ID
  if (legacy) {
    evidence.legacy_book_id = legacy
    await navigate(legacy, 'concept'); await expect(page.getByTestId('story-page')).toContainText('这本书开书时还没有一段话的定调'); await expect(page.getByRole('button', { name: '让主编按现有内容写一段' })).toBeVisible(); await shot('23-第二包旧书定调')
    await navigate(legacy, 'library'); await expect(page.getByTestId('library-page').getByRole('complementary', { name: '设定条目列表' })).not.toContainText('没有符合条件'); await shot('24-旧书迁移设定')
    await navigate(legacy, 'outline'); await expect(page.getByRole('tree')).toContainText('第 1 篇'); await shot('25-旧书篇树')
  }
  for (const dark of [false, true]) {
    await page.setViewportSize({ width: dark ? 1680 : 390, height: dark ? 1100 : 844 })
    await page.evaluate(dark => { const a = JSON.parse(localStorage.getItem('zhibi:appearance') ?? '{}'); localStorage.setItem('zhibi:appearance', JSON.stringify({ ...a, theme: dark ? 'ink' : 'paper' })) }, dark)
    for (const section of ['concept', 'library', 'outline']) { await navigate(bookId, section); await expect(page.getByTestId(section === 'concept' ? 'story-page' : `${section}-page`)).toBeVisible(); await shot(`${dark ? '27-暗色' : '26-390窄屏'}-${section}`); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${section}页面不能横向溢出`) }
  }
  assert.deepEqual(errors, [])
  evidence.completed = true
} catch (error) {
  evidence.failure = String(error.stack ?? error)
  await shot('调试-失败现场')
  throw error
} finally {
  await fs.writeFile(path.join(output, '任务4-浏览器结果.json'), JSON.stringify(evidence, null, 2))
  await browser.close()
}
