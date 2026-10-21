/** 拆书导入交互回归：合成预览、全部 API 拦截，只准独立前端端口。 */
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL
assert.ok(base, '指定独立 TEST_BASE_URL')
const url = new URL(base)
assert.ok(['127.0.0.1', 'localhost'].includes(url.hostname))
assert.ok(url.port && !['8000', '4320'].includes(url.port), '不能使用日常服务')
const executablePath = process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync)
const browser = await chromium.launch({ headless: true, executablePath })
const errors = []
let passed = 0
const fixture = {
  book_id: 'fixture', title: '合成导入书', author: '演示作者', intro: '', file: { name: 'fixture.txt', size: 1000 },
  encoding: 'utf-8', encoding_auto: true, traditional: true, t2s: true, t2s_seconds: 0.01,
  chars: 1000, chapter_count: 500, volumes: [{ index: 1, title: '苍风烟云', chapters: 500 }], volume_mode: 'editor', largest_volume: { index: 1, title: '苍风烟云', chapters: 500 },
  first: { index: 1, title: '起点' }, last: { index: 500, title: '终点' }, opening: '她说这里的名字已经转成简体。',
  excluded: [{ order: 501, title: '外门弟子', chars: 50, reason: '像是混进来的别的书', head: '别的书' }],
  number_issues: [{ index: 596, expected: 596, number: 396, kind: '打错了', count: 2, end_index: 597, end_number: 397 }], number_issue_total: 1,
  ignored_headings: Array.from({ length: 20 }, (_, index) => ({ index: 810 + index, title: `所在章${index + 1}`, line: index ? `（第${1460 + index}章）` : '第1章' })), ignored_heading_total: 22,
  ads_removed: 0, duplicates_removed: 0, by_length: false,
}

async function scenario(name, initial, run) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(`${name}: ${error.message}`))
  const calls = []
  let current = structuredClone(initial)
  await page.route(`${base}/api/**`, async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api', '')
    const body = request.postDataJSON()
    if (request.method() !== 'GET') calls.push({ path, method: request.method(), body })
    let result = []
    if (path === '/health') result = { status: 'ok', components: { database: { ok: true }, redis: { ok: true }, worker: { ok: true } }, demo_mode: true }
    if (path === '/llm/profiles') result = []
    if (path === '/llm/roles') result = { default: null, teardown: null }
    if (path === '/teardown/fixture/preview') result = current
    if (path === '/books/fixture' && request.method() === 'PATCH') { current = { ...current, ...body }; result = current }
    if (path === '/teardown/fixture/encoding') {
      if (body.encoding === 'big5') return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: '演示编码失败' }) })
      const traditional = current.traditional || body.encoding === 'utf-16'
      const t2s = body.t2s ?? traditional
      current = { ...current, traditional, t2s, opening: t2s ? '她说这里的名字已经转成简体。' : '她說這裡的名字仍是繁體。' }
      result = current
    }
    if (path === '/teardown/fixture/import') return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: '合成交互不实际导入' }) })
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) })
  })
  try { await page.goto(`${base}/teardown/fixture`); await run(page, calls); passed += 1; console.log(`PASS ${name}`) }
  catch (error) { console.error({ name, errors, body: (await page.locator('body').innerText()).slice(0, 8000) }); throw error }
  finally { await context.close() }
}

