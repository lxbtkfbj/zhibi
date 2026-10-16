import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

// 独立演示页读取真实书结构；所有写请求在浏览器内截获，只验证前端完整列表补丁。
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const base = process.env.PREVIEW_BASE ?? 'http://127.0.0.1:4345'
const api = process.env.PREVIEW_API ?? 'http://127.0.0.1:8025/api'
const bookId = process.env.PREVIEW_BOOK ?? '857bb2ad-1dce-48d3-ac4f-7baf12d49b27'
const browserPath = process.env.CHROMIUM_PATH ?? 'C:/Users/cxc/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'
const original = await fetch(`${api}/books/${bookId}`, { signal: AbortSignal.timeout(20_000) }).then(response => response.json())
const originalWorld = structuredClone(original.world)
const browser = await chromium.launch({ executablePath: browserPath, headless: true })
const page = await browser.newPage({ viewport: { width: 1560, height: 1050 }, reducedMotion: 'reduce' })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const shots = []
const patches = []
const first = { name: '边界镇', powers: '作者原定商会', ceiling: '镇守', rules: '原定宵禁', start: '杂役', gains: '线索' }
const second = { name: '后来到过的京城', powers: '皇室', ceiling: '天师', rules: '原样保留', start: '客卿', gains: '卷宗' }
const far = [{ name: '远方海域', line: '作者先定的海岛' }, { name: '更远雪山', line: '后续原文不变' }]
const laterPower = '（第 2 段）筑基层级与代价\n（第 3 段）金丹层级与限制'
const mock = { ...original, world: { ...original.world, maps: [first, second], far_maps: far, power: `开局力量规则\n${laterPower}` } }
await page.route('**/api/**', async route => {
  const request = route.request()
  const pathname = new URL(request.url()).pathname
  if (pathname === `/api/books/${bookId}`) {
    if (request.method() === 'PATCH') {
      const patch = request.postDataJSON()
      patches.push(patch)
      assert.deepEqual(Object.keys(patch), ['world'])
      mock.world = { ...mock.world, ...patch.world }
    } else assert.equal(request.method(), 'GET')
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mock) })
  }
  if (!['GET', 'HEAD'].includes(request.method())) throw new Error(`阻止非模拟写入：${request.method()} ${pathname}`)
  return route.continue()
})

const edit = async (section, oldText, newText) => {
  const beforeCount = patches.length
  await page.locator(section).getByRole('button', { name: oldText, exact: true }).click()
  const editor = page.locator(section).getByRole('textbox', { name: '编辑文字' })
  await editor.fill(newText)
  await editor.press('Control+Enter')
  await expect(page.locator(section).getByRole('button', { name: newText, exact: true })).toBeVisible()
  assert.equal(patches.length, beforeCount + 1)
  return patches.at(-1)
}
const shot = async (section, name) => {
  const filename = `docs/第二包验收/任务3-世界编辑-${name}.png`
  await page.locator(section).screenshot({ path: path.join(root, filename) })
  shots.push(filename)
}

try {
  await page.goto(`${base}/books/${bookId}/world`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '第一张地图上谁说了算？', exact: true })).toBeVisible()
  assert.equal(await page.locator('#q-first_map').getByRole('button').count(), 6, '只有第一张地图可编辑')
  const mapPatch = await edit('#q-first_map', '边界镇', '作者改名后的边界镇')
  assert.deepEqual(mapPatch.world.maps, [{ ...first, name: '作者改名后的边界镇' }, second])
  await expect(page.locator('#q-first_map')).toContainText('后来到过的京城')
  await shot('#q-first_map', '地图列表保留')

  const farPatch = await edit('#q-shadows', '远方海域', '作者改名后的海域')
  assert.deepEqual(farPatch.world.far_maps, [{ ...far[0], name: '作者改名后的海域' }, far[1]])
  const farLinePatch = await edit('#q-shadows', '作者先定的海岛', '作者修改海域的一句话')
  assert.deepEqual(farLinePatch.world.far_maps, [{ name: '作者改名后的海域', line: '作者修改海域的一句话' }, far[1]])
  await shot('#q-shadows', '远图列表保留')

  const powerPatch = await edit('#q-power', '开局力量规则', '作者修改的开局规则')
  assert.deepEqual(powerPatch.world, { power: `作者修改的开局规则\n${laterPower}` })
  await expect(page.locator('#q-power')).toContainText(laterPower)
  assert.equal(await page.locator('#q-power').getByRole('button').count(), 1, '往上的层级只展示写作中追加的内容')
  await shot('#q-power', '后续层级保留')
  assert.deepEqual(errors, [])
  const after = await fetch(`${api}/books/${bookId}`, { signal: AbortSignal.timeout(20_000) }).then(response => response.json())
  assert.deepEqual(after.world, originalWorld, '真实演示书完全未被修改')
  const result = { passed: true, mode: '浏览器内模拟 PATCH；真实隔离书只读，未改变原数据', preview: base, api, bookId, checks: ['第一张地图单项编辑完整保存两张地图', '后来地图只读', '远图姓名与一句话分别编辑保留完整列表', '力量规则编辑保留第 2、3 段追加原文', '实际演示书 world 写前写后完全一致', '无浏览器运行时错误'], patches, screenshots: shots }
  await fs.mkdir(path.join(root, 'data/second-package-task3'), { recursive: true })
  await fs.writeFile(path.join(root, 'data/second-package-task3/world-boundaries.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
} finally {
  await browser.close()
}
