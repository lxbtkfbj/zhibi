/** Isolated draft/interaction tests. Prompt mutations are mocked, never persisted server-side. */
import assert from 'node:assert/strict'
import { chromium, expect } from '@playwright/test'

const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4332'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
const call = { id: 9461, book_id: null, book_title: null, role: 'chief', purpose: '草稿回归测试', model: 'demo', profile_name: '演示模式', prompt_tokens: null, completion_tokens: null, latency_ms: 12, ok: true, error: null, created_at: '2026-10-15T09:00:00Z' }
await page.route('**/api/llm-calls**', route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/9461') ? { ...call, request: { system: '系统提示', user: '用户提示', schema_name: '测试结构', schema: { type: 'object' }, method: 'demo' }, response: '{"ok":true}' } : { items: [call], next_before: null } }))
let saved = null
let releaseSave
let delayed = false
await page.route('**/api/prompts/setup_interview', async route => {
  if (route.request().method() === 'GET') return saved ? route.fulfill({ json: saved }) : route.continue()
  if (route.request().method() !== 'PUT') return route.continue()
  const original = await (await fetch(`${baseURL}/api/prompts/setup_interview`)).json()
  if (delayed) await new Promise(resolve => { releaseSave = resolve })
  saved = { ...original, customized: true, content: route.request().postDataJSON().content }
  return route.fulfill({ json: saved })
})
const editor = () => page.getByTestId('prompt-editor').locator('.cm-content')
try {
  await page.goto(`${baseURL}/prompts`)
  await page.getByRole('button', { name: '自定义', exact: true }).click()
  await editor().click()
  await editor().press('Control+End')
  await page.keyboard.insertText('\n需要保留的本地草稿')
  await expect(page.getByText('有未保存的本地草稿；切换提示词或分页会保留，点击「保存」才会发给编辑部。')).toBeVisible()
  await page.getByRole('button', { name: '定书的概念', exact: true }).click()
  await page.getByRole('heading', { name: '定书的概念' }).waitFor()
  await page.getByRole('button', { name: '动笔前提问', exact: true }).click()
  await expect(editor()).toContainText('需要保留的本地草稿')
  await page.getByRole('tab', { name: '调用记录', exact: true }).click()
  await page.getByRole('tab', { name: '提示词', exact: true }).click()
  await expect(editor()).toContainText('需要保留的本地草稿')
  await page.reload()
  await expect(editor()).toContainText('需要保留的本地草稿')
  console.log('PASS local prompt drafts survive template switching, calls tab, and reload')

  delayed = true
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(editor()).toHaveAttribute('contenteditable', 'false')
  await expect(page.getByRole('button', { name: '恢复默认', exact: true })).toBeDisabled()
  await expect.poll(() => typeof releaseSave).toBe('function')
  releaseSave()
  await expect(page.getByText('已保存，从下一步调用起对所有书生效。')).toBeVisible()
  await expect(editor()).toContainText('需要保留的本地草稿')
  assert.equal(await page.evaluate(() => sessionStorage.getItem('zhibi:prompt-draft:setup_interview')), null)
  console.log('PASS pending saves lock editing and reset; successful save clears only the saved draft')

  await page.getByRole('button', { name: '自定义', exact: true }).click()
  await editor().click()
  await editor().press('Control+End')
  await page.keyboard.insertText('\n慢请求里的旧稿')
  releaseSave = undefined
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => typeof releaseSave).toBe('function')
  await page.getByRole('button', { name: '定书的概念', exact: true }).click()
  await page.getByRole('heading', { name: '定书的概念' }).waitFor()
  await page.getByRole('button', { name: '动笔前提问', exact: true }).click()
  await expect(editor()).toHaveAttribute('contenteditable', 'true')
  await editor().click()
  await editor().press('Control+End')
  await page.keyboard.insertText('\n重新打开后继续编辑的新稿')
  releaseSave()
  await expect.poll(() => saved.content.includes('慢请求里的旧稿')).toBe(true)
  await page.reload()
  await expect(editor()).toContainText('重新打开后继续编辑的新稿')
  console.log('PASS a prior save completing after navigation cannot erase a newer local draft')

  await page.getByRole('tab', { name: '调用记录', exact: true }).click()
  const view = page.getByRole('button', { name: '查看', exact: true }).first()
  await view.click()
    const drawer = page.getByRole('dialog', { name: '调用详情', exact: true })
    await expect(drawer).toBeVisible()
    await expect.poll(() => drawer.evaluate(element => element.contains(document.activeElement))).toBe(true)
    await page.keyboard.press('Shift+Tab')
    await expect.poll(() => drawer.evaluate(element => element.contains(document.activeElement))).toBe(true)
    await page.keyboard.press('Escape')
    await expect(drawer).toHaveCount(0)
    await expect(view).toBeFocused()
  console.log('PASS call drawer is named, traps keyboard focus, and restores trigger focus on close')
  assert.deepEqual(errors, [])
} finally { await browser.close() }
