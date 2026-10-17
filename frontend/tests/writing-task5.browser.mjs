/** 第三包任务5：只操作独立演示网页；API只读核对，不拦截业务响应。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = process.env.TEST_BASE_URL
assert.equal(base, 'http://127.0.0.1:4355', '只允许任务5独立环境')
const output = path.resolve('../docs/第三包验收')
const data = path.resolve('../data/third-package-task5')
const phase = process.argv[2] || 'setup'
const statePath = path.join(data, 'browser-state.json')
const evidence = await fs.readFile(statePath, 'utf8').then(JSON.parse).catch(() => ({ screenshots: [], requests: [], errors: [] }))
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM })
const page = await browser.newPage({ viewport: { width: 1720, height: 1180 }, reducedMotion: 'reduce' })
const expect = baseExpect.configure({ timeout: 120_000 })
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => {
  if (['POST', 'PATCH', 'DELETE'].includes(request.method())) evidence.requests.push({ method: request.method(), url: request.url(), body: request.postData() })
})
const api = async route => {
  const response = await page.request.get(`${base}/api${route}`)
  assert.equal(response.status(), 200, route)
  return response.json()
}
const shot = async name => {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(450)
  const file = `任务5-${name}.png`
  await page.screenshot({ path: path.join(output, file) })
  if (!evidence.screenshots.includes(file)) evidence.screenshots.push(file)
  console.log(file)
}
// 仅滚动真实 DOM 到待核对的提示词，不改正文、样式或应用状态。
const scrollText = async (locator, text) => locator.locator('pre').evaluate((element, needle) => {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) {
    const index = walker.currentNode.textContent.indexOf(needle)
    if (index < 0) continue
    const range = document.createRange()
    range.setStart(walker.currentNode, index)
    range.setEnd(walker.currentNode, index + needle.length)
    let parent = element.parentElement
    while (parent && !(/auto|scroll/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight)) parent = parent.parentElement
    if (parent) parent.scrollTop += range.getBoundingClientRect().top - parent.getBoundingClientRect().top - 120
    return
  }
  throw new Error(`页面文本里没有 ${needle}`)
}, text)
const navigate = async (suffix, book = evidence.book_id) => {
  await page.goto(`${base}/books/${book}/${suffix}`)
  const manuscript = page.getByRole('tab', { name: '稿件', exact: true })
  if (await manuscript.isVisible()) await manuscript.click()
}
const selectNode = async key => navigate(`outline?node=${key}`)
const tree = () => api(`/books/${evidence.book_id}/outline-tree`)
const book = () => api(`/books/${evidence.book_id}`)
const visibleSnapshot = outline => outline.arcs.flatMap(arc => arc.volumes.flatMap(volume => [
  { kind: 'volume', id: volume.id, title: volume.title, summary: volume.summary, count: volume.chapter_count, locked: volume.locked },
  ...volume.units.map(unit => ({ kind: 'unit', id: unit.id, title: unit.title, summary: unit.summary, count: unit.chapter_count, locked: unit.locked })),
]))

try {
  assert.ok((await api('/llm/profiles')).every(profile => profile.provider === 'demo'))
  if (phase === 'setup') {
    await page.goto(base)
    await page.locator('textarea').first().fill('第三包任务5独立演示：楚风重生，以轮回镜追查前世之死。测试冲突。')
    await page.getByRole('button', { name: '一步一步看', exact: true }).click()
    await page.getByRole('button', { name: '交给编辑部', exact: true }).click()
    await page.waitForURL(/\/books\//)
    evidence.book_id = new URL(page.url()).pathname.split('/')[2]
    await fs.writeFile(statePath, JSON.stringify(evidence, null, 2))
    const pitches = page.getByRole('region', { name: '选择短版定调' })
    await expect(pitches.getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
    await shot('01-新书三个短版')
    await pitches.getByRole('button', { name: '用这个', exact: true }).first().click()
    await expect(page.getByRole('button', { name: '确认，去建设定', exact: true })).toBeVisible()
    await shot('02-定调与底牌')
    await page.getByRole('button', { name: '确认，去建设定', exact: true }).click()
    await expect(page.getByRole('button', { name: '设定先这样，去出大纲', exact: true })).toBeVisible()
    const library = await api(`/books/${evidence.book_id}/library`)
    const convention = library.entries.find(item => item.name === '世界概况')
    evidence.secret = library.entries.find(item => item.tags.includes('底牌')).content
    evidence.convention = convention.id
    await page.getByRole('navigation', { name: '设定类别' }).getByRole('button', { name: /^世界与地图/ }).click()
    await page.getByTestId(`library-item-${convention.id}`).click()
    await page.getByRole('combobox', { name: '条目状态' }).selectOption('one')
    await expect.poll(async () => (await api(`/books/${evidence.book_id}/library`)).entries.find(item => item.id === convention.id).status).toBe('one')
    await shot('03-作者设为一句话惯例')
    await page.getByRole('button', { name: '设定先这样，去出大纲', exact: true }).click()
    await expect(page.getByRole('button', { name: '确认，开写', exact: true })).toBeVisible()
    let outline = await tree()
    const volumes = outline.arcs.flatMap(arc => arc.volumes)
    evidence.volume1 = volumes[0].id
    evidence.volume2 = volumes[1].id
    evidence.units = volumes[0].units.map(unit => unit.id)
    // 通过真实作者界面压缩演示篇幅，随后以这一版为不变性基线。
    for (const id of evidence.units) {
      await selectNode(`unit-${id}`)
      await page.getByRole('spinbutton', { name: '章数', exact: true }).fill('3')
      await page.getByRole('button', { name: '改章数', exact: true }).click()
      await expect.poll(async () => (await tree()).arcs.flatMap(arc => arc.volumes).flatMap(volume => volume.units).find(unit => unit.id === id).chapter_count).toBe(3)
    }
    await selectNode('volume-2')
    await page.getByRole('spinbutton', { name: '章数', exact: true }).fill('6')
    await page.getByRole('button', { name: '改章数', exact: true }).click()
    await selectNode(`unit-${evidence.units[0]}`)
    await page.getByTestId('outline-detail').getByRole('button', { name: '锁住', exact: true }).click()
    await selectNode('volume-1')
    await page.getByTestId('outline-detail').getByRole('button', { name: '锁住', exact: true }).click()
    await shot('04-开写前作者大纲基线')
    await navigate('settings')
    await page.getByRole('button', { name: '省时', exact: true }).click()
    await page.getByRole('switch', { name: '新书前 3 章先给我试读', exact: true }).uncheck()
    await page.getByRole('spinbutton', { name: '每章字数', exact: true }).fill('600')
    await page.getByRole('heading', { name: '本书设置', exact: true }).click()
    await expect.poll(async () => (await api(`/books/${evidence.book_id}/settings`)).settings.chapter_words).toBe(600)
    await shot('05-写作设置默认章纲不暂停')
    await selectNode('volume-1')
    outline = await tree()
    evidence.before = visibleSnapshot(outline)
    evidence.first_chapters = await api(`/books/${evidence.book_id}/chapters?volume=1`)
    await shot('06-三步开书完成等待开写')
  }
  if (phase === 'first-write') {
    await selectNode('volume-1')
    if (!(await book()).chapters_final) await page.getByRole('button', { name: '确认，开写', exact: true }).click()
    await expect.poll(async () => {
      const value = await book()
      if (value.active_job?.status === 'failed') throw new Error(value.active_job.error)
      return value.chapters_final
    }).toBe(3)
    await expect.poll(async () => (await book()).active_job?.status || 'idle').not.toMatch(/running|queued/)
    const after = await tree()
    assert.deepEqual(visibleSnapshot(after), evidence.before, '补齐不改作者见过的名称/一段话/章数/锁')
    const chapters = await api(`/books/${evidence.book_id}/chapters?volume=1`)
    assert.deepEqual(chapters.slice(0, 3).map(item => ({ id: item.id, outline: item.outline })), evidence.first_chapters.slice(0, 3).map(item => ({ id: item.id, outline: item.outline })))
    const messages = await api(`/books/${evidence.book_id}/meeting`)
    const fillArc = messages.findIndex(item => item.content?.includes('开写前，我把第 1 篇'))
    const fillVolume = messages.findIndex(item => item.content?.includes('开写前，我把第 1 卷'))
    const write = messages.findIndex(item => /写手正在写第\s*1\s*章/.test(item.content || ''))
    evidence.fill_messages = messages.filter(item => item.content?.includes('开写前，我把'))
    assert.ok(fillArc >= 0 && fillVolume > fillArc)
    assert.ok(write > fillVolume)
    evidence.immutable_verified = true
    await navigate('')
    await shot('07-补齐后前三章定稿')
    await selectNode(`unit-${evidence.units[1]}`)
    await page.getByTestId('outline-writing-details').locator('summary').click()
    await expect(page.getByTestId('outline-writing-details')).toContainText('关键事件')
    await shot('08-单元一段话不变细节已补')
    await navigate('outline?view=threads')
    await expect.poll(async () => (await api(`/books/${evidence.book_id}/threads`)).length).toBeGreaterThan(0)
    await shot('09-第一篇线索')
    await navigate('foreshadowing')
    const bible = await api(`/books/${evidence.book_id}/bible`)
    assert.ok(bible.foreshadowings.some(item => item.kind === '期待' && item.span === '长'))
    assert.ok(bible.foreshadowings.some(item => item.kind === '伏笔'))
    await shot('10-伏笔与长线期待')
    await navigate('secrets')
    assert.ok((await api(`/books/${evidence.book_id}/secrets`)).length >= 2)
    await shot('11-第一篇信息差')
    const library = await api(`/books/${evidence.book_id}/library`)
    const linked = library.entries.find(item => item.category === '往事与秘密' && item.secret_id)
    assert.ok(linked)
    await navigate(`library?cat=${encodeURIComponent('往事与秘密')}&id=${linked.id}`)
    await page.getByTestId(`library-item-${linked.id}`).click()
    await expect(page.getByTestId('library-page')).toContainText('谁知道')
    await shot('12-往事关联谁知道')
    const recorded = library.entries.find(item => item.source === 'writing')
    assert.ok(recorded)
    await navigate(`library?cat=${encodeURIComponent(recorded.category)}&id=${recorded.id}`)
    await page.getByTestId(`library-item-${recorded.id}`).click()
    await expect(page.getByTestId('library-page')).toContainText('写作中记下的')
    await shot('13-每章记新设定')
    assert.ok((await api(`/books/${evidence.book_id}/suggestions`)).some(item => /^第 \d+ 章：/.test(item.title)))
    await page.getByText('展开建议', { exact: true }).click()
    await shot('14-正文冲突只挂建议')
    await selectNode(`unit-${evidence.units[2]}`)
    await expect(page.getByRole('button', { name: '展开这一个', exact: true })).toHaveCount(0)
    await shot('15-后面的单元不能跳着展开')
    await selectNode(`unit-${evidence.units[1]}`)
    await page.getByRole('button', { name: '展开这一个', exact: true }).click()
    await expect(page.getByTestId('unit-chapter-outlines')).toContainText('第 4 章')
    await shot('16-下一个单元提前展开章纲')
    const next = (await tree()).arcs.find(arc => !arc.planned && arc.node_id)
    await selectNode(`segment-${next.node_id}`)
    await expect(page.getByRole('button', { name: '现在就规划下一篇', exact: true })).toBeVisible()
    await shot('17-下一篇可提前规划')
    evidence.first_write_passed = true
  }
  if (phase === 'gates') {
    await navigate('settings')
    await page.getByRole('switch', { name: '每个单元的章纲都给我看', exact: true }).check()
    await expect.poll(async () => (await api(`/books/${evidence.book_id}/settings`)).settings.chapters_approval).toBe(true)
    await shot('18-打开单元章纲确认')
    await navigate('')
    await page.getByRole('button', { name: '一直写到完本', exact: true }).first().click()
    await page.getByRole('button', { name: '继续写', exact: true }).first().click()
    await expect.poll(async () => (await book()).active_job?.pending?.kind).toBe('chapters_review')
    const review = (await book()).active_job.pending
    assert.equal(review.unit_id, evidence.units[2], '主动展开的第二单元不停，第三单元才进入章纲确认')
    await expect(page).toHaveURL(new RegExp(`outline\\?node=unit-${review.unit_id}`))
    await expect(page.getByTestId('unit-chapter-outlines')).toContainText('第 7 章')
    await shot('19-自动跟随到单元章纲拍板')
    evidence.before_revision = (await api(`/books/${evidence.book_id}/chapters`)).filter(item => item.unit_id === review.unit_id)
    await page.getByTestId('outline-detail').getByRole('button', { name: '提意见', exact: true }).click()
    await page.getByRole('textbox', { name: '修改意见', exact: true }).fill('这一单元先安排主角发现账册，再去公开对质；不要改作者的一段话。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect.poll(async () => {
      const chapters = (await api(`/books/${evidence.book_id}/chapters`)).filter(item => item.unit_id === review.unit_id)
      return chapters.length === 3 && chapters[0].id !== evidence.before_revision[0].id
    }).toBe(true)
    await expect.poll(async () => (await book()).active_job?.pending?.kind).toBe('chapters_review')
    await expect(page.getByTestId('unit-chapter-outlines')).toBeVisible()
    await shot('20-章纲提意见重出后再拍板')
    // 只验这一轮开关；后续关闭以继续走到卷与篇边界，不会吞掉正在等待的确认。
    await navigate('settings')
    await page.getByRole('switch', { name: '每个单元的章纲都给我看', exact: true }).uncheck()
    await expect.poll(async () => (await api(`/books/${evidence.book_id}/settings`)).settings.chapters_approval).toBe(false)
    await navigate('')
    await expect(page).toHaveURL(new RegExp(`outline\\?node=unit-${review.unit_id}`))
    await page.getByTestId('outline-detail').getByRole('button', { name: '批准开写', exact: true }).click()
    await expect.poll(async () => (await book()).active_job?.pending?.kind).toBe('volume_review')
    assert.equal((await book()).active_job.pending.volume, 2)
    await expect(page).toHaveURL(/outline\?node=volume-2/)
    await expect(page.getByRole('region', { name: '待确认的单元' })).toBeVisible()
    await shot('21-第二卷卷纲在大纲页拍板')
    await page.getByTestId('outline-detail').getByRole('button', { name: '批准开写', exact: true }).click()
    await expect.poll(async () => (await book()).active_job?.pending?.kind).toBe('segment_review')
    await expect(page).toHaveURL(/outline\?node=pending/)
    const pending = (await book()).active_job.pending
    evidence.arc_pending = pending
    assert.equal(pending.flow, 3)
    assert.equal(pending.number, 2)
    assert.equal(pending.plan.title, '天风国篇')
    assert.equal((await api(`/books/${evidence.book_id}/library`)).entries.some(item => item.name === '青云宗'), false)
    await expect(page.getByTestId('pending-arc-review')).toContainText('天风国')
    await shot('22-下一篇自动打开待确认节点')
    await page.getByTestId('pending-arc-review').getByText('这一篇新建的设定', { exact: true }).scrollIntoViewIfNeeded()
    await shot('23-确认前设定新建与写全预览')
    await page.getByRole('checkbox', { name: '确认时把它锁住', exact: true }).check()
    await page.getByTestId('decision-bar').getByRole('button', { name: '确认这一篇', exact: true }).click()
    await expect.poll(async () => (await api(`/books/${evidence.book_id}/library`)).entries.some(item => item.name === '青云宗')).toBe(true)
    await expect.poll(async () => (await book()).active_job?.pending?.kind).toBe('volume_review')
    const library = await api(`/books/${evidence.book_id}/library`)
    const place = library.entries.find(item => item.name === '天风国')
    assert.equal(place.status, 'must')
    assert.ok(place.content)
    const newArc = (await tree()).arcs.find(arc => arc.planned && arc.title === '天风国篇')
    assert.ok(newArc.locked)
    evidence.new_arc = newArc
    await selectNode(`segment-${newArc.node_id}`)
    await shot('24-第二篇已保存终点已锁')
    await navigate(`library?cat=${encodeURIComponent('势力划分')}&id=${library.entries.find(item => item.name === '青云宗').id}`)
    await shot('25-确认后新建青云宗')
    await navigate(`library?cat=${encodeURIComponent('世界与地图')}&id=${place.id}`)
    await shot('26-天风国从以后再说写全')
    evidence.gates_passed = true
  }
  if (phase === 'legacy') {
    const old = JSON.parse(await fs.readFile(path.join(data, 'legacy.json'), 'utf8'))
    evidence.legacy_book_id = old.book_id
    await navigate('next-segment', old.book_id)
    await expect(page).toHaveURL(/outline\?node=pending/)
    await expect(page.getByTestId('legacy-arc-review')).toContainText('这一篇是按旧写法规划的，要按新写法重出一次')
    await expect(page.getByTestId('legacy-arc-review').getByRole('button')).toHaveCount(1)
    await shot('27-真实旧flow2确认只允许重出')
    await page.getByTestId('legacy-arc-review').getByRole('button', { name: '按新写法重出', exact: true }).click()
    await expect(page.getByTestId('pending-arc-review')).toBeVisible()
    await expect(page.getByTestId('pending-arc-review')).toContainText('主编推的底牌')
    await page.getByTestId('pending-arc-review').getByText('主编推的底牌', { exact: true }).scrollIntoViewIfNeeded()
    await shot('28-旧书下一篇推底牌')
    await page.getByTestId('pending-arc-review').getByRole('button', { name: '确认这一篇', exact: true }).click()
    await expect.poll(async () => (await api(`/books/${old.book_id}/library`)).entries.some(item => item.tags.includes('底牌'))).toBe(true)
    const secret = (await api(`/books/${old.book_id}/library`)).entries.find(item => item.tags.includes('底牌'))
    assert.ok(secret.locked)
    assert.equal(secret.status, 'must')
    await navigate(`library?cat=${encodeURIComponent('往事与秘密')}&id=${secret.id}`, old.book_id)
    await expect(page.getByTestId('library-page')).toContainText('已锁住')
    await shot('29-旧书确认后底牌入库并锁住')
    await navigate('', old.book_id)
    await page.getByRole('button', { name: '写 1 章', exact: true }).first().click()
    await page.getByRole('button', { name: '继续写', exact: true }).first().click()
    await expect.poll(async () => (await api(`/books/${old.book_id}`)).chapters_final).toBe(2)
    const original = await api(`/books/${old.book_id}/chapters/1`)
    assert.equal(original.id, old.old_final_chapter.id)
    assert.equal(original.content, old.old_final_chapter.content)
    await navigate('chapter/2', old.book_id)
    await shot('30-旧书原章不变继续写第二章')
    const messages = await api(`/books/${old.book_id}/meeting?limit=2000`)
    assert.equal(messages.some(item => item.content?.includes('开写前，我把')), false, '第二包旧书不误触发开书补齐')
    evidence.legacy_passed = true
  }
  if (phase === 'calls') {
    await page.goto(`${base}/prompts`)
    await page.getByRole('tab', { name: '调用记录', exact: true }).click()
    await page.getByRole('combobox', { name: '按书筛选' }).selectOption(evidence.book_id)
    await page.getByRole('combobox', { name: '按角色筛选' }).selectOption('writer')
    await expect(page.locator('tbody tr').first()).toContainText('demo')
    await page.locator('tbody tr').filter({ hasText: '写作·正文' }).first().getByRole('button', { name: '查看', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '调用详情', exact: true })
    const prompt = dialog.locator('section').filter({ has: page.getByRole('heading', { name: '用户提示', exact: true }) })
    await expect(prompt).toContainText('这本书的惯例')
    assert.equal((await prompt.innerText()).includes(evidence.secret), false)
    await scrollText(prompt, '这本书的惯例：')
    await shot('31-写手调用含惯例不含底牌')
    await dialog.getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByRole('combobox', { name: '按角色筛选' }).selectOption('chief')
    for (const [purpose, contains, filename] of [
      ['写作·章纲', false, '32-出章纲调用无底牌'],
      ['写作·定下一篇', true, '33-定下一篇调用有底牌'],
      [/写作·第\d+卷方案/, true, '34-拆卷纲调用有底牌'],
    ]) {
      const row = page.locator('tbody tr').filter({ hasText: purpose }).first()
      await row.getByRole('button', { name: '查看', exact: true }).click()
      const user = dialog.locator('section').filter({ has: page.getByRole('heading', { name: '用户提示', exact: true }) })
      await expect(user).toBeVisible()
      assert.equal((await user.innerText()).includes(evidence.secret), contains, purpose)
      if (contains) await scrollText(user, '每个纪元，九天之上的天道')
      else await user.scrollIntoViewIfNeeded()
      await shot(filename)
      await dialog.getByRole('button', { name: '关闭', exact: true }).click()
    }
    evidence.calls_passed = true
  }
  if (phase === 'fill-messages') {
    await navigate('outline?view=threads')
    await page.getByText(/^开写前，我把第 1 篇/).scrollIntoViewIfNeeded()
    await shot('35-群聊先补齐第一篇')
    await page.getByText(/^开写前，我把第 1 卷/).scrollIntoViewIfNeeded()
    await shot('36-群聊再补齐第一卷')
  }
  if (phase === 'final-smoke') {
    const extra = JSON.parse(await fs.readFile(path.join(output, '任务5-补充卷展开-浏览器.json'), 'utf8'))
    const id = extra.book_id
    assert.ok(id && id !== evidence.book_id && id !== evidence.legacy_book_id)
    const before = await api(`/books/${id}/outline-tree`)
    const next = before.arcs.flatMap(arc => arc.volumes).flatMap(volume => volume.units).find(unit => !unit.chapters.length)
    assert.ok(next)
    await navigate(`outline?node=unit-${next.id}`, id)
    await page.getByRole('button', { name: '展开这一个', exact: true }).click()
    await expect(page.getByTestId('unit-chapter-outlines')).toBeVisible()
    const after = (await api(`/books/${id}/outline-tree`)).arcs.flatMap(arc => arc.volumes).flatMap(volume => volume.units).find(unit => unit.id === next.id)
    assert.equal(after.chapters.length, next.chapter_count)
    for (const key of ['title', 'summary', 'chapter_count', 'locked']) assert.deepEqual(after[key], next[key])
    await shot('37-最终版本展开章数严格不变')
    evidence.final_smoke = { book_id: id, unit_id: next.id, expected_chapters: next.chapter_count, actual_chapters: after.chapters.length, author_fields_unchanged: true }
  }
} catch (error) {
  evidence.failures ??= []
  evidence.failures.push({ phase, message: error.stack })
  await shot(`${phase}-失败现场`).catch(() => {})
  throw error
} finally {
  await fs.writeFile(statePath, JSON.stringify(evidence, null, 2))
  await fs.writeFile(path.join(output, '任务5-浏览器.json'), JSON.stringify(evidence, null, 2))
  await browser.close()
}
