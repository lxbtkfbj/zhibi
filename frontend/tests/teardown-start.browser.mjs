/** 第二批开始拆交互回归：所有 /api 请求拦截，仅在明确指定的独立前端运行。 */
import assert from 'node:assert/strict'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL
assert.ok(base, '指定独立 TEST_BASE_URL')
const url = new URL(base)
assert.ok(['127.0.0.1', 'localhost'].includes(url.hostname))
assert.ok(url.port && !['8000', '4320'].includes(url.port), '不能使用日常服务')
const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const profiles = [{ id: 'first', name: '默认演示', provider: 'demo', has_key: false }, { id: 'chosen', name: '拆书演示', provider: 'demo', has_key: false }]
const preview = {
  book_id: 'fixture', title: '合成验收书', author: '演示作者', intro: '', file: { name: 'fixture.txt', size: 10000 },
  encoding: 'utf-8', encoding_auto: true, chars: 10000, chapter_count: 40, volumes: [], first: { index: 1, title: '起点' }, last: { index: 40, title: '终点' },
  opening: '这是一段只用于交互回归的合成原文。', excluded: [{ order: 41, title: '完本感言', chars: 10, reason: '感言', head: '感言' }],
  number_issues: [], number_issue_total: 0, ads_removed: 0, duplicates_removed: 0, by_length: false,
}
const errors = []
let passed = 0
async function scenario(name, run, { availableProfiles = profiles, initialRoles = { default: 'first', teardown: 'chosen', router: null } } = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(`${name}: ${error.message}`))
  const calls = []
  let roles = { ...initialRoles }
  await page.route(`${base}/api/**`, async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api', '')
    const body = request.postDataJSON()
    if (request.method() !== 'GET') calls.push({ path, method: request.method(), body })
    let result = []
    if (path === '/health') result = { status: 'ok', components: { database: { ok: true }, redis: { ok: true }, worker: { ok: true } }, demo_mode: true }
    if (path === '/llm/profiles') result = availableProfiles
    if (path === '/llm/web-search') result = { has_key: false }
    if (path === '/llm/roles') {
      if (request.method() === 'PUT') roles = { ...roles, ...body }
      result = roles
    }
    if (path === '/teardown/fixture/preview') result = preview
    if (path === '/teardown/fixture/import') return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: '交互回归不实际导入' }) })
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) })
  })
  try { await run(page, calls); passed += 1; console.log(`PASS ${name}`) }
  catch (error) { console.error({ name, pageErrors: errors, body: (await page.locator('body').innerText()).slice(0, 5000) }); throw error }
  finally { await context.close() }
}

try {
  await scenario('确认页三个按钮、0与负数阻止、超过章数按全本、服务错误原样显示', async (page, calls) => {
    await page.goto(`${base}/teardown/fixture`)
    const input = page.getByRole('spinbutton', { name: '拆到第几章', exact: true })
    const start = page.getByRole('button', { name: '开始拆', exact: true })
    const onlyImport = page.getByRole('button', { name: '先只导入，不拆', exact: true })
    await expect(page.getByText('现在是 拆书演示', { exact: false })).toBeVisible()
    await expect(page.getByRole('button', { name: '不导入了', exact: true })).toBeVisible()
    await expect(input).toHaveAttribute('placeholder', '不填就是全本（40 章）')
    for (const value of ['0', '-2']) {
      await input.fill(value)
      await expect(page.getByText('至少拆 1 章', { exact: true })).toBeVisible()
      await expect(start).toBeDisabled()
      await expect(onlyImport).toBeDisabled()
    }
    await input.fill('41')
    await expect(start).toBeEnabled()
    await start.click()
    await expect(page.getByText('交互回归不实际导入', { exact: true })).toBeVisible()
    assert.deepEqual(calls.find(call => call.path.endsWith('/import')).body, { title: '合成验收书', author: '演示作者', include: [], start: { upto: null } })
    await expect(input).toHaveValue('41')
    await expect(start).toBeEnabled()
    await page.getByRole('checkbox').check()
    await expect(input).toHaveAttribute('placeholder', '不填就是全本（41 章）')
  })
  await scenario('确认页填写20按原值start，先只导入不携带start', async (page, calls) => {
    await page.goto(`${base}/teardown/fixture`)
    await page.getByRole('spinbutton', { name: '拆到第几章', exact: true }).fill('20')
    await page.getByRole('button', { name: '开始拆', exact: true }).click()
    await expect(page.getByText('交互回归不实际导入', { exact: true })).toBeVisible()
    assert.deepEqual(calls.filter(call => call.path.endsWith('/import'))[0].body.start, { upto: 20 })
    await page.getByRole('button', { name: '先只导入，不拆', exact: true }).click()
    await expect.poll(() => calls.filter(call => call.path.endsWith('/import')).length).toBe(2)
    assert.equal('start' in calls.filter(call => call.path.endsWith('/import'))[1].body, false)
  })
  for (const [name, availableProfiles, initialRoles, expected] of [
    ['默认', profiles, { default: 'first', teardown: null }, '默认演示'],
    ['第一项', profiles, { default: null, teardown: null }, '默认演示'],
    ['演示模式', [], { default: null, teardown: null }, '演示模式'],
  ]) await scenario(`费用提醒回退到${name}`, async page => {
    await page.goto(`${base}/teardown/fixture`)
    await expect(page.getByText(`现在是 ${expected}`, { exact: false })).toBeVisible()
  }, { availableProfiles, initialRoles })
  await scenario('模型分工拆书常显、审稿后、精确说明与跟随默认，能独立更换', async (page, calls) => {
    await page.goto(`${base}/settings`)
    await expect(page.getByRole('dialog', { name: '系统设置', exact: true })).toBeVisible()
    assert.deepEqual(await page.locator('.settings-tools-link').evaluateAll(items => items.map(item => item.getAttribute('aria-label'))), ['预设管理', '提示词与调用记录'])
    const row = page.getByLabel('拆书使用的模型', { exact: true })
    await expect(row).toBeVisible()
    await expect(row).toHaveValue('')
    await expect(row.locator('option').first()).toHaveText('跟随默认（默认演示）')
    await expect(page.getByText('拆书时读原文、归单元归卷都用它：一本书要调几百次，挑便宜快、格式稳的', { exact: true })).toBeVisible()
    const labels = await page.locator('select[aria-label$="使用的模型"]').evaluateAll(items => items.map(item => item.getAttribute('aria-label')))
    assert.equal(labels[labels.indexOf('审稿使用的模型') + 1], '拆书使用的模型')
    await expect(page.getByLabel('群聊分流使用的模型', { exact: true })).toHaveCount(0)
    await row.selectOption('chosen')
    await expect(row).toHaveValue('chosen')
    assert.deepEqual(calls.find(call => call.path === '/llm/roles').body, { teardown: 'chosen' })
  }, { initialRoles: { default: 'first', teardown: null, router: null } })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ passed, pageErrors: errors }))
} finally { await browser.close() }
