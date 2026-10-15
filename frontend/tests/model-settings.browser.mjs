/**
 * Isolated browser regression checks for model discovery and the settings form.
 * Start Vite first, then run: node tests/model-settings.browser.mjs
 * Uses an installed `playwright`; PLAYWRIGHT_MODULE can point to an existing
 * installation without adding a project dependency. Optional overrides:
 * TEST_BASE_URL, PLAYWRIGHT_CHROMIUM_EXECUTABLE, TEST_ARTIFACT_DIR.
 * TEST_GEOMETRY_BASELINE=1 captures pre-change measurements without assertions.
 * Every /api request is mocked: no real API keys/profiles are read or written.
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
})
const baseUrl = process.env.TEST_BASE_URL || 'http://127.0.0.1:4332'
const artifactDir = process.env.TEST_ARTIFACT_DIR
if (artifactDir) await mkdir(artifactDir, { recursive: true })

const MODEL_IDS = ['DeepSeek-chat', 'deepseek-reasoner', 'qwen-plus', 'claude-sonnet']
const savedProfile = {
  id: 'fixture-profile', name: 'Mock saved profile', provider: 'openai_compatible',
  base_url: 'https://fixture.invalid/v1', model: 'existing-custom-model',
  temperature: 0.8, max_tokens: null, structured_method: 'function_calling',
  timeout_s: 300, reasoning_effort: '', has_key: true,
}
let passed = 0

async function eventually(check, description) {
  let lastError
  const deadline = Date.now() + 5_000
  do {
    try { await check(); return } catch (error) { lastError = error }
    await new Promise((resolve) => setTimeout(resolve, 30))
  } while (Date.now() < deadline)
  throw new Error(`${description}: ${lastError?.message}`, { cause: lastError })
}

async function scenario(name, run, { profiles = [], viewport = { width: 1440, height: 1100 } } = {}) {
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.setDefaultTimeout(5_000)
  const state = {
    requests: [], saves: [], unexpected: [], pageErrors: [], completedDiscovery: 0,
    discovery: async () => ({ status: 200, json: { models: MODEL_IDS } }),
  }
  page.on('pageerror', (error) => state.pageErrors.push(error.message))
  await context.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    // Vite also serves source modules from /src/api/: never mock those modules.
    if (!path.startsWith('/api/')) { await route.continue(); return }
    if (method === 'GET' && path === '/api/books') {
      await route.fulfill({ json: [] }); return
    }
    if (method === 'GET' && path === '/api/llm/profiles') {
      await route.fulfill({ json: profiles }); return
    }
    if (method === 'GET' && path === '/api/llm/roles') {
      await route.fulfill({ json: { default: null, chief: null, lorekeeper: null, writer: null, reviewer: null } }); return
    }
    if (method === 'GET' && path === '/api/health') {
      await route.fulfill({ json: { status: 'ok', components: {} } }); return
    }
    if (method === 'POST' && path === '/api/llm/models') {
      state.requests.push(request.postDataJSON())
      const response = await state.discovery()
      // A changed endpoint/key may abort this request before the mock responds.
      await route.fulfill(response).catch(() => {})
      state.completedDiscovery += 1
      return
    }
    if ((method === 'POST' && path === '/api/llm/profiles') ||
        (method === 'PATCH' && path === `/api/llm/profiles/${savedProfile.id}`)) {
      const body = request.postDataJSON()
      state.saves.push(body)
      await route.fulfill({ json: { ...savedProfile, ...body, has_key: Boolean(body.api_key) } }); return
    }
    state.unexpected.push(`${method} ${path}`)
    await route.fulfill({ status: 500, json: { detail: 'Unexpected API request blocked by test' } })
  })
  try {
    await page.goto(`${baseUrl}/settings`)
    if (profiles.length) {
      await page.locator('.settings-row-label').filter({ hasText: new RegExp(`^${savedProfile.name}$`) }).waitFor()
    } else {
      await page.getByRole('button', { name: '＋ 添加', exact: true }).click()
      await page.getByRole('dialog', { name: '设置', exact: true }).waitFor()
      assert.equal(await page.getByRole('dialog').count(), 1, 'Model form stays inside the only settings dialog')
      await settleDialog(page)
    }
    await run(page, state)
    assert.deepEqual(state.unexpected, [], 'All API calls must be explicitly mocked')
    assert.deepEqual(state.pageErrors, [], 'No uncaught browser errors')
    passed += 1
    console.log(`PASS ${name}`)
  } catch (error) {
    if (artifactDir) await page.screenshot({ path: join(artifactDir, `failure-${passed + 1}.png`), fullPage: true }).catch(() => {})
    throw new Error(`FAIL ${name}: ${error.message}${state.pageErrors.length ? `\nBrowser errors: ${state.pageErrors.join('; ')}` : ''}`, { cause: error })
  } finally {
    await context.close()
  }
}

const dialog = (page) => page.getByRole('dialog')
const modelInput = (page) => dialog(page).getByRole('combobox', { name: '模型名', exact: true })
const fetchButton = (page) => dialog(page).getByRole('button', { name: /获取模型列表|刷新模型列表|重新获取|正在获取/ })
const options = (page) => dialog(page).getByRole('listbox', { name: '可用模型' }).getByRole('option')
const field = (page, name) => dialog(page).getByLabel(name)
const keyToggle = (page, visible) => dialog(page).getByRole('button', { name: visible ? /隐藏.*API Key/ : /显示.*API Key/ })

async function settleDialog(page) {
  await eventually(async () => {
    assert.equal(await dialog(page).evaluate((element) => getComputedStyle(element).opacity), '1')
    assert.equal(await dialog(page).evaluate((element) => getComputedStyle(element.parentElement).opacity), '1')
  }, 'Modal opening animation completed')
}

async function fillConnection(page) {
  await field(page, '模型配置名称').fill('Browser fixture')
  await field(page, /^接口地址/).fill('https://fixture.invalid/v1')
  await field(page, /^API Key/).fill('fake-key-for-mocked-requests')
}

async function fetchModels(page, state) {
  const before = state.requests.length
  await fetchButton(page).click()
  await eventually(() => assert.equal(state.requests.length, before + 1), 'Model discovery request sent')
  await eventually(async () => assert.equal(await fetchButton(page).isEnabled(), true), 'Discovery finished')
}

async function assertOptions(page, expected) {
  await eventually(async () => assert.deepEqual(await options(page).allTextContents(), expected), 'Visible model options')
}

async function formGeometry(page) {
  return {
    dialog: await dialog(page).boundingBox(),
    header: await dialog(page).locator(':scope > header').boundingBox(),
    footer: await dialog(page).locator('.settings-profile-form > div').last().boundingBox(),
    apiKey: await field(page, /^API Key/).boundingBox(),
    model: await modelInput(page).boundingBox(),
    fetch: await fetchButton(page).boundingBox(),
    save: await dialog(page).getByRole('button', { name: '保存', exact: true }).boundingBox(),
    scroll: await dialog(page).locator('.settings-modal-content').evaluate((element) => ({ top: element.scrollTop, height: element.clientHeight, content: element.scrollHeight })),
  }
}

function assertGeometryStable(before, after, phase, allowInnerScroll = false) {
  for (const name of ['dialog', 'header', 'apiKey', 'model', 'fetch']) {
    for (const dimension of ['x', 'y', 'width', 'height']) {
      const scrollCorrection = allowInnerScroll && dimension === 'y' && ['apiKey', 'model', 'fetch'].includes(name)
        ? after.scroll.top - before.scroll.top : 0
      assert.ok(Math.abs(before[name][dimension] - after[name][dimension] - scrollCorrection) <= 1,
        `${phase}: ${name}.${dimension} moved from ${before[name][dimension]} to ${after[name][dimension]}`)
    }
  }
}

if (process.env.TEST_GEOMETRY_BASELINE) {
  const captures = []
  try {
    for (const viewport of [{ width: 727, height: 799 }, { width: 686, height: 993 }, { width: 390, height: 844 }]) {
      for (const advanced of [false, true]) {
        await scenario(`baseline geometry ${viewport.width} advanced=${advanced}`, async (page, state) => {
          let release
          state.discovery = () => new Promise((resolve) => { release = resolve })
          await fillConnection(page)
          // Advanced parameters are always visible in the unified settings list.
          await fetchButton(page).scrollIntoViewIfNeeded()
          const before = await formGeometry(page)
          await fetchButton(page).hover()
          await page.mouse.down()
          await page.waitForTimeout(200)
          const down = await formGeometry(page)
          await page.mouse.up()
          await eventually(() => assert.equal(state.requests.length, 1), 'Baseline fetch started')
          await page.waitForTimeout(200)
          const pending = await formGeometry(page)
          release({ status: 404, json: { detail: 'Not Found' } })
          await eventually(async () => assert.equal(await fetchButton(page).isEnabled(), true), 'Baseline fetch finished')
          await page.waitForTimeout(200)
          const error = await formGeometry(page)
          captures.push({ viewport, advanced, before, down, pending, error })
          if (artifactDir) await page.screenshot({ path: join(artifactDir, `baseline-404-${viewport.width}-${advanced ? 'advanced' : 'collapsed'}.png`), fullPage: true })
        }, { viewport })
      }
    }
    console.log(JSON.stringify(captures, null, 2))
    if (artifactDir) await writeFile(join(artifactDir, 'baseline-geometry.json'), JSON.stringify(captures, null, 2))
  } finally { await browser.close() }
  process.exit(0)
}

try {
  await scenario('fetch, case-insensitive substring filter, click and keyboard selection', async (page, state) => {
    assert.equal(await fetchButton(page).isDisabled(), true, 'Endpoint is required before discovery')
    await fillConnection(page)
    await fetchModels(page, state)
    assert.equal(state.requests[0].base_url, 'https://fixture.invalid/v1')
    assert.equal(state.requests[0].api_key, 'fake-key-for-mocked-requests')
    await modelInput(page).fill('DEEP')
    await assertOptions(page, MODEL_IDS.slice(0, 2))
    await options(page).filter({ hasText: /^deepseek-reasoner$/ }).click()
    assert.equal(await modelInput(page).inputValue(), 'deepseek-reasoner')
    await modelInput(page).fill('qWeN')
    await assertOptions(page, ['qwen-plus'])
    await modelInput(page).press('ArrowDown')
    await modelInput(page).press('Enter')
    assert.equal(await modelInput(page).inputValue(), 'qwen-plus')
    assert.equal(state.saves.length, 0, 'Selecting a model must not save the profile')
    await modelInput(page).fill('deep')
    await assertOptions(page, MODEL_IDS.slice(0, 2))
    await modelInput(page).press('Escape')
    assert.equal(await modelInput(page).getAttribute('aria-expanded'), 'false')
    assert.equal(await dialog(page).isVisible(), true, 'Escape dismisses the list, not the whole modal')
  })

  await scenario('custom model can be saved without fetching', async (page, state) => {
    await fillConnection(page)
    await modelInput(page).fill('my-private-model:latest')
    await dialog(page).getByRole('button', { name: '保存', exact: true }).click()
    await eventually(() => assert.equal(state.saves.length, 1), 'Mock save completed')
    assert.equal(state.saves[0].model, 'my-private-model:latest')
    assert.equal(state.requests.length, 0)
  })

  await scenario('custom unmatched model remains savable after discovery', async (page, state) => {
    await fillConnection(page)
    await fetchModels(page, state)
    await modelInput(page).fill('provider/custom-v2')
    await assertOptions(page, [])
    await dialog(page).getByRole('button', { name: '保存', exact: true }).click()
    await eventually(() => assert.equal(state.saves.length, 1), 'Mock custom save completed')
    assert.equal(state.saves[0].model, 'provider/custom-v2')
  })

  for (const mode of ['empty', 'error']) {
    await scenario(`${mode} discovery preserves manual input and save`, async (page, state) => {
      state.discovery = async () => mode === 'empty'
        ? { status: 200, json: { models: [] } }
        : { status: 502, json: { detail: 'Mock discovery unavailable' } }
      await fillConnection(page)
      await modelInput(page).fill('manual-before-fetch')
      await fetchModels(page, state)
      assert.equal(await modelInput(page).inputValue(), 'manual-before-fetch')
      if (mode === 'error') await dialog(page).getByText('Mock discovery unavailable', { exact: false }).waitFor()
      await modelInput(page).fill('manual-after-fetch')
      await dialog(page).getByRole('button', { name: '保存', exact: true }).click()
      await eventually(() => assert.equal(state.saves.length, 1), 'Manual fallback saved')
      assert.equal(state.saves[0].model, 'manual-after-fetch')
    })
  }

  for (const connectionField of ['接口地址', 'API Key']) {
    await scenario(`changing ${connectionField} invalidates fetched options without losing manual model`, async (page, state) => {
      await fillConnection(page)
      await fetchModels(page, state)
      await modelInput(page).fill('DEEP')
      await assertOptions(page, MODEL_IDS.slice(0, 2))
      await field(page, new RegExp(`^${connectionField}`)).fill(connectionField === '接口地址' ? 'https://new.invalid/v1' : 'fake-replacement-key')
      await modelInput(page).click()
      assert.equal(await modelInput(page).inputValue(), 'DEEP')
      await assertOptions(page, [])
    })
  }

  await scenario('in-flight response cannot repopulate options after connection changes', async (page, state) => {
    let release
    state.discovery = () => new Promise((resolve) => { release = resolve })
    await fillConnection(page)
    await fetchButton(page).click()
    await eventually(() => assert.equal(state.requests.length, 1), 'Delayed request started')
    assert.equal(await fetchButton(page).isDisabled(), true, 'Duplicate fetches blocked while loading')
    await field(page, /^接口地址/).fill('https://new.invalid/v1')
    await field(page, /^API Key/).fill('fake-new-key')
    release({ status: 200, json: { models: ['stale-model'] } })
    await modelInput(page).fill('stale')
    await assertOptions(page, [])
    state.discovery = async () => ({ status: 200, json: { models: ['new-provider-model'] } })
    await fetchModels(page, state)
    await modelInput(page).fill('new-provider')
    await assertOptions(page, ['new-provider-model'])
    assert.equal(state.requests.at(-1).base_url, 'https://new.invalid/v1')
    assert.equal(state.requests.at(-1).api_key, 'fake-new-key')
  })

  await scenario('saved profile discovery sends profile id without exposing saved key', async (page, state) => {
    const row = page.locator('.settings-row').filter({ has: page.locator('.settings-row-label').filter({ hasText: new RegExp(`^${savedProfile.name}$`) }) })
    await row.getByRole('button').nth(1).click()
    await dialog(page).waitFor()
    assert.equal(await field(page, /^API Key/).inputValue(), '')
    assert.equal(await modelInput(page).inputValue(), savedProfile.model)
    await fetchModels(page, state)
    assert.equal(state.requests[0].profile_id, savedProfile.id)
    assert.equal(state.requests[0].api_key, '')
    assert.equal(await modelInput(page).inputValue(), savedProfile.model, 'Fetch must not silently replace the current model')
  }, { profiles: [savedProfile] })

  await scenario('A to B to A connection changes do not revive loading or a stale response', async (page, state) => {
    let release
    state.discovery = () => new Promise((resolve) => { release = resolve })
    await fillConnection(page)
    await fetchButton(page).click()
    await eventually(() => assert.equal(state.requests.length, 1), 'Connection A request started')
    await field(page, /^接口地址/).fill('https://temporary-b.invalid/v1')
    await field(page, /^接口地址/).fill('https://fixture.invalid/v1')
    await eventually(async () => assert.equal(await fetchButton(page).isEnabled(), true), 'Restoring A permits a fresh request')
    state.discovery = async () => ({ status: 200, json: { models: ['fresh-A-model'] } })
    await fetchModels(page, state)
    await modelInput(page).fill('')
    await assertOptions(page, ['fresh-A-model'])
    release({ status: 200, json: { models: ['stale-A-model'] } })
    await eventually(() => assert.equal(state.completedDiscovery, 2), 'Older response delivered after the newer response')
    await assertOptions(page, ['fresh-A-model'])
  })

  for (const viewport of [{ width: 686, height: 993 }, { width: 390, height: 844 }]) {
    await scenario(`long list bottom model remains reachable at ${viewport.width}px`, async (page, state) => {
      const longList = Array.from({ length: 30 }, (_, index) => `mock-model-${String(index + 1).padStart(2, '0')}`)
      state.discovery = async () => ({ status: 200, json: { models: longList } })
      await fillConnection(page)
      await fetchModels(page, state)
      await assertOptions(page, longList)
      await eventually(async () => {
        const geometry = await dialog(page).getByRole('listbox', { name: '可用模型' }).evaluate((list) => {
          const popup = list.parentElement
          let scrollport = popup.parentElement
          while (scrollport && getComputedStyle(scrollport).overflowY !== 'auto') scrollport = scrollport.parentElement
          if (!scrollport) throw new Error('Model list needs a scrollable modal body')
          const bounds = popup.getBoundingClientRect()
          const visible = scrollport.getBoundingClientRect()
          return { top: bounds.top, bottom: bounds.bottom, visibleTop: visible.top, visibleBottom: visible.bottom }
        })
        assert.ok(geometry.top >= geometry.visibleTop - 1, 'Opened model list starts within the visible modal body')
        assert.ok(geometry.bottom <= geometry.visibleBottom + 1, 'Opened model list is not clipped by the save footer')
      }, 'Initial model list fits the scrollable modal body')
      if (artifactDir) await page.screenshot({ path: join(artifactDir, `list-initial-${viewport.width}.png`), fullPage: true })
      const last = options(page).last()
      await last.scrollIntoViewIfNeeded()
      if (artifactDir) await page.screenshot({ path: join(artifactDir, `list-bottom-${viewport.width}.png`), fullPage: true })
      await last.click()
      assert.equal(await modelInput(page).inputValue(), 'mock-model-30')
      assert.equal(state.saves.length, 0)
    }, { viewport })
  }

  for (const viewport of [{ width: 1440, height: 1100 }, { width: 686, height: 993 }, { width: 390, height: 844 }]) {
    await scenario(`advanced fields align at ${viewport.width}px`, async (page) => {
      // No separate accordion or nested card: advanced parameters are settings rows.
      const names = [/^温度/, /^最大输出 token/, /^结构化输出方式/, /^推理强度/, /^超时/]
      const boxes = []
      for (const name of names) {
        const box = await field(page, name).boundingBox()
        assert.ok(box, `${name} is rendered`)
        boxes.push(box)
      }
      for (let index = 0; index < boxes.length; index += 1) {
        assert.ok(Math.abs(boxes[index].height - 28) < 2, 'All settings controls are 28px high')
        if (index > 0) {
          assert.ok(boxes[index].y >= boxes[index - 1].y + boxes[index - 1].height, 'Settings controls stack without overlap')
          assert.ok(Math.abs(boxes[index].x + boxes[index].width - boxes[0].x - boxes[0].width) < 2, 'Settings controls share their right edge')
        }
      }
      const dialogBox = await dialog(page).boundingBox()
      assert.ok(dialogBox.x >= -1 && dialogBox.x + dialogBox.width <= viewport.width + 1, 'Dialog fits viewport horizontally')
      assert.equal(await dialog(page).evaluate((element) => element.scrollWidth <= element.clientWidth + 1), true, 'No horizontal dialog overflow')
      await field(page, /^推理强度/).scrollIntoViewIfNeeded()
      await settleDialog(page)
      if (artifactDir) await page.screenshot({ path: join(artifactDir, `advanced-${viewport.width}.png`), fullPage: true })
    }, { viewport })
  }

  await scenario('API key eye defaults hidden and toggles without mutating typed value or model list', async (page, state) => {
    const key = field(page, /^API Key/)
    assert.equal(await key.getAttribute('type'), 'password')
    await fillConnection(page)
    const original = await key.inputValue()
    const before = await key.boundingBox()
    await keyToggle(page, false).click()
    assert.equal(await key.getAttribute('type'), 'text')
    assert.equal(await key.inputValue(), original)
    assert.deepEqual(await key.boundingBox(), before, 'Eye toggle does not resize or move the input')
    await keyToggle(page, true).click()
    assert.equal(await key.getAttribute('type'), 'password')
    assert.equal(await key.inputValue(), original)
    await fetchModels(page, state)
    await keyToggle(page, false).click()
    await modelInput(page).fill('deep')
    await assertOptions(page, MODEL_IDS.slice(0, 2))
    assert.equal(state.requests.length, 1, 'Visibility does not trigger another network request')
    assert.equal(state.saves.length, 0, 'Visibility never saves the profile')
    await dialog(page).getByRole('button', { name: '取消', exact: true }).click()
    await page.getByRole('button', { name: '＋ 添加', exact: true }).click()
    assert.equal(await field(page, /^API Key/).getAttribute('type'), 'password', 'Reopening resets to hidden')
  })

  await scenario('saved key eye never exposes or fetches the stored secret', async (page, state) => {
    const row = page.locator('.settings-row').filter({ has: page.locator('.settings-row-label').filter({ hasText: new RegExp(`^${savedProfile.name}$`) }) })
    await row.getByRole('button').nth(1).click()
    await settleDialog(page)
    const key = field(page, /^API Key/)
    assert.equal(await key.getAttribute('type'), 'password')
    assert.equal(await key.inputValue(), '')
    assert.equal(await keyToggle(page, false).isDisabled(), true, 'Empty saved-key input cannot reveal a server-side secret')
    assert.equal(await key.inputValue(), '', 'Stored credential remains server-side; only the placeholder is present')
    assert.equal(await key.getAttribute('type'), 'password')
    assert.equal(await key.inputValue(), '')
    assert.equal(state.requests.length, 0)
    assert.equal(state.saves.length, 0)
    await fetchModels(page, state)
    assert.equal(state.requests[0].profile_id, savedProfile.id)
    assert.equal(state.requests[0].api_key, '')
  }, { profiles: [savedProfile] })

  await scenario('local Not Found explains stale backend and restart while preserving manual input', async (page, state) => {
    state.discovery = async () => ({ status: 404, json: { detail: 'Not Found' } })
    await fillConnection(page)
    await modelInput(page).fill('manual-fallback-model')
    await fetchModels(page, state)
    const text = await dialog(page).innerText()
    assert.match(text, /后端/, 'Local application route absence is identified as a backend problem')
    assert.match(text, /重启/, 'User gets an actionable restart instruction')
    assert.match(text, /手动|直接填写/, 'Manual model entry remains an available fallback')
    assert.equal(await modelInput(page).inputValue(), 'manual-fallback-model')
    assert.equal(await dialog(page).getByText('Not Found', { exact: true }).count(), 0, 'Raw Not Found is not the only explanation')
    if (artifactDir) await page.screenshot({ path: join(artifactDir, 'local-404-diagnosis.png'), fullPage: true })
  })

  await scenario('upstream discovery failure does not claim the local backend route is missing', async (page, state) => {
    const upstreamMessage = '模型服务未提供模型列表接口（HTTP 404），请检查接口地址，或手动填写模型名。'
    state.discovery = async () => ({ status: 502, json: { detail: upstreamMessage } })
    await fillConnection(page)
    await fetchModels(page, state)
    await dialog(page).getByText(upstreamMessage, { exact: false }).waitFor()
    assert.doesNotMatch(await dialog(page).innerText(), /重启/, 'Upstream provider failure is not mislabeled as a local backend upgrade issue')
    await modelInput(page).fill('upstream-manual-fallback')
    assert.equal(await modelInput(page).inputValue(), 'upstream-manual-fallback')
  })

  for (const viewport of [{ width: 727, height: 799 }, { width: 686, height: 993 }, { width: 390, height: 844 }]) {
    for (const advanced of [false, true]) {
      await scenario(`discovery does not displace dialog or controls at ${viewport.width}px advanced=${advanced}`, async (page, state) => {
        await fillConnection(page)
        // Advanced parameters are always visible in the unified settings list.
        await fetchButton(page).scrollIntoViewIfNeeded()
        const initial = await formGeometry(page)
        const measurements = [{ phase: 'initial', geometry: initial }]
        let allowInnerScroll = false
        for (const [phase, response] of [
          ['local-404', { status: 404, json: { detail: 'Not Found' } }],
          ['empty-success', { status: 200, json: { models: [] } }],
          ['models-success', { status: 200, json: { models: MODEL_IDS } }],
          ['retry-error', { status: 502, json: { detail: '测试服务暂不可用，请稍后重试或继续手动填写模型名。' } }],
        ]) {
          let release
          state.discovery = () => new Promise((resolve) => { release = resolve })
          const beforeCount = state.requests.length
          await fetchButton(page).hover()
          await page.mouse.down()
          await page.waitForTimeout(180)
          assertGeometryStable(initial, await formGeometry(page), `${phase} pointer down`, allowInnerScroll)
          await page.mouse.up()
          await eventually(() => assert.equal(state.requests.length, beforeCount + 1), `${phase} request started`)
          assert.equal(await fetchButton(page).isDisabled(), true)
          await page.waitForTimeout(180)
          const pending = await formGeometry(page)
          assertGeometryStable(initial, pending, `${phase} pending`, allowInnerScroll)
          release(response)
          await eventually(async () => assert.equal(await fetchButton(page).isEnabled(), true), `${phase} response arrived`)
          await page.waitForTimeout(180)
          const settled = await formGeometry(page)
          // Opening a nonempty list may intentionally scroll the inner form to
          // make its options visible; content coordinates and outer frame stay fixed.
          if (phase === 'models-success') allowInnerScroll = true
          assertGeometryStable(initial, settled, `${phase} settled`, allowInnerScroll)
          measurements.push({ phase: `${phase}-pending`, geometry: pending }, { phase, geometry: settled })
          if (artifactDir) await page.screenshot({ path: join(artifactDir, `stable-${viewport.width}-${advanced ? 'advanced' : 'collapsed'}-${phase}.png`), fullPage: true })
        }
        if (artifactDir) await writeFile(join(artifactDir, `stable-geometry-${viewport.width}-${advanced ? 'advanced' : 'collapsed'}.json`), JSON.stringify(measurements, null, 2))
      }, { viewport })
    }
  }
  console.log(`\n${passed} model settings browser regression checks passed.`)
} finally {
  await browser.close()
}
