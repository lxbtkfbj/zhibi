/** 补丁 1 独立浏览器验收：写入只经 UI，API GET 仅核对证据。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect as baseExpect } from '@playwright/test'

const base = 'http://127.0.0.1:4361'
assert.equal(process.env.TEST_BASE_URL, base)
const root = fileURLToPath(new URL('../../', import.meta.url))
const data = path.join(root, 'data/third-package-patch1')
const output = path.join(root, 'docs/第三包验收')
const statePath = path.join(data, 'browser-state.json')
const evidence = await fs.readFile(statePath, 'utf8').then(JSON.parse).catch(() => ({ screenshots: [], requests: [], errors: [], checks: {} }))
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM })
const page = await browser.newPage({ viewport: { width: 1720, height: 1100 }, reducedMotion: 'reduce' })
const expect = baseExpect.configure({ timeout: 120000 })
page.on('pageerror', error => evidence.errors.push(error.message))
page.on('request', request => { if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) evidence.requests.push({ method: request.method(), url: request.url(), body: request.postData() }) })
const api = async route => { const r = await page.request.get(`${base}/api${route}`); assert.equal(r.status(), 200, route); return r.json() }
let id = evidence.book_id
const book = () => api(`/books/${id}`)
const history = () => api(`/books/${id}/meeting?limit=2000`)
const reqs = () => api(`/books/${id}/requirements`)
const calls = async () => (await api(`/llm-calls?book_id=${id}&limit=100`)).items
const library = () => api(`/books/${id}/library`)
const shot = async name => { await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(350); const file = `补丁1-${name}.png`; await page.screenshot({ path: path.join(output, file) }); if (!evidence.screenshots.includes(file)) evidence.screenshots.push(file); console.log(file) }
const nav = async suffix => { await page.goto(`${base}/books/${id}/${suffix}`); const tab = page.getByRole('tab', { name: '稿件', exact: true }); if (await tab.isVisible()) await tab.click() }
const conversation = () => page.getByRole('region', { name: '会话消息与输入' })
const selectRole = async name => page.getByRole('button', { name, exact: true }).first().click()
const send = async text => { const input = conversation().locator('textarea'); await input.fill(text); await conversation().getByRole('button', { name: '发送', exact: true }).click(); await expect(input).toHaveValue(''); await expect(input).toBeEnabled() }
const latestNote = async () => (await history()).filter(m => m.speaker === 'author' && m.kind === 'note').at(-1)
const waitReply = async mid => expect.poll(async () => (await history()).some(m => m.payload?.reply_to?.includes(mid))).toBe(true)
const latestPlan = async thread => (await history()).filter(m => m.kind === 'plan' && (m.payload?.thread ?? 'group') === thread).at(-1)
const planStatus = async (mid, status) => expect.poll(async () => (await history()).find(m => m.id === mid)?.payload?.status).toBe(status)
const noOldWords = async () => assert.equal((await page.locator('body').innerText()).includes('短版'), false)
const createBook = async (prefill = false) => {
  await page.goto(base)
  await page.locator('textarea').first().fill('第三包补丁1独立演示：楚风凭还魂青灯修行，追查前世之死。')
  await page.getByRole('button', { name: '一步一步看', exact: true }).click()
  if (prefill) await page.getByRole('checkbox', { name: '先写设定，写好了再出故事方向', exact: true }).check()
  await page.getByRole('button', { name: '交给编辑部', exact: true }).click()
  await page.waitForURL(/\/books\//)
  id = new URL(page.url()).pathname.split('/')[2]
  return id
}
const addItem = async (category, name) => {
  await page.getByRole('button', { name: '新增一条', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新增一条' })
  await dialog.getByRole('combobox', { name: '新条目的类别' }).selectOption(category)
  await dialog.getByRole('textbox', { name: '条目名称' }).fill(name)
  await dialog.getByRole('button', { name: '建好这一条', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await page.getByRole('button', { name: '自己改', exact: true }).click()
  return page.getByRole('dialog', { name: `自己改 · ${name}`, exact: true })
}
const saveItem = async dialog => { await dialog.getByRole('button', { name: '保存这一条', exact: true }).click(); await expect(dialog).not.toBeVisible() }

try {
  const phase = process.argv[2]
  if (phase === 'models') {
    await page.goto(base)
    await page.getByRole('button', { name: '设置', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '设置', exact: true })
    await dialog.getByRole('button', { name: '＋ 添加', exact: true }).click()
    await dialog.getByRole('combobox', { name: '快速填写' }).selectOption('demo')
    await dialog.getByRole('textbox', { name: '模型配置名称' }).fill('补丁1-分流演示')
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    const profile = (await api('/llm/profiles')).find(p => p.name === '补丁1-分流演示')
    await dialog.getByRole('combobox', { name: '群聊分流使用的模型' }).selectOption(profile.id)
    await expect.poll(async () => (await api('/llm/roles')).router).toBe(profile.id)
    await expect(dialog.getByText('判断你在群聊里说的话是要改设定、记成要求还是提问。选一个快的模型就行，不用最强的。没选时用「默认」的模型。', { exact: true })).toBeVisible()
    await shot('01-群聊分流设置')
    evidence.router_profile = profile.id
    evidence.checks[1] = true
  }
  if (phase === 'prefill') {
    evidence.book_id = await createBook(true)
    await expect(page.getByRole('button', { name: '出三个故事方向', exact: true })).toBeVisible()
    assert.equal((await book()).active_job.pending.kind, 'setup_prefill')
    await shot('10a-先写设定入口')
    let dialog = await addItem('角色卡片', '楚风')
    await dialog.getByRole('combobox').selectOption('主角')
    await dialog.getByRole('textbox', { name: '编辑性格与说话方式', exact: true }).fill('作者手写：少言、护短，绝不滥杀。')
    await dialog.getByRole('textbox', { name: '编辑身世', exact: true }).fill('作者手写：旧朝遗孤，记得前世被师父害死。')
    await dialog.getByRole('textbox', { name: '编辑一句话', exact: true }).fill('作者手写：握着还魂青灯的复仇少年。')
    await saveItem(dialog)
    dialog = await addItem('特殊规则', '还魂青灯')
    await dialog.getByRole('textbox', { name: '编辑一句话', exact: true }).fill('作者手写：点灯一次，消耗一年寿命，回看死者最后一刻。')
    await dialog.getByRole('textbox', { name: '编辑一段话', exact: true }).fill('作者手写：青灯不能复活死人，只有楚风能用。')
    await saveItem(dialog)
    await page.getByRole('button', { name: '＋金手指', exact: true }).click()
    evidence.author_library = await library()
    await shot('10b-作者手写主角和金手指')
    await page.getByRole('button', { name: '出三个故事方向', exact: true }).click()
    await expect(page.getByRole('region', { name: '选择故事方向' }).getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
    const pitchCall = (await calls()).find(c => c.purpose === '开书·三个故事方向')
    const detail = await api(`/llm-calls/${pitchCall.id}`)
    const request = JSON.stringify(detail.request)
    assert(request.includes('【设定库里已经有的】') && request.includes('楚风') && request.includes('还魂青灯'))
    evidence.existing_call = detail
    await noOldWords(); await shot('10c-故事方向读取已有设定')
    await page.getByRole('region', { name: '选择故事方向' }).getByRole('button', { name: '用这个', exact: true }).first().click()
    await expect.poll(async () => (await book()).active_job?.pending?.piece).toBe('settings')
    await expect(page.getByRole('button', { name: '定调和设定先这样，去出大纲', exact: true })).toBeVisible()
    const lib = await library()
    const heroes = lib.characters.filter(c => c.role_type === '主角')
    assert.equal(heroes.length, 1); assert.equal(heroes[0].name, '楚风')
    for (const key of ['one_line', 'personality', 'background']) assert.equal(heroes[0][key], evidence.author_library.characters[0][key])
    const finger = lib.entries.find(e => e.name === '还魂青灯')
    assert.equal(finger.content, evidence.author_library.entries[0].content)
    evidence.hero_id = heroes[0].id
    evidence.finger_id = finger.id
    await noOldWords(); await shot('11a-只建一个主角并保留作者字段')
    await nav('concept')
    await expect(page.getByRole('button', { name: '定调和设定先这样，去出大纲', exact: true })).toBeVisible()
    await shot('11b-定调与设定合并确认')
    await page.getByRole('region', { name: '定调的一段话' }).getByRole('button', { name: '自己改', exact: true }).click()
    const input = page.getByRole('textbox', { name: '定调的一段话', exact: true })
    await input.fill(`${await input.inputValue()}\n作者手改：复仇不能牺牲无辜。`)
    await page.getByRole('button', { name: '保存定调', exact: true }).click()
    await expect(input).not.toBeVisible()
    await expect.poll(async () => (await book()).concept.story).toContain('作者手改：复仇不能牺牲无辜。')
    await nav(`library?cat=${encodeURIComponent('角色卡片')}&id=${heroes[0].id}`)
    await page.getByRole('button', { name: '自己改', exact: true }).click()
    dialog = page.getByRole('dialog', { name: '自己改 · 楚风', exact: true })
    await dialog.getByRole('textbox', { name: '编辑想要什么', exact: true }).fill('作者手改：查清师父为何背叛，不能连累同门。')
    await saveItem(dialog)
    await send('故事更偏复仇一点，师父改成反派，第一卷先查师父的动机')
    await expect.poll(async () => (await book()).active_job?.pending?.piece).toBe('settings')
    await expect.poll(async () => (await book()).concept.story).toContain('已按要求修改')
    await expect.poll(async () => (await library()).characters.find(c => c.role_type === '导师')?.background ?? '').toContain('已按要求修改')
    const after = await book()
    assert(after.concept.story.includes('作者手改：复仇不能牺牲无辜。'))
    const afterReqs = await reqs()
    assert(afterReqs.some(r => r.text.includes('第一卷先查师父的动机')))
    assert(!afterReqs.some(r => r.text.includes('故事更偏复仇一点')))
    evidence.combined_feedback = { book: after, library: await library(), requirements: afterReqs }
    await noOldWords(); await shot('12a-群聊意见拆分处理')
    await page.getByRole('button', { name: '定调和设定先这样，去出大纲', exact: true }).click()
    await expect(page.getByRole('button', { name: '确认，开写', exact: true })).toBeVisible()
    const progress = (await book()).setup_progress
    evidence.confirmed_progress = progress
    await noOldWords(); await shot('12b-确认一次后出大纲')
    evidence.checks[10] = true; evidence.checks[11] = true; evidence.checks[12] = true; evidence.checks[13] = true
  }
  if (phase === 'write-initial') {
    await nav('settings')
    await page.getByRole('button', { name: '省时', exact: true }).click()
    await page.getByRole('switch', { name: '新书前 3 章先给我试读', exact: true }).uncheck()
    await page.getByRole('switch', { name: '每卷卷纲都要我拍板', exact: true }).uncheck()
    await page.getByRole('spinbutton', { name: '每章字数', exact: true }).fill('600')
    await page.getByRole('heading', { name: '本书设置', exact: true }).click()
    await expect.poll(async () => (await api(`/books/${id}/settings`)).settings.chapter_words).toBe(600)
    await nav('outline?node=volume-1')
    await page.getByRole('button', { name: '确认，开写', exact: true }).click()
    await expect.poll(async () => { const b = await book(); if (b.active_job?.status === 'failed') throw new Error(b.active_job.error); return b.chapters_final }, { timeout: 300000 }).toBe(3)
    await expect.poll(async () => (await book()).active_job?.status ?? 'idle').toBe('idle')
    await shot('00-演示书写完三章')
  }
  if (phase === 'chat') {
    await nav('library'); await selectRole('编辑部群聊')
    const beforeCalls = await calls()
    await send('楚风现在什么境界？'); let note = await latestNote(); await waitReply(note.id)
    const newCalls = (await calls()).filter(c => !beforeCalls.some(b => b.id === c.id))
    assert(!newCalls.some(c => c.purpose === '群聊分流'))
    assert(newCalls.some(c => c.role === 'lorekeeper'))
    evidence.shortcut_calls = newCalls
    await shot('02-明显提问直接由设定师回答'); evidence.checks[2] = true
    await send('下一章节奏快一点'); note = await latestNote()
    await expect(page.getByTestId(`outcome-${note.id}`)).toContainText('主编在看')
    assert.equal(note.payload.outcome.kind, 'pending')
    await shot('03a-消息立即出现输入可用')
    await expect(page.getByTestId(`outcome-${note.id}`)).toContainText('只管第 4 章')
    const routerCall = (await calls()).find(c => c.purpose === '群聊分流')
    assert.equal(routerCall.role, 'router'); assert.equal(routerCall.profile_name, '补丁1-分流演示')
    evidence.router_call = routerCall
    await shot('03b-后台记下有范围的要求'); evidence.checks[3] = true
    await send('老怪如果表面救主角，其实想夺舍，会不会更抓人？'); await waitReply((await latestNote()).id)
    await send('我想开篇先压主角，老怪后面反转，可以吗？'); await waitReply((await latestNote()).id)
    await send('总结一下')
    await expect.poll(async () => (await latestPlan('group'))?.payload?.status).toBe('open')
    let plan = await latestPlan('group'); const card = page.getByTestId(`plan-${plan.id}`)
    await shot('05a-群聊生成可编辑方案卡')
    await card.getByRole('button', { name: '删除方案第 4 条', exact: true }).click()
    await card.getByRole('button', { name: '编辑方案第 1 条', exact: true }).click()
    await card.getByRole('textbox', { name: '修改方案第 1 条', exact: true }).fill('作者改过的方案要求：开篇一百字内进入压抑处境。')
    await card.getByRole('heading').click()
    await card.getByRole('button', { name: '按这个来', exact: true }).click()
    await planStatus(plan.id, 'applied')
    plan = (await history()).find(m => m.id === plan.id)
    assert.deepEqual(plan.payload.results.map(r => r.kind), ['requirement', 'edit', 'created'])
    assert.equal(plan.payload.plan.items.length, 3)
    assert((await reqs()).some(r => r.text === '作者改过的方案要求：开篇一百字内进入压抑处境。'))
    assert((await library()).characters.some(c => c.name === '老怪'))
    await expect(conversation().getByText('方案「（演示）方案」照办了：改了 1 处，新建 1 条，记了 1 条要求。', { exact: true })).toBeVisible()
    evidence.group_plan = plan
    await shot('05b-改删后逐条落地')
    await card.getByTestId(`outcome-${plan.id}`).filter({ hasText: '已记成要求' }).getByRole('button', { name: '撤销', exact: true }).click()
    await expect(card.getByText('已撤销', { exact: true })).toBeVisible()
    await shot('05c-撤销方案要求'); evidence.checks[5] = true
    await send('测试分流出错，下一章快一点'); note = await latestNote()
    await expect(page.getByTestId(`outcome-${note.id}`)).toContainText('没判断出来')
    await expect(page.getByTestId(`outcome-${note.id}`).getByRole('button', { name: '其实要记下', exact: true })).toBeVisible()
    await shot('09-分流失败可明确记下'); evidence.checks[9] = true
    await selectRole('设定师')
    await expect(conversation().getByText('这里只聊天，不会改动书稿，也不会记成要求。聊出想法以后说「总结一下」，看过方案再点「按这个来」。', { exact: true })).toBeVisible()
    await send('老怪的夺舍条件还可以怎么限制？'); await waitReply((await latestNote()).id)
    await conversation().getByRole('button', { name: '总结一下', exact: true }).click()
    await expect.poll(async () => (await latestPlan('lorekeeper'))?.payload?.status).toBe('open')
    plan = await latestPlan('lorekeeper')
    await shot('07a-私聊顶部总结生成方案')
    await send('就按这个来'); await planStatus(plan.id, 'applied')
    await expect(conversation().getByRole('button', { name: '记成要求', exact: true })).toHaveCount(0)
    await expect(conversation().getByRole('button', { name: '照这个改', exact: true })).toHaveCount(0)
    evidence.private_plan = (await history()).find(m => m.id === plan.id)
    await shot('07b-私聊口头按方案办'); evidence.checks[7] = true
  }
  if (phase === 'writing') {
    await nav('outline?node=volume-1'); await selectRole('编辑部群聊')
    const before = (await book()).chapters_final
    await page.getByRole('button', { name: '写 1 章', exact: true }).first().click()
    await page.getByRole('button', { name: '继续写', exact: true }).first().click()
    await expect.poll(async () => (await book()).active_job?.status).toMatch(/queued|running/)
    await send('下一章不要长篇回忆，第一句要求')
    const first = await latestNote()
    await send('下一章多一点动作，第二句要求')
    const second = await latestNote()
    await expect.poll(async () => (await history()).find(m => m.id === second.id)?.payload?.outcome.kind).toBe('to_job')
    const notes = (await history()).filter(m => [first.id, second.id].includes(m.id))
    assert(notes.every(m => m.payload.outcome.kind === 'to_job' && m.job_id))
    assert(notes[0].id < notes[1].id)
    const rows = await reqs()
    assert(rows.find(r => r.id === notes[0].payload.outcome.requirement_id).created_at <= rows.find(r => r.id === notes[1].payload.outcome.requirement_id).created_at)
    evidence.writing_notes = notes
    await shot('04-写作中两条要求按序入队')
    await expect.poll(async () => (await book()).chapters_final, { timeout: 300000 }).toBe(before + 1)
    await expect.poll(async () => (await book()).active_job?.status ?? 'idle').toBe('idle')
    evidence.checks[4] = true
  }
  if (phase === 'pitches') {
    evidence.pitch_book_id = await createBook(false)
    await expect(page.getByRole('region', { name: '选择故事方向' }).getByRole('button', { name: '用这个', exact: true })).toHaveCount(3)
    await send('我想用方向一，不过老怪的反转能更强一点吗？'); await waitReply((await latestNote()).id)
    await send('开篇先让主角吃亏，后面反杀会不会更爽？'); await waitReply((await latestNote()).id)
    await send('就用方向一')
    await expect.poll(async () => (await latestPlan('group'))?.payload?.status).toBe('open')
    const plan = await latestPlan('group')
    const note = await latestNote()
    assert.equal(note.payload.outcome.kind, 'plan_made')
    await shot('06a-等选方向聊过后先出方案')
    await page.getByTestId(`plan-${plan.id}`).getByRole('button', { name: '按这个来', exact: true }).click()
    await planStatus(plan.id, 'applied')
    await expect.poll(async () => (await book()).active_job?.pending?.round).toBe(2)
    const detail = await api(`/llm-calls/${(await calls()).find(c => c.purpose === '开书·三个故事方向').id}`)
    const request = JSON.stringify(detail.request)
    assert(request.includes('【和作者商量定的方案：') && request.includes('还没定的（先不用管）：') && plan.payload.plan.items.every(i => request.includes(i.change)))
    evidence.pitch_feedback_call = detail
    await noOldWords(); await shot('06b-整张方案重出故事方向'); evidence.checks[6] = true
  }
  if (phase === 'volume') {
    id = evidence.book_id
    await nav('settings')
    await page.getByRole('switch', { name: '每卷卷纲都要我拍板', exact: true }).check()
    await expect.poll(async () => (await api(`/books/${id}/settings`)).settings.volume_approval).toBe(true)
    await nav('outline?node=volume-1'); await selectRole('编辑部群聊')
    await conversation().getByRole('button', { name: '换个话题', exact: true }).click()
    await page.getByRole('button', { name: '一直写到完本', exact: true }).first().click()
    await page.getByRole('button', { name: '继续写', exact: true }).first().click()
    await expect.poll(async () => { const b = await book(); if (b.active_job?.status === 'failed') throw new Error(b.active_job.error); return b.active_job?.pending?.kind }, { timeout: 600000 }).toBe('volume_review')
    evidence.volume_wait = (await book()).active_job
    await send('第三个单元换个对手')
    await expect.poll(async () => (await calls()).some(c => c.purpose.includes('按作者意见修改'))).toBe(true)
    await expect.poll(async () => (await book()).active_job?.status).toBe('waiting_author')
    await expect.poll(async () => (await book()).active_job?.pending?.kind).toBe('volume_review')
    const cs = await calls()
    const rerun = await api(`/llm-calls/${cs.find(c => c.purpose.includes('按作者意见修改')).id}`)
    assert(rerun.request.user.includes('第三个单元换个对手'))
    evidence.volume_feedback_call = rerun
    evidence.volume_after = await book(); evidence.volume_calls = cs.slice(0, 12)
    await shot('08-无聊天时仍直接提卷纲意见'); evidence.checks[8] = true
  }
  if (phase === 'volume-verify') {
    await nav('outline?node=volume-2'); await selectRole('编辑部群聊')
    await expect.poll(async () => (await calls()).some(c => c.purpose.includes('按作者意见修改'))).toBe(true)
    await expect.poll(async () => (await book()).active_job?.status).toBe('waiting_author')
    assert.equal((await book()).active_job.pending.kind, 'volume_review')
    const detail = await api(`/llm-calls/${(await calls()).find(c => c.purpose.includes('按作者意见修改')).id}`)
    assert(detail.request.user.includes('第三个单元换个对手'))
    evidence.volume_feedback_call = detail
    evidence.volume_after = await book()
    await shot('08-无聊天时仍直接提卷纲意见'); evidence.checks[8] = true
  }
  if (phase === 'combined-shots') {
    id = evidence.pitch_book_id
    await nav('concept')
    await page.getByRole('region', { name: '选择故事方向' }).getByRole('button', { name: '用这个', exact: true }).first().click()
    await expect.poll(async () => (await book()).active_job?.pending?.piece).toBe('settings')
    const confirm = () => page.getByRole('button', { name: '定调和设定先这样，去出大纲', exact: true })
    await confirm().scrollIntoViewIfNeeded()
    await shot('11c-定调页合并确认按钮')
    await nav('library')
    await confirm().scrollIntoViewIfNeeded()
    await shot('11d-设定库页同一个确认按钮')
  }
  console.log(`PASS ${phase}`)
} catch (error) {
  await page.screenshot({ path: path.join(data, `failed-${process.argv[2]}.png`) }).catch(() => {})
  await fs.writeFile(path.join(data, `failed-${process.argv[2]}.txt`), await page.locator('body').innerText().catch(() => ''))
  console.error(error)
  process.exitCode = 1
} finally {
  await fs.writeFile(statePath, JSON.stringify(evidence, null, 2))
  await browser.close()
}
