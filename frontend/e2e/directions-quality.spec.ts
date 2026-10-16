import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import type { BookDetail, Job, Pending } from '../src/api/types'

// 真实 HTTP + Celery + PostgreSQL 演示验收；拒绝连接日常或其他任务的书库。
const evidence = path.resolve('../docs/第一包验收')
const marker = 'fe3b63b5-b940-4ce3-b11c-21cb417239df'
type Directions = Extract<Pending, { kind: 'setup_directions' }>
type Call = { id: number; model: string; purpose: string; request: { user: string; schema_name: string }; response: string }
async function get<T>(request: APIRequestContext, route: string): Promise<T> {
  const response = await request.get(`/api${route}`)
  expect(response.ok(), `${route}: ${await response.text()}`).toBeTruthy()
  return response.json()
}
async function settled(request: APIRequestContext, id: string, kind: string): Promise<Job> {
  let job: Job
  await expect.poll(async () => {
    job = await get<Job>(request, `/jobs/${id}`)
    if (job.status === 'failed') throw new Error(job.error)
    return job.status === 'waiting_author' && job.pending?.kind === kind
  }, { timeout: 120_000, intervals: [200, 500, 1000] }).toBe(true)
  return job!
}
async function shot(page: Page, name: string) {
  await fs.mkdir(evidence, { recursive: true })
  // 等待抽屉/页面进场完成，不把半透明过渡帧当作最终界面。
  await page.waitForTimeout(450)
  await page.screenshot({ path: path.join(evidence, `任务6-${name}.png`) })
}
async function saved(name: string, data: unknown) {
  await fs.mkdir(evidence, { recursive: true })
  await fs.writeFile(path.join(evidence, `任务6-${name}.json`), JSON.stringify(data, null, 2))
}
async function calls(request: APIRequestContext, bookId: string) {
  const result = await get<{ items: { id: number }[] }>(request, `/llm-calls?book_id=${bookId}&limit=100`)
  return Promise.all(result.items.map(c => get<Call>(request, `/llm-calls/${c.id}`)))
}
async function redo(page: Page, request: APIRequestContext, id: string, feedback: string) {
  await page.getByRole('button', { name: '都不满意，重新出', exact: true }).click()
  await page.getByRole('textbox', { name: '不满意的地方' }).fill(feedback)
  const response = page.waitForResponse(r => r.url().endsWith(`/jobs/${id}/directions`) && r.request().method() === 'POST')
  await page.getByRole('button', { name: '重新出方向', exact: true }).click()
  expect((await response).ok()).toBe(true)
  const job = await settled(request, id, 'setup_directions')
  const pending = job.pending as Directions
  await expect(page.getByRole('heading', { name: `方向一 · ${pending.directions[0].name}`, exact: true })).toBeVisible()
  return pending
}

test.beforeEach(async ({ request, baseURL }) => {
  expect(new URL(baseURL!).port).toBe('4342')
  const book = await get<BookDetail>(request, `/books/${marker}`)
  expect(book.title).toBe('任务6隔离验收标记（非作者作品）')
  const profiles = await get<{ provider: string }[]>(request, '/llm/profiles')
  expect(profiles.every(p => p.provider === 'demo')).toBe(true)
})

