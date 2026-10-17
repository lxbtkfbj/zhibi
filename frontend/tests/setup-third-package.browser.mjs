/** 第三包任务 3 的真实独立演示验收；只连明确提供的非日常端口，不拦截业务 API。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = process.env.TEST_BASE_URL
assert.ok(base, '必须指定独立 TEST_BASE_URL')
assert.ok(!['8000', '4320'].includes(new URL(base).port), '禁止连接日常服务')
const legacyId = process.env.THIRD_PACKAGE_LEGACY_BOOK_ID
assert.ok(legacyId, '必须先在独立环境准备第二包流程中途的书，并传入 THIRD_PACKAGE_LEGACY_BOOK_ID')
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const output = path.join(root, 'docs/第三包验收')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...((process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) ? { executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) })
const page = await browser.newPage({ viewport: { width: 1680, height: 1100 }, reducedMotion: 'reduce' })
const errors = [], screenshots = [], writes = [], librarySnapshots = []
let focusShotPromise = null
const partialLibrary = snapshot => snapshot.characters.length === 1 && snapshot.entries.some(entry => entry.name === '轮回镜')
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => { if (request.method() === 'POST') writes.push({ url: request.url(), body: request.postDataJSON() }) })
page.on('response', async response => {
  if (response.url().endsWith('/library') && response.ok()) try {
    const snapshot = await response.json()
    librarySnapshots.push(snapshot)
    if (!focusShotPromise && partialLibrary(snapshot)) focusShotPromise = (async () => {
      const library = page.getByTestId('three-step-settings')
      await expect(library.getByRole('region', { name: '重点', exact: true })).toContainText('轮回镜')
      await expect(library.getByRole('region', { name: '类别：角色卡片', exact: true }).getByRole('listitem')).toHaveCount(1)
      await shot('04-重点先出来')
    })()
  } catch { /* 关闭浏览器时不读取响应。 */ }
})
const expect = baseExpect.configure({ timeout: 90_000 })
const api = async route => { const response = await page.request.get(`${base}/api${route}`); assert.equal(response.status(), 200, route); return response.json() }
const shot = async name => { const filename = `任务3-${name}.png`; await page.screenshot({ path: path.join(output, filename) }); screenshots.push(filename) }
const scrollShot = async (section, name) => { await section.scrollIntoViewIfNeeded(); await shot(name) }
const create = async (mode, idea) => {
  await page.goto(base)
  await page.locator('textarea').first().fill(idea)
  if (mode === 'oneshot') await page.getByRole('button', { name: '一口气做完再给我看', exact: true }).click()
  else await page.getByRole('button', { name: '逐块确认（推荐）', exact: true }).click()
  await expect(page.getByText('先问我几个问题', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '交给编辑部', exact: true }).click()
  await page.waitForURL(/\/books\//)
  return new URL(page.url()).pathname.split('/')[2]
}

try {
  const profiles = await api('/llm/profiles')
  assert.ok(profiles.every(profile => profile.provider === 'demo'), '只允许演示模型')
  const bookId = await create('puzzle', '第三包任务3独立演示：逆世帝尊，测试自建类别；主角楚风重生，用轮回镜揭开前世之死。')
  const selection = page.getByRole('region', { name: '选择短版定调' })
  await expect(selection.getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
  const firstJob = (await api(`/books/${bookId}`)).active_job
  assert.equal(firstJob.setup_flow, 3)
  const firstRound = firstJob.pending.round
  await shot('01-三个短版')
  await selection.getByRole('textbox', { name: '重出短版的意见' }).fill('保留楚风和轮回镜，把复仇与前世谜团的联系写清楚。')
  await selection.getByRole('button', { name: '都不要，再来', exact: true }).click()
  await expect.poll(async () => (await api(`/books/${bookId}`)).active_job.pending?.round, { timeout: 90_000 }).toBe(firstRound + 1)
  await expect(selection.getByRole('button', { name: '用这个', exact: true }).first()).toBeEnabled()
  await selection.getByRole('radio', { name: /400/ }).check()
  await shot('02-重出并选400万')
  await selection.getByRole('button', { name: '用这个', exact: true }).first().click()
  await expect(page.getByTestId('three-step-concept')).toContainText('400 万字')
  await expect(page.getByTestId('three-step-concept')).toContainText('底牌')
  await expect(page.getByTestId('decision-bar').getByRole('button', { name: '确认', exact: true })).toBeEnabled()
  await shot('03-定调和底牌')
  await page.getByTestId('decision-bar').getByRole('button', { name: '确认', exact: true }).click()
  await expect(page.getByTestId('three-step-settings').getByRole('region', { name: '重点', exact: true })).toContainText('轮回镜')
  await expect.poll(() => librarySnapshots.some(partialLibrary)).toBe(true)
  await focusShotPromise
  await expect.poll(async () => (await api(`/books/${bookId}`)).active_job.pending?.piece, { timeout: 90_000 }).toBe('settings')
  await expect(page.getByTestId('three-step-settings')).toContainText('主编建了')
  await expect(page.getByTestId('three-step-settings')).toContainText('待处理的建议：')
  await shot('05-设定库完成')
  // 确认后的定调仍可就地改；流程位置不回退，下游变化只生成建议。
  await page.getByTestId('puzzle-tracker').getByRole('button', { name: '定调', exact: true }).click()
  const conceptPage = page.getByTestId('three-step-concept')
  await conceptPage.getByRole('button', { name: '改这一段', exact: true }).click()
  const story = conceptPage.getByRole('textbox', { name: '定调的一段话' })
  const revisedStory = `${await story.inputValue()}楚风要先守住楚家，再追查前世真相。`
  await story.fill(revisedStory)
  await conceptPage.getByRole('button', { name: '保存定调', exact: true }).click()
  await expect(conceptPage.getByRole('button', { name: '改这一段', exact: true })).toBeVisible()
  const afterStory = await api(`/books/${bookId}`)
  assert.equal(afterStory.concept.story, revisedStory)
  assert.equal(afterStory.active_job.pending.piece, 'settings')
  assert.equal(afterStory.setup_progress.pieces.concept, 'confirmed')
  await expect.poll(async () => (await api(`/books/${bookId}/suggestions`)).some(suggestion => suggestion.kind === 'concept')).toBe(true)
  await shot('05a-回头改定调不回退')
  await page.getByTestId('puzzle-tracker').getByRole('button', { name: '设定库', exact: true }).click()
  // 简版页暂不实现任务 4 的正式收件箱；这里通过现有建议接口验收接受类别及内含条目。
  const categorySuggestion = (await api(`/books/${bookId}/suggestions`)).find(suggestion => suggestion.payload?.op === 'create_category' && suggestion.payload.category?.name === '厉鬼')
  assert.ok(categorySuggestion, '建库建议包含厉鬼自建类别')
  assert.ok(categorySuggestion.payload.category.entries.some(entry => entry.name === '末班车司机'))
  const accepted = await page.request.post(`${base}/api/suggestions/${categorySuggestion.id}/accept`, { data: {} })
  assert.equal(accepted.status(), 200)
  const acceptedLibrary = await api(`/books/${bookId}/library`)
  const ghostCategory = acceptedLibrary.categories.find(category => category.name === '厉鬼')
  assert.ok(ghostCategory?.key.startsWith('custom:'))
  assert.ok(acceptedLibrary.entries.some(entry => entry.name === '末班车司机' && entry.category === ghostCategory.key))
  await page.reload()
  await expect(page.getByTestId('three-step-settings').getByRole('region', { name: '类别：厉鬼', exact: true })).toContainText('末班车司机')
  await scrollShot(page.getByRole('region', { name: '类别：厉鬼', exact: true }), '05b-接受自建类别和条目')
  const conversation = page.getByTestId('conversation-pane')
  await conversation.getByRole('textbox', { name: '修改意见', exact: true }).fill('把境界改成九重天，给我几个写法。')
  await conversation.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByTestId('three-step-settings')).toContainText('候选写法')
  await scrollShot(page.getByRole('region', { name: /的候选写法/ }).first(), '06-境界候选')
  await page.getByTestId('decision-bar').getByRole('button', { name: '确认', exact: true }).click()
  await expect(page.getByTestId('three-step-outline')).toContainText('青阳城篇')
  await expect(page.getByTestId('three-step-outline')).toContainText('第 1 章')
  await expect(page.getByTestId('decision-bar').getByRole('button', { name: '确认，开写', exact: true })).toBeEnabled()
  await shot('07-大纲和章纲')
  const outline = await api(`/books/${bookId}/outline`)
  const firstUnitId = outline.volumes[0].units[0].id
  const plannedChapters = (await api(`/books/${bookId}/chapters`)).filter(chapter => chapter.unit_id === firstUnitId).map(chapter => chapter.id)
  const setupCalls = (await api(`/llm-calls?book_id=${bookId}&limit=100`)).items.filter(call => call.purpose === '写作·章纲')
  assert.ok(setupCalls.length > 0, '开书时已记录章纲调用')
  await page.getByTestId('decision-bar').getByRole('button', { name: '确认，开写', exact: true }).click()
  await expect.poll(async () => (await api(`/books/${bookId}`)).chapters_final, { timeout: 180_000 }).toBe(3)
  const finished = await api(`/books/${bookId}`)
  assert.equal(finished.active_job.kind, 'write_book')
  assert.ok(['ready', 'writing'].includes(finished.status))
  assert.deepEqual(Object.values(finished.setup_progress.pieces), ['confirmed', 'confirmed', 'confirmed'])
  assert.deepEqual((await api(`/books/${bookId}/chapters`)).filter(chapter => chapter.unit_id === firstUnitId).map(chapter => chapter.id), plannedChapters)
  const writtenCalls = (await api(`/llm-calls?book_id=${bookId}&limit=100`)).items.filter(call => call.purpose === '写作·章纲')
  assert.equal(writtenCalls.length, setupCalls.length, '开写没有再给第一个单元出章纲')
  assert.ok(writes.some(write => write.url.endsWith(`/books/${bookId}/write`) && write.body.count === 3))
  await shot('08-自动写完前三章')
  const oneshotId = await create('oneshot', '第三包任务3一口气独立演示：逆世帝尊，楚风重生，以轮回镜追查前世之死。')
  await expect(page.getByTestId('three-step-outline')).toContainText('第 1 章')
  await expect(page.getByRole('button', { name: '确认，开写', exact: true })).toBeVisible()
  const oneshot = await api(`/books/${oneshotId}`)
  assert.equal(oneshot.active_job.pending.piece, 'outline')
  assert.equal(oneshot.chapters_final, 0)
  await shot('09-一口气停在大纲')
  await page.goto(`${base}/books/${legacyId}`)
  await expect(page.getByTestId('restart-setup-bar')).toBeVisible()
  await shot('10-第二包旧任务提示重开')
  await page.getByTestId('restart-setup-bar').getByRole('button', { name: '按新流程重开', exact: true }).click()
  await expect(page.getByRole('region', { name: '选择短版定调' })).toBeVisible()
  await shot('11-旧任务重开从短版开始')
  assert.equal((await api(`/books/${legacyId}`)).active_job.setup_flow, 3)
  const meeting = await api(`/books/${bookId}/meeting`)
  assert.ok(meeting.some(message => message.content.startsWith('重点先出来了：')))
  assert.deepEqual(errors, [])
  assert.ok(librarySnapshots.some(partialLibrary), '页面收到主角和轮回镜先行保存、其余尚未补齐的真实快照')
  const evidence = { bookId, oneshotId, legacyId, setupPlanChapterCalls: setupCalls.length, writtenPlanChapterCalls: writtenCalls.length, plannedChapters, libraryPartialObserved: true, conceptEditKeptSettings: true, acceptedCategoryWithEntries: true, screenshots }
  await fs.writeFile(path.join(output, '任务3-浏览器结果.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify(evidence, null, 2))
} finally { await browser.close() }
