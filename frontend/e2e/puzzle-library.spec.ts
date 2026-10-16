/** 页面交互回归：所有 API 都由本文件拦截，不访问或修改作者数据库。 */
import { expect, test, type Page } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import type { BookDetail, Character, Foreshadowing, Secret, StoryNode } from '../src/api/types'
import type { PromptDetail } from '../src/api/prompts'

const root = '/books/library-mock'
const evidence = '../data/first-package-library'
const character = (id: string, name: string): Character => ({ id, name, aliases: [], role_type: '主角', gender: '', age: '', appearance: '', personality: '执着', background: '', abilities: '', goal: '', location: '', condition: '', notes: '', is_alive: true, first_appearance_chapter: null })
const node = (id: string, index: number, title: string): StoryNode => ({ id, index, title, kind: index === 1 ? 'opening' : 'ending', event: '', prerequisite: '', consequence: '', volume: index, status: 'pinned', origin: 'ai', editor_note: '', techniques: [], anchors: [] })
const ledger = (id: string, seq: number, kind: Foreshadowing['kind']): Foreshadowing => ({ id, seq, code: `${kind === '期待' ? 'E' : 'F'}${seq}`, kind, node_id: null, description: kind === '期待' ? '三年之约' : '古镜的裂纹', span: '长', plant_plan: '第一卷准备', payoff_plan: '最后揭晓', plant_volume: 1, payoff_volume: 2, status: 'planned', planted_chapter: null, hint_chapters: [], resolved_chapter: null })

async function mockLibrary(page: Page) {
  const book: BookDetail = { id: 'library-mock', title: '设定库回归', source: 'new', genre: '玄幻', status: 'ready', idea: '', logline: '', job_status: null, created_at: '', updated_at: '', style_reference: '', concept: {}, spine: {}, setup_progress: {}, requirements: [], trial_read_done: false, active_job: null, chapters_final: 0, words_final: 0 }
  const state = {
    book,
    characters: [character('c1', '林岚'), character('c2', '赵青')],
    nodes: [node('n1', 1, '古镜醒来'), node('n2', 2, '真相大白')],
    secrets: [{ id: 's1', seq: 1, code: 'S1', title: '古镜身份', truth: '古镜曾属于母亲', knowers: [{ name: '林岚', since_chapter: null, how: '母亲亲口告知' }], reader_knows: null, reveal_plan: '归乡时揭开', node_id: 'n2', status: 'hidden', created_chapter: null }] as Secret[],
    foreshadowings: [ledger('f1', 1, '伏笔'), ledger('f2', 2, '期待')],
    failNextSecret: false,
  }
  state.nodes[0].anchors = [{ id: 'a1', character_id: 'c1', character_name: '林岚', node_id: 'n1', kind: '登场', note: '第一次见到古镜' }]
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '')
    const method = route.request().method()
    const body = method === 'GET' || method === 'DELETE' ? {} : route.request().postDataJSON()
    const reply = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path.endsWith('/events')) return route.fulfill({ status: 204 })
    if (path === root && method === 'GET') return reply(state.book)
    if (path === `${root}/outline`) return reply({ concept: {}, volumes: [] })
    if (path === `${root}/nodes`) return reply(state.nodes)
    if (path === `${root}/bible`) return reply({ characters: state.characters, relationships: [], world_entries: [], foreshadowings: state.foreshadowings, secrets: state.secrets })
    if (path === `${root}/secrets` && method === 'GET') return reply(state.secrets)
    if (path === `${root}/secrets` && method === 'POST') {
      if (state.failNextSecret) { state.failNextSecret = false; return reply({ detail: '演示保存失败，请重试' }, 409) }
      const secret: Secret = { id: `s${state.secrets.length + 1}`, seq: state.secrets.length + 1, code: `S${state.secrets.length + 1}`, title: '', truth: '', knowers: [], reader_knows: null, reveal_plan: '', node_id: null, status: 'hidden', created_chapter: null, ...body }
      state.secrets.push(secret)
      return reply(secret, 201)
    }
    if (path.startsWith('/secrets/')) {
      const id = path.split('/').at(-1)
      if (method === 'DELETE') { state.secrets = state.secrets.filter(secret => secret.id !== id); return route.fulfill({ status: 204 }) }
      const secret = state.secrets.find(secret => secret.id === id)!
      Object.assign(secret, body)
      return reply(secret)
    }
    if (path === `${root}/anchors` && method === 'POST') {
      const anchor = { id: 'a-new', character_name: state.characters.find(item => item.id === body.character_id)!.name, ...body }
      state.nodes.find(node => node.id === body.node_id)!.anchors.push(anchor)
      return reply(anchor, 201)
    }
    if (path.startsWith('/anchors/')) {
      const id = path.split('/').at(-1)
      const originalNode = state.nodes.find(node => node.anchors.some(anchor => anchor.id === id))!
      const anchor = originalNode.anchors.find(anchor => anchor.id === id)!
      if (method === 'DELETE') { originalNode.anchors = originalNode.anchors.filter(anchor => anchor.id !== id); return route.fulfill({ status: 204 }) }
      Object.assign(anchor, body)
      if (body.node_id && body.node_id !== originalNode.id) {
        originalNode.anchors = originalNode.anchors.filter(anchor => anchor.id !== id)
        state.nodes.find(node => node.id === body.node_id)!.anchors.push(anchor)
      }
      return reply(anchor)
    }
    if (path === `${root}/foreshadowings` && method === 'POST') {
      const item = { ...ledger('f-new', 3, body.kind), ...body }
      state.foreshadowings.push(item)
      return reply(item, 201)
    }
    if (path.startsWith('/foreshadowings/')) {
      const id = path.split('/').at(-1)
      if (method === 'DELETE') { state.foreshadowings = state.foreshadowings.filter(item => item.id !== id); return route.fulfill({ status: 204 }) }
      const item = state.foreshadowings.find(item => item.id === id)!
      Object.assign(item, body)
      return reply(item)
    }
    if (path === '/health') return reply({ status: 'ok', components: {} })
    if (path === '/glossary') return reply({ terms: [] })
    if (path === `${root}/usage`) return reply({ calls: 0, prompt_tokens: null, completion_tokens: null, by_role: {} })
    if (path === `${root}/threads` || path.startsWith(`${root}/chapters`)) return reply([])
    // No fallthrough: an unhandled request must never reach the real backend.
    return reply({ detail: `未模拟接口：${method} ${path}` }, 404)
  })
  return state
}