try {
  await scenario('繁体默认勾选、去掉和勾上重预览并保留手改，失败不丢预览', fixture, async (page, calls) => {
    const checkbox = page.getByRole('checkbox', { name: '原文是繁体，导入时转成简体', exact: true })
    await expect(checkbox).toBeChecked()
    await expect(page.getByText('转成简体，拆出来的人名、设定都用简体，不容易把同一个人认成两个', { exact: true })).toBeVisible()
    await page.getByLabel('书名', { exact: true }).fill('手改的书名')
    await checkbox.click()
    await expect(checkbox).not.toBeChecked()
    await expect(page.getByText('她說這裡的名字仍是繁體。', { exact: true })).toBeVisible()
    assert.deepEqual(calls.slice(0, 2), [
      { path: '/books/fixture', method: 'PATCH', body: { title: '手改的书名' } },
      { path: '/teardown/fixture/encoding', method: 'POST', body: { encoding: 'auto', t2s: false } },
    ])
    await expect(page.getByLabel('书名', { exact: true })).toHaveValue('手改的书名')
    await checkbox.click()
    await expect(checkbox).toBeChecked()
    await expect(page.getByText('她说这里的名字已经转成简体。', { exact: true })).toBeVisible()
    assert.deepEqual(calls.at(-1).body, { encoding: 'auto', t2s: true })
    await page.getByRole('button', { name: 'BIG5', exact: true }).click()
    await expect(page.getByText('演示编码失败', { exact: true })).toBeVisible()
    await expect(checkbox).toBeChecked()
    await expect(page.getByText('她说这里的名字已经转成简体。', { exact: true })).toBeVisible()
  })
  await scenario('超400章默认主编、按钮只切本地、原卷保留、导入携带选择', fixture, async (page, calls) => {
    const editor = page.getByRole('button', { name: '让主编按剧情分卷', exact: true })
    const original = page.getByRole('button', { name: '照原书分卷', exact: true })
    await expect(editor).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByText('原书的「苍风烟云」一卷有 500 章，太粗，默认让主编按剧情分。', { exact: true })).toBeVisible()
    await expect(page.getByText('主编一边拆一边分，大约每一百章一卷，收在大高潮上。下面原书的卷名不用。', { exact: true })).toBeVisible()
    await original.click()
    await expect(original).toHaveAttribute('aria-pressed', 'true')
    await expect(editor).toHaveAttribute('aria-pressed', 'false')
    await expect(page.getByText('第 1 卷 苍风烟云 · 500 章', { exact: true })).toBeVisible()
    assert.equal(calls.length, 0)
    await page.getByRole('button', { name: '先只导入，不拆', exact: true }).click()
    await expect(page.getByText('合成交互不实际导入', { exact: true })).toBeVisible()
    assert.equal(calls.at(-1).body.volume_mode, 'original')
    await editor.click()
    await page.getByRole('button', { name: '先只导入，不拆', exact: true }).click()
    await expect.poll(() => calls.filter(call => call.path.endsWith('/import')).length).toBe(2)
    assert.equal(calls.at(-1).body.volume_mode, 'editor')
  })
  await scenario('连续笔误及忽略标题逐字显示，忽略最多20条另报余数', fixture, async page => {
    await expect(page.getByText('原书把第 596–597 章写成了「第396章」到「第397章」', { exact: true })).toBeVisible()
    const ignored = page.getByRole('region', { name: '这几行没当成章标题', exact: true })
    await expect(ignored.getByText('看着像章标题，其实是正文里的字，留在原来那一章里', { exact: true })).toBeVisible()
    await expect(ignored.getByText('第 810 章「所在章1」里的「第1章」', { exact: true })).toBeVisible()
    await expect(ignored.locator('div > p')).toHaveCount(20)
    await expect(ignored.getByText('还有 2 处没列', { exact: true })).toBeVisible()
  })
  await scenario('简体没有转换框、小于等于400章默认原卷且无过粗提示', { ...fixture, traditional: false, t2s: false, chapter_count: 400, volume_mode: 'original', volumes: [{ index: 1, title: '原卷', chapters: 400 }], largest_volume: { index: 1, title: '原卷', chapters: 400 } }, async page => {
    await expect(page.getByLabel('书名', { exact: true })).toBeVisible()
    await expect(page.getByRole('checkbox', { name: '原文是繁体，导入时转成简体', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '照原书分卷', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('button', { name: '让主编按剧情分卷', exact: true })).toBeVisible()
    await expect(page.getByText('太粗，默认让主编按剧情分。', { exact: false })).toHaveCount(0)
  })
  await scenario('原书没有卷不出现分卷按钮', { ...fixture, traditional: false, t2s: false, volume_mode: 'editor', volumes: [], largest_volume: null }, async page => {
    await expect(page.getByLabel('书名', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '照原书分卷', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '让主编按剧情分卷', exact: true })).toHaveCount(0)
  })
  await scenario('先未认出繁体时换编码不强传false，重新认出繁体默认勾选', { ...fixture, traditional: false, t2s: false }, async (page, calls) => {
    await expect(page.getByLabel('书名', { exact: true })).toBeVisible()
    await expect(page.getByRole('checkbox', { name: '原文是繁体，导入时转成简体', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'UTF-16', exact: true }).click()
    await expect(page.getByRole('checkbox', { name: '原文是繁体，导入时转成简体', exact: true })).toBeChecked()
    assert.deepEqual(calls.at(-1).body, { encoding: 'utf-16' })
    await expect(page.getByText('她说这里的名字已经转成简体。', { exact: true })).toBeVisible()
  })
  await scenario('勾回前置排除章即重编号，排除章自身的假标题跟着显示和取消', { ...fixture,
    excluded: [{ order: 0, title: '排除的开头', chars: 50, reason: '不像正文', head: '开头' }, { order: 3, title: '排除章自身', chars: 50, reason: '不像正文', head: '自身' }],
    ignored_headings: [{ index: 1, order: 1, title: '后面的章', line: '第1章' }], ignored_heading_total: 1,
    ignored_heading_candidates: [{ order: 1, title: '后面的章', line: '第1章' }, { order: 3, title: '排除章自身', line: '第20章' }],
  }, async page => {
    const ignored = page.getByRole('region', { name: '这几行没当成章标题', exact: true })
    const before = page.getByRole('checkbox', { name: '排除的开头 · 50 字 · 不像正文 开头', exact: true })
    const itself = page.getByRole('checkbox', { name: '排除章自身 · 50 字 · 不像正文 自身', exact: true })
    await expect(ignored.getByText('第 1 章「后面的章」里的「第1章」', { exact: true })).toBeVisible()
    await before.check()
    await expect(ignored.getByText('第 2 章「后面的章」里的「第1章」', { exact: true })).toBeVisible()
    await itself.check()
    await expect(ignored.getByText('第 4 章「排除章自身」里的「第20章」', { exact: true })).toBeVisible()
    await itself.uncheck()
    await expect(ignored.getByText('排除章自身', { exact: false })).toHaveCount(0)
    await before.uncheck()
    await expect(ignored.getByText('第 1 章「后面的章」里的「第1章」', { exact: true })).toBeVisible()
  })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ passed, pageErrors: errors, realModelCalls: 0 }))
} finally { await browser.close() }
