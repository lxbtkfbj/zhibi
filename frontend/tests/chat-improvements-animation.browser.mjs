/** 聊天改进任务 1 的动画补验：两书 × 浮窗/侧栏，真实 demo 流式回答中点击回最新。
 * 独立保存 browser-animation-results.json，不覆盖完整34组证据或三张截图。
 * 独立预览使用 ZHIBI_DEMO_DELAY=16，给真实流式上翻和220ms动画留下完整采样窗口。
 * TEST_BASE_URL=http://127.0.0.1:4381 node tests/chat-improvements-animation.browser.mjs
 */
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect as baseExpect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const base = process.env.TEST_BASE_URL
assert.ok(base)
const origin = new URL(base)
assert.ok(['127.0.0.1', 'localhost'].includes(origin.hostname) && origin.port && !['8000', '4320'].includes(origin.port))
const fixturePath = resolve(process.env.CHAT_FIXTURE || resolve(root, 'data/chat-improvements-task1/fixture.json'))
const fixture = JSON.parse(await readFile(fixturePath, 'utf8'))
const output = resolve(dirname(fixturePath), 'browser-animation-results.json')
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || process.env.ZHIBI_CHROMIUM || ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(existsSync)
const browser = await chromium.launch({ headless: true, executablePath })
const context = await browser.newContext({ viewport: { width: 1500, height: 1050 }, reducedMotion: 'no-preference', serviceWorkers: 'block' })
const page = await context.newPage()
const expect = baseExpect.configure({ timeout: 30_000 })
const evidence = { base, reducedMotion: 'no-preference', checks: [], errors: [], demoCalls: [] }
page.on('pageerror', error => evidence.errors.push(error.message))
const get = async path => { const response = await context.request.get(`${base}/api${path}`); assert.equal(response.status(), 200); return response.json() }
const list = () => page.getByTestId('chat-messages')
const composer = () => page.getByLabel('给编辑部发消息', { exact: true })
const distance = () => list().evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)
async function wheel(delta) {
  const box = await list().boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, delta)
}
try {
  assert.ok((await get('/llm/profiles')).every(profile => profile.provider === 'demo'))
  for (const [kind, id] of [['new', fixture.new_book_id], ['teardown', fixture.teardown_book_id]]) {
    await page.goto(`${base}/desk/${id}`)
    const ball = page.locator('[role="button"][title="编辑部"]')
    await expect(ball.or(composer())).toBeVisible()
    if (await ball.isVisible()) await ball.click()
    await expect(composer()).toBeVisible()
    assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), false)
    for (const mode of ['float', 'side']) {
      const switcher = page.getByRole('button', { name: mode === 'float' ? '浮起来' : '贴到右边', exact: true })
      if (await switcher.isVisible()) await switcher.click()
      await wheel(100000)
      await expect.poll(distance).toBeLessThanOrEqual(1)
      await wheel(-750)
      await expect.poll(distance).toBeGreaterThan(48)
      await expect(page.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
      await composer().click()
      await page.keyboard.insertText('@主编 灯光\n影子\n人物\n街道\n场景\n是什么样？')
      // 先把鼠标放在消息区，短demo流式期间只滚轮，不耗在重新定位上。
      const listBox = await list().boundingBox()
      await page.mouse.move(listBox.x + listBox.width / 2, listBox.y + listBox.height / 2)
      const responsePromise = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/books/${id}/notes`)
      await composer().press('Enter')
      assert.equal((await responsePromise).status(), 201)
      // 作者主动发送会重新跟到底；等真实流式开头后再上翻，验编辑部后续新字不拽回。
      const live = page.locator('[data-testid^="reply-"][data-state="streaming"]').last()
      await page.waitForFunction(() => document.querySelector('[data-testid^="reply-"][data-state="streaming"]'))
      await expect(live).toBeVisible()
      const replyTestId = await live.getAttribute('data-testid')
      await page.mouse.wheel(0, -750)
      await page.waitForFunction(() => {
        const el = document.querySelector('[data-testid="chat-messages"]')
        return el.scrollHeight - el.scrollTop - el.clientHeight > 48
      })
      await expect.poll(distance).toBeGreaterThan(48)
      const jump = page.getByRole('button', { name: '有新回答', exact: true })
      await page.waitForFunction(() => document.querySelector('button[aria-label="有新回答"]'))
      await expect(jump).toBeVisible()
      await expect(page.getByTestId(replyTestId)).toHaveAttribute('data-state', 'streaming')
      // 本轮独立预览的demo延迟为16（每8字约400ms）；等半个产字周期再点，令220ms动画覆盖下一次推字。
      await page.waitForTimeout(200)
      await expect(page.getByTestId(replyTestId)).toHaveAttribute('data-state', 'streaming')
      // 被动记录真实帧；不改scrollTop，也不模拟点击。点击时间由真实鼠标事件标记。
      await jump.evaluate((button, replyTestId) => {
        window.__chatAnimationFrames = []
        window.__chatAnimationDone = false
        window.__chatAnimationStart = null
        button.addEventListener('click', () => { window.__chatAnimationStart = performance.now() }, { once: true, capture: true })
        const box = document.querySelector('[data-testid="chat-messages"]')
        const reply = document.querySelector(`[data-testid="${replyTestId}"]`)
        const sample = now => {
          const start = window.__chatAnimationStart
          if (start !== null) window.__chatAnimationFrames.push({ ms: now - start, top: box.scrollTop, height: box.scrollHeight, client: box.clientHeight, chars: reply.innerText.length, state: reply.dataset.state })
          if (start !== null && now - start >= 600) window.__chatAnimationDone = true
          else requestAnimationFrame(sample)
        }
        requestAnimationFrame(sample)
      }, replyTestId)
      await jump.click()
      await page.waitForFunction(() => window.__chatAnimationDone)
      const frames = await page.evaluate(() => window.__chatAnimationFrames)
      evidence.lastSample = { kind, mode, frames }
      const moving = frames.filter(frame => frame.ms >= 0 && frame.ms <= 220)
      assert.ok(moving.length >= 4, '真实动画必须跨多个浏览器帧')
      const positions = [...new Set(moving.map(frame => frame.top))]
      assert.ok(positions.length >= 4, '至少四个不同滚动位置，不能把瞬移误报平滑动画')
      assert.ok(moving.some(frame => frame.chars > moving[0].chars && frame.state === 'streaming'), '动画进行时必须仍收到真实流式新字')
      await expect(page.getByTestId(replyTestId)).toHaveAttribute('data-state', 'done', { timeout: 90_000 })
      await expect.poll(distance).toBeLessThanOrEqual(1)
      await expect(page.getByRole('button', { name: /^(回到最新|有新回答)$/ })).toHaveCount(0)
      evidence.checks.push({ name: `${kind}/${mode}`, reply: replyTestId, distinctAnimationPositions: positions.length, streamingCharactersAddedDuringAnimation: Math.max(...moving.map(frame => frame.chars)) - moving[0].chars, finalDistance: await distance(), frames })
      console.log(`PASS ${kind}/${mode}: ${positions.length} distinct positions, streaming during real animation, at bottom`)
    }
    const calls = (await get(`/llm-calls?book_id=${id}&limit=100`)).items
    assert.ok(calls.every(call => call.model === 'demo'))
    evidence.demoCalls.push({ book: id, count: calls.length, models: [...new Set(calls.map(call => call.model))] })
  }
  assert.equal(evidence.checks.length, 4)
  assert.deepEqual(evidence.errors, [])
  evidence.complete = true
} catch (error) {
  evidence.failure = error.message
  throw error
} finally {
  await writeFile(output, JSON.stringify(evidence, null, 2))
  await browser.close()
}