test.beforeEach(async ({ page }) => {
  await mkdir(evidence, { recursive: true })
  page.on('pageerror', error => { throw error })
})

test('人物锚点增改删：节点下拉、类型分段、说明就地编辑', async ({ page }) => {
  const state = await mockLibrary(page)
  await page.goto(`${root}/characters`)
  const pane = page.getByRole('main', { name: '稿件' })
  await expect(pane).toContainText('节点 1「古镜醒来」· 登场——第一次见到古镜')
  await pane.getByRole('button', { name: /林岚/ }).click()
  const sheet = page.getByRole('dialog')
  await sheet.getByLabel('林岚的锚点节点').selectOption('n2')
  await expect.poll(() => state.nodes[1].anchors.length).toBe(1)
  await sheet.getByRole('button', { name: '高光', exact: true }).click()
  await expect.poll(() => state.nodes[1].anchors[0]?.kind).toBe('高光')
  await sheet.getByRole('button', { name: '第一次见到古镜', exact: true }).click()
  await sheet.getByRole('textbox').fill('在古镜中发现母亲留下的指引')
  await sheet.getByRole('textbox').press('Control+Enter')
  await expect.poll(() => state.nodes[1].anchors[0]?.note).toContain('母亲留下')
  await sheet.getByRole('button', { name: '添加锚点', exact: true }).click()
  await sheet.getByLabel('新锚点节点').selectOption('n1')
  await sheet.getByLabel('新锚点说明').fill('新增锚点说明')
  await sheet.getByRole('button', { name: '添加', exact: true }).click()
  await expect.poll(() => state.nodes[0].anchors.length).toBe(1)
  await expect(sheet.getByText('新增锚点说明', { exact: true })).toBeVisible()
  page.once('dialog', dialog => dialog.accept())
  await sheet.getByRole('button', { name: '删除节点 1 的登场锚点' }).click()
  await expect.poll(() => state.nodes[0].anchors.length).toBe(0)
  await page.screenshot({ path: `${evidence}/人物锚点.png`, fullPage: true })
})