test('任务6：对标、五档篇幅、最近一轮重出与作者选定书名的真实演示链路', async ({ page, request }) => {
  test.setTimeout(300_000)
  page.setDefaultTimeout(15_000)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.getByRole('button', { name: '逐块确认（推荐）', exact: true }).click()
  const idea = '借用《某某》的设定，保留鬼屋经营和任务解锁场景的金手指，写一个不同剧情的小说。'
  await page.locator('textarea').first().fill(idea)
  const created = page.waitForResponse(r => r.url().endsWith('/api/books') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '交给编辑部', exact: true }).click()
  const { book, job } = await (await created).json() as { book: BookDetail; job: Job }
  const first = (await settled(request, job.id, 'setup_directions')).pending as Directions
  const understanding = page.getByRole('region', { name: '主编对对标作品的理解' })
  await expect(understanding).toContainText(first.reference!)
  await expect(understanding).toContainText('理解得不对？')
  expect(first.reference).toBeTruthy()
  expect(first.length.options).toEqual([
    '约 50 万字（短篇，约 170 章）', '约 100 万字（中篇，约 330 章）', '约 200 万字（长篇，约 670 章）',
    '约 300 万字（长篇，约 1000 章）', '500 万字以上（超长篇，约 1670 章起）',
  ])
  const selection = page.getByRole('region', { name: '选择开书方向' })
  await expect(selection.getByRole('radio')).toHaveCount(5)
  await expect(selection.getByRole('radio').nth(2)).toBeChecked()
  await expect(selection).toContainText('按每章约 3000 字估算章数。')
  await understanding.scrollIntoViewIfNeeded()
  await shot(page, '01-对标理解与五档篇幅')
  for (let i = 0; i < 3; i++) {
    expect(first.directions[i].titles).toHaveLength(2)
    const card = page.getByRole('article', { name: `方向 ${i + 1}：${first.directions[i].name}`, exact: true })
    await expect(card.getByRole('heading')).toHaveText(`方向${['一', '二', '三'][i]} · ${first.directions[i].name}`)
    expect(await card.getByRole('heading').evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeLessThanOrEqual(14)
    await card.screenshot({ path: path.join(evidence, `任务6-02-方向${i + 1}与书名候选.png`) })
  }
  const firstCalls = await calls(request, book.id)
  expect(firstCalls[0].request.user).not.toContain('【上一轮的方向（作者不满意）】')

  // 通过真实单书设置修改字数，重出后而不是只在前端重新计算章数。
  await page.goto(`/books/${book.id}/settings`)
  const settingsSaved = page.waitForResponse(r => r.url().endsWith(`/books/${book.id}/settings`) && r.request().method() === 'PATCH')
  await page.getByRole('spinbutton', { name: '每章字数' }).fill('2000')
  expect((await settingsSaved).ok()).toBe(true)
  await page.goto(`/books/${book.id}`)
  const feedback1 = '第一轮不要换掉鬼屋经营和任务解锁场景，只调整开局冲突，舞台要从城区扩展到全国。'
  const second = await redo(page, request, job.id, feedback1)
  expect(second.directions).not.toEqual(first.directions)
  expect(second.length.options).toEqual([
    '约 50 万字（短篇，约 250 章）', '约 100 万字（中篇，约 500 章）', '约 200 万字（长篇，约 1000 章）',
    '约 300 万字（长篇，约 1500 章）', '500 万字以上（超长篇，约 2500 章起）',
  ])
  await expect(selection).toContainText('按每章约 2000 字估算章数。')
  const secondCall = (await calls(request, book.id))[0]
  expect(secondCall.request.user).toContain('【上一轮的方向（作者不满意）】')
  expect(secondCall.request.user).toContain(first.reference!)
  expect(secondCall.request.user).toContain(feedback1)
  for (const direction of first.directions) {
    expect(secondCall.request.user).toContain(direction.name)
    expect(secondCall.request.user).toContain(direction.golden_finger)
    expect(secondCall.request.user).toContain(direction.stage_ladder)
    for (const title of direction.titles!) expect(secondCall.request.user).toContain(`《${title}》`)
  }
  const feedback2 = '第二轮再换一种开局矛盾，继续保留鬼屋经营和任务解锁场景，不要增加折磨式代价。'
  const third = await redo(page, request, job.id, feedback2)
  expect(third.directions).not.toEqual(second.directions)
  const thirdCall = (await calls(request, book.id))[0]
  expect(thirdCall.request.user).toContain(feedback1) // 历次意见仍在作者要求里。
  expect(thirdCall.request.user).toContain(feedback2)
  const previous = thirdCall.request.user.split('【上一轮的方向（作者不满意）】')[1]
  expect(previous).toBeTruthy()
  for (const direction of second.directions) expect(previous).toContain(direction.logline)
  for (const direction of first.directions) {
    if (!second.directions.some(d => d.logline === direction.logline)) expect(previous).not.toContain(direction.logline)
  }
  await understanding.scrollIntoViewIfNeeded()
  await shot(page, '03-重出后每章2000字篇幅')

  // 调用记录界面取证，不只读取数据库或用 mock 替代。
  await page.goto('/prompts')
  await page.getByRole('tab', { name: '调用记录', exact: true }).click()
  await page.getByRole('combobox', { name: '按书筛选' }).selectOption(book.id)
  await page.getByRole('button', { name: '查看', exact: true }).first().click()
  const userPrompt = page.getByRole('dialog', { name: '调用详情' }).locator('section').filter({ has: page.getByRole('heading', { name: '用户提示', exact: true }) })
  await expect(userPrompt).toContainText('【上一轮的方向（作者不满意）】')
  await userPrompt.locator('pre').evaluate(el => {
    const index = el.textContent!.indexOf('【上一轮的方向（作者不满意）】')
    const range = document.createRange()
    range.setStart(el.firstChild!, index)
    range.setEnd(el.firstChild!, index + 18)
    const scroller = el.closest('[role="dialog"]')!.querySelector('.scroll-thin')!
    scroller.scrollTop += range.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 20
  })
  await shot(page, '04-调用记录中的上一轮方向')
  await page.goto(`/books/${book.id}`)

  const chosen = third.directions[0]
  const title = chosen.titles![1]
  const card = page.getByRole('article', { name: `方向 1：${chosen.name}`, exact: true })
  const firstTitle = card.getByRole('button', { name: `《${chosen.titles![0]}》`, exact: true })
  const chosenTitle = card.getByRole('button', { name: `《${title}》`, exact: true })
  await firstTitle.click()
  await chosenTitle.click()
  await expect(firstTitle).toHaveAttribute('aria-pressed', 'false')
  await expect(chosenTitle).toHaveAttribute('aria-pressed', 'true')
  await chosenTitle.click()
  await expect(chosenTitle).toHaveAttribute('aria-pressed', 'false')
  await chosenTitle.focus()
  await page.keyboard.press('Enter')
  await expect(chosenTitle).toHaveAttribute('aria-pressed', 'true')
  await card.screenshot({ path: path.join(evidence, '任务6-05-单选作者书名.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('tab', { name: '稿件', exact: true }).click()
  await chosenTitle.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, '06-窄屏选书名')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('tab', { name: '外观', exact: true }).click()
  await page.getByRole('button', { name: '墨色·暗', exact: true }).click()
  await page.getByRole('button', { name: '关闭设置' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ink')
  await shot(page, '06-窄屏暗色选书名')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('tab', { name: '外观', exact: true }).click()
  await page.getByRole('button', { name: '宣纸·亮', exact: true }).click()
  await page.getByRole('button', { name: '关闭设置' }).click()

  const invalid = await request.post(`/api/jobs/${job.id}/directions`, { data: { action: 'choose', choice: 0, length: third.length.options[2], title: '不在本方向里的伪造书名' } })
  expect(invalid.status()).toBe(422)
  expect(await invalid.json()).toEqual({ detail: '请选择这个方向里的书名候选' })
  const choosing = page.waitForResponse(r => r.url().endsWith(`/jobs/${job.id}/directions`) && r.request().method() === 'POST')
  await card.getByRole('button', { name: '选这个', exact: true }).click()
  const chooseResponse = await choosing
  expect(chooseResponse.ok()).toBe(true)
  expect(chooseResponse.request().postDataJSON().title).toBe(title)
  const conceptJob = await settled(request, job.id, 'setup_piece')
  expect(conceptJob.pending?.kind === 'setup_piece' && conceptJob.pending.piece).toBe('concept')
  const finalBook = await get<BookDetail>(request, `/books/${book.id}`)
  expect(finalBook.concept.title).toBe(title)
  expect(finalBook.title).toBe(title)
  await expect(page).toHaveURL(new RegExp(`/books/${book.id}/concept$`))
  const conceptTitle = page.getByRole('main', { name: '稿件' }).getByRole('button', { name: title, exact: true })
  await expect(conceptTitle).toBeVisible()
  await expect(page.getByTestId('decision-bar')).toContainText('待你确认：定调')
  await conceptTitle.scrollIntoViewIfNeeded()
  await shot(page, '07-定调保留选定书名')
  const requirements = await get<{ text: string; source: string }[]>(request, `/books/${book.id}/requirements`)
  expect(requirements).toEqual(expect.arrayContaining([expect.objectContaining({ text: `书名用《${title}》`, source: 'answer' })]))
  const messages = await get<{ speaker: string; content: string }[]>(request, `/books/${book.id}/meeting`)
  expect(messages).toEqual(expect.arrayContaining([expect.objectContaining({ speaker: 'author', content: `选方向「${chosen.name}」，书名用《${title}》。` })]))
  expect(errors).toEqual([])
  await saved('真实演示结果', { bookId: book.id, jobId: job.id, idea, first, second, third, feedback1, feedback2, selectedTitle: title, conceptTitle: finalBook.concept.title, altTitles: finalBook.concept.alt_titles, invalidTitleStatus: invalid.status(), requirements, directionCalls: [firstCalls[0], secondCall, thirdCall], pageErrors: errors })
})

test('任务6：一口气模式也使用同一套五档篇幅', async ({ page, request }) => {
  const response = await request.post('/api/books', { data: { idea: '任务6一口气提问验收：少年从小镇出发调查失踪案。', mode: 'oneshot', ask: true } })
  expect(response.ok()).toBe(true)
  const { book, job } = await response.json() as { book: BookDetail; job: Job }
  const result = await settled(request, job.id, 'setup_questions')
  if (result.pending?.kind !== 'setup_questions') throw new Error('没有进入提问')
  const question = result.pending.questions[0]
  expect(question.options).toHaveLength(5)
  expect(question.recommended).toBe(2)
  expect(question.options[4]).toBe('500 万字以上（超长篇，约 1670 章起）')
  await page.goto(`/books/${book.id}`)
  for (const option of question.options) await expect(page.getByRole('button', { name: option, exact: false })).toBeVisible()
  await shot(page, '08-一口气模式五档篇幅')
  await saved('一口气篇幅结果', { bookId: book.id, jobId: job.id, question })
})

test('任务6回归：选方向后仍能换编辑部决定、解锁修改概念', async ({ page, request }) => {
  page.setDefaultTimeout(15_000)
  async function post(route: string, data: unknown) {
    const response = await request.post(`/api${route}`, { data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const { book, job } = await post('/books', { idea: '任务6兼容演示：少年持青灯在宗门追查身世。', mode: 'puzzle' }) as { book: BookDetail; job: Job }
  const pending = (await settled(request, job.id, 'setup_directions')).pending as Directions
  const title = pending.directions[0].titles![0]
  await post(`/jobs/${job.id}/directions`, { action: 'choose', choice: 0, title, length: pending.length.options[2] })
  await settled(request, job.id, 'setup_piece')
  await page.goto(`/books/${book.id}/concept`)
  await page.getByRole('radio', { name: '从欢喜冤家开始', exact: true }).check()
  const revised = page.waitForResponse(r => r.url().endsWith(`/jobs/${job.id}/piece`) && r.request().method() === 'POST')
  await page.getByRole('button', { name: '按我选的改', exact: true }).click()
  expect((await revised).ok()).toBe(true)
  await settled(request, job.id, 'setup_piece')
  const manuscript = page.getByRole('main', { name: '稿件' })
  await expect(manuscript).toContainText('感情线：从欢喜冤家开始')
  await post(`/jobs/${job.id}/piece`, { action: 'confirm', piece: 'concept' })
  const nodes = await settled(request, job.id, 'setup_piece')
  expect(nodes.pending?.kind === 'setup_piece' && nodes.pending.piece).toBe('nodes')
  const feedback = '主角钩子补充：每次点灯消耗一天寿元，必须权衡救人与自保'
  // 复现既有解锁概念路径；demo 的普通意见分派固定去第一卷，不把它当成通用语义模型。
  await post(`/jobs/${job.id}/piece`, { action: 'unlock', piece: 'concept', feedback })
  await settled(request, job.id, 'setup_piece')
  await expect(manuscript).toContainText('每次点灯消耗一天寿元，必须权衡救人与自保')
  const finalBook = await get<BookDetail>(request, `/books/${book.id}`)
  expect(finalBook.concept.title).toBe(title)
  await manuscript.getByRole('button', { name: title, exact: true }).scrollIntoViewIfNeeded()
  await shot(page, '09-选方向后仍可按意见修改概念')
  await saved('后续概念修改结果', { bookId: book.id, jobId: job.id, selectedTitle: title, feedback, concept: finalBook.concept })
})