test('信息差完整 CRUD、知情人增改删与失败草稿保留', async ({ page }) => {
  const state = await mockLibrary(page)
  await page.goto(`${root}/secrets`)
  const pane = page.getByRole('main', { name: '稿件' })
  await expect(pane.getByRole('button', { name: /林岚，开书时知道/ })).toHaveAttribute('title', '母亲亲口告知')
  await pane.getByLabel('S1 读者知不知道').selectOption('部分')
  await expect.poll(() => state.secrets[0].reader_knows).toBe('部分')
  await pane.getByLabel('S1 状态').selectOption('public')
  await expect.poll(() => state.secrets[0].status).toBe('public')
  await pane.getByLabel('S1 揭开节点').selectOption('n1')
  await expect.poll(() => state.secrets[0].node_id).toBe('n1')
  await pane.getByRole('button', { name: '添加知情人', exact: true }).click()
  await pane.getByLabel('知情人', { exact: true }).selectOption('赵青')
  await pane.getByLabel('知情章节').fill('35')
  await pane.getByLabel('知情方式').fill('在卷末亲眼看见')
  await pane.getByRole('button', { name: '保存知情人', exact: true }).click()
  await expect.poll(() => state.secrets[0].knowers.length).toBe(2)
  await expect(pane.getByRole('button', { name: /赵青，第 35 章知道/ })).toBeVisible()
  await pane.getByRole('button', { name: /赵青，第 35 章知道/ }).click()
  await pane.getByLabel('知情章节').fill('36')
  await pane.getByRole('button', { name: '保存知情人', exact: true }).click()
  await expect.poll(() => state.secrets[0].knowers[1].since_chapter).toBe(36)
  page.once('dialog', dialog => dialog.accept())
  await pane.getByRole('button', { name: '移除知情人赵青', exact: true }).click()
  await expect.poll(() => state.secrets[0].knowers.length).toBe(1)
  await pane.getByRole('button', { name: '古镜曾属于母亲', exact: true }).click()
  await pane.getByRole('textbox').fill('古镜来自旧王朝')
  await pane.getByRole('textbox').press('Control+Enter')
  await expect.poll(() => state.secrets[0].truth).toBe('古镜来自旧王朝')
  await pane.getByRole('button', { name: '添加秘密', exact: true }).click()
  await pane.getByLabel('新秘密短名').fill('保存失败后仍保留')
  await pane.getByLabel('新秘密真相').fill('这段作者输入不能丢')
  state.failNextSecret = true
  await pane.getByRole('button', { name: '添加秘密', exact: true }).last().click()
  await expect(pane.getByText('演示保存失败，请重试')).toBeVisible()
  await expect(pane.getByLabel('新秘密真相')).toHaveValue('这段作者输入不能丢')
  await pane.getByRole('button', { name: '添加秘密', exact: true }).last().click()
  await expect.poll(() => state.secrets.length).toBe(2)
  await expect(pane.getByText('保存失败后仍保留', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${evidence}/信息差.png`, fullPage: true })
  page.once('dialog', dialog => dialog.accept())
  await pane.getByRole('button', { name: '删除 S2', exact: true }).click()
  await expect.poll(() => state.secrets.length).toBe(1)
})

test('伏笔与期待筛选、新增类型、期待状态和动作词', async ({ page }) => {
  const state = await mockLibrary(page)
  await page.goto(`${root}/foreshadowing`)
  const pane = page.getByRole('main', { name: '稿件' })
  await pane.getByRole('group', { name: '按台账类型筛选' }).getByRole('button', { name: '期待', exact: true }).click()
  await expect(pane.getByText('三年之约', { exact: true })).toBeVisible()
  await expect(pane.getByText('古镜的裂纹', { exact: true })).toHaveCount(0)
  await expect(pane).toContainText('台账动作：立下 / 提醒 / 兑现')
  await pane.getByLabel('E2 状态').selectOption('resolved')
  await expect.poll(() => state.foreshadowings[1].status).toBe('resolved')
  await expect(pane.getByLabel('E2 状态').locator('option:checked')).toHaveText('已兑现')
  await pane.getByRole('button', { name: '添加条目', exact: true }).click()
  await expect(pane.getByRole('group', { name: '新增条目类型' }).getByRole('button', { name: '期待' })).toHaveAttribute('aria-pressed', 'true')
  await pane.getByLabel('新增台账内容').fill('重逢之约')
  await pane.getByRole('button', { name: '添加期待', exact: true }).click()
  await expect.poll(() => state.foreshadowings.length).toBe(3)
  expect(state.foreshadowings[2].kind).toBe('期待')
  await expect(pane.getByText('E3', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${evidence}/伏笔与期待.png`, fullPage: true })
  page.once('dialog', dialog => dialog.accept())
  await pane.getByRole('button', { name: '删除 E3', exact: true }).click()
  await expect.poll(() => state.foreshadowings.length).toBe(2)
})

test('运行期间信息差与人物锚点只读', async ({ page }) => {
  const state = await mockLibrary(page)
  state.book.status = 'setting_up'
  state.book.active_job = { id: 'job1', book_id: 'library-mock', kind: 'book_setup', status: 'running', pending: null, error: '', created_at: '', updated_at: '', finished_at: null }
  await page.goto(root)
  const pane = page.getByRole('main', { name: '稿件' })
  await expect(pane.getByText('概览', { exact: true })).toBeVisible()
  await page.locator(`nav a[href="${root}/secrets"]`).click()
  await expect(pane).toContainText('这里暂时只能看、不能改')
  await expect(pane.getByRole('button', { name: '添加秘密', exact: true })).toHaveCount(0)
  await expect(pane.getByRole('combobox')).toHaveCount(0)
  await page.locator(`nav a[href="${root}/characters"]`).last().click()
  await pane.getByRole('button', { name: /林岚/ }).click()
  const sheet = page.getByRole('dialog')
  await expect(sheet.getByRole('button', { name: '添加锚点', exact: true })).toHaveCount(0)
  await expect(sheet.getByLabel('林岚的锚点节点')).toBeDisabled()
  await expect(sheet.getByRole('button', { name: '登场', exact: true })).toBeDisabled()
})

test('窄屏暗色信息差与人物锚点没有横向溢出', async ({ page }) => {
  await mockLibrary(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'ink', reducedMotion: true })))
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto(`${root}/secrets`)
  await page.getByRole('tab', { name: '稿件', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ink')
  const pane = page.getByRole('main', { name: '稿件' })
  await expect(pane.getByText('古镜身份', { exact: true })).toBeVisible()
  expect(await pane.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({ path: `${evidence}/信息差-窄屏暗色.png`, fullPage: true })
  await page.goto(`${root}/characters`)
  await page.getByRole('tab', { name: '稿件', exact: true }).click()
  await pane.getByRole('button', { name: /林岚/ }).click()
  const sheet = page.getByRole('dialog')
  await sheet.getByLabel('林岚的锚点节点').scrollIntoViewIfNeeded()
  expect(await sheet.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({ path: `${evidence}/人物锚点-窄屏暗色.png`, fullPage: true })
})

test('提示词默认更新提醒、新增变量说明与恢复默认', async ({ page }) => {
  let prompt: PromptDetail = { name: 'setup_interview', title: '动笔前提问', group: '开书', role: 'chief', when: '开书时', customized: true, updated_at: '', last_call: null, variables: [{ name: 'idea', label: '作者想法' }], default_changed: true, new_variables: [{ name: 'glossary', label: '术语表' }], content: '作者自定义 {{idea}}', default_content: '默认内容 {{idea}} {{glossary}}' }
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/prompts') return route.fulfill({ json: [prompt] })
    if (path === '/api/prompts/setup_interview') {
      if (route.request().method() === 'DELETE') {
        prompt = { ...prompt, customized: false, content: prompt.default_content, variables: [...prompt.variables, ...prompt.new_variables], default_changed: false, new_variables: [] }
        return route.fulfill({ status: 204 })
      }
      return route.fulfill({ json: prompt })
    }
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', components: {} } })
    return route.fulfill({ status: 404, json: { detail: `未模拟接口：${path}` } })
  })
  await page.goto('/prompts')
  await expect(page.getByRole('heading', { name: /动笔前提问.*默认版本已更新/ })).toBeVisible()
  await expect(page.getByRole('note')).toContainText('术语表（glossary）')
  await expect(page.getByTestId('prompt-editor')).toContainText('作者自定义')
  await page.screenshot({ path: `${evidence}/提示词默认更新.png`, fullPage: true })
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: '恢复默认', exact: true }).click()
  await expect(page.getByText('已恢复默认。', { exact: true })).toBeVisible()
  await expect(page.getByRole('note')).toHaveCount(0)
  await expect(page.getByTestId('prompt-editor')).toContainText('默认内容')
})
