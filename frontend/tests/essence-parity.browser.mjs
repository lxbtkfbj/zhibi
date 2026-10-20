import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import pixelmatch from 'pixelmatch'
import { PNG } from 'pngjs'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { createHash } from 'node:crypto'
import { pathToFileURL } from 'node:url'

// Real isolated API data. No route fulfills, DOM replacements, CSS overrides,
// masks, or per-view discrepancy allowances are used by this comparison.
const ROOT = path.resolve(import.meta.dirname, '../..')
const BASE = process.env.ZHIBI_DESK_URL ?? 'http://127.0.0.1:4351'
const API = process.env.ZHIBI_DESK_API ?? 'http://127.0.0.1:8051/api'
const BOOK = process.env.ZHIBI_DESK_BOOK ?? 'ff4aff0b-d1f1-46c4-b120-f7da9ac1ec2a'
const OUT = path.resolve(ROOT, process.env.ZHIBI_PARITY_OUT ?? 'docs/拆书精髓验收/页面比对')
const SAMPLE = path.join(ROOT, 'docs/界面原型/精髓样张.html')
const DATA = path.join(ROOT, 'docs/界面原型/精髓样张-数据.js')
const KEYS = ['overview', 'source', 'skeleton', 'link', 'fresh', 'longline', 'setting', 'shuang', 'scene', 'hero', 'cast', 'rhythm', 'opening']
const VIEWS = ['简介', ...KEYS.map(key => `精髓-${key}`)]
const SIZES = process.env.ZHIBI_PARITY_SIZE ? [process.env.ZHIBI_PARITY_SIZE.split('x').map(Number)] : [[1600, 900], [2560, 1312]]
const views = process.env.ZHIBI_PARITY_VIEW ? process.env.ZHIBI_PARITY_VIEW.split(',') : VIEWS
assert.ok(views.every(view => VIEWS.includes(view)), '只比任务规定的 14 页')
const props = ['font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing', 'color', 'background-color', 'background-image', ...['top', 'right', 'bottom', 'left'].flatMap(s => [`border-${s}-width`, `border-${s}-style`, `border-${s}-color`]), ...['top-left', 'top-right', 'bottom-right', 'bottom-left'].map(c => `border-${c}-radius`), ...['top', 'right', 'bottom', 'left'].map(s => `padding-${s}`), ...['top', 'right', 'bottom', 'left'].map(s => `margin-${s}`), 'box-shadow', 'width', 'height', 'display', 'gap', 'grid-template-columns']
assert.equal(props.length, 38)
fs.mkdirSync(OUT, { recursive: true })
const json = async suffix => {
  const response = await fetch(`${API}/books/${BOOK}${suffix}`)
  if (!response.ok) throw new Error(`${suffix}: ${response.status}`)
  return response.json()
}
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value
const sha = value => createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(canonical(value))).digest('hex')
const dataContext = { window: {} }
vm.runInNewContext(fs.readFileSync(DATA, 'utf8'), dataContext, { filename: DATA })
const fixture = JSON.parse(JSON.stringify(dataContext.window.DATA))
const [book, tree, essenceResponse, saves] = await Promise.all([json(''), json('/outline-tree'), json('/teardown/essence'), json('/saves?limit=1')])
const essence = essenceResponse.essence
const units = tree.arcs.flatMap(arc => arc.volumes).flatMap(volume => volume.units).filter(unit => !unit.virtual)
const actualBook = { title: book.title, author: book.teardown?.author, chapters: book.teardown?.chapters, read: book.teardown?.read, intro: book.teardown?.intro, units: units.length }
assert.deepEqual(actualBook, fixture.book, '验收副本的书名、作者、章数、已读、简介和单元数必须等于样张')
assert.ok(essence, '验收副本必须写入精髓样张的数据')
for (const key of ['upto', 'overview', 'sections', 'rails']) assert.deepEqual(canonical(essence[key]), canonical(fixture.essence[key]), `精髓 ${key} 必须原样写入真实 API`)
assert.ok(saves.items[0]?.created_at, '验收副本必须有真实存档，才能固定浏览器时钟')
const clock = { latestSaveAt: saves.items[0].created_at, fixedAt: new Date(new Date(saves.items[0].created_at).getTime() + 8 * 60_000).toISOString() }
const executablePath = process.env.ZHIBI_CHROMIUM ?? ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Users/cxc/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe'].find(fs.existsSync)
const browser = await chromium.launch({ executablePath })
const results = [], errors = [], blockedWrites = [], externalRequests = []
let currentCase = null
function same(a, b) {
  if (a === b) return true
  // Exactly the old comparison: only px lengths can vary by 0.5 CSS px.
  const tokens = s => s.match(/-?\d*\.?\d+px/g) ?? []
  const aa = tokens(a), bb = tokens(b)
  return aa.length > 0 && aa.length === bb.length && a.replace(/-?\d*\.?\d+px/g, '#') === b.replace(/-?\d*\.?\d+px/g, '#') && aa.every((n, i) => Math.abs(parseFloat(n) - parseFloat(bb[i])) <= .5)
}
const computed = page => page.evaluate(props => {
  const root = document.querySelector('.desk-v2') ?? document.body
  const elements = [...root.querySelectorAll('[class]')]
  const classes = [...new Set(elements.flatMap(element => [...element.classList]))]
  return Object.fromEntries(classes.map(cls => {
    const style = getComputedStyle(elements.find(element => element.classList.contains(cls)))
    return [cls, Object.fromEntries(props.map(property => [property, style.getPropertyValue(property)]))]
  }))
}, props)
const text = page => page.evaluate(() => ({ page: document.querySelector('.page').innerText, rail: document.querySelector('.rail')?.innerText ?? '' }))
const structure = page => page.evaluate(() => {
  const root = document.querySelector('.desk-v2') ?? document.body
  const rect = element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height } }
  return {
    visibleText: root.innerText,
    top: root.querySelector('.top')?.innerText ?? '',
    tabs: [...root.querySelectorAll('.tabs a')].map(element => ({ text: element.innerText, active: element.classList.contains('on') })),
    toc: root.querySelector('.toc')?.innerText ?? '',
    search: [...root.querySelectorAll('.search')].map(element => ({ text: element.innerText, placeholder: element.querySelector('input')?.placeholder ?? null })),
    rows: [...root.querySelectorAll('.toc .row')].map(element => ({ text: element.innerText, classes: element.className, rect: rect(element) })),
    footer: root.querySelector('.toc-foot')?.innerText ?? '',
    ball: root.querySelector('.ball') ? { text: root.querySelector('.ball').innerText, rect: rect(root.querySelector('.ball')) } : null,
    zoom: getComputedStyle(root).zoom,
  }
})
try {
  for (const [width, height] of SIZES) for (const view of views) {
    currentCase = { view, width, height }
    const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: 'light' })
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { blockedWrites.push({ view, width, method: request.method(), path: url.pathname }); return route.abort('blockedbyclient') }
      if (url.protocol.startsWith('http') && !['127.0.0.1', 'localhost'].includes(url.hostname)) { externalRequests.push({ view, width, url: url.origin + url.pathname }); return route.abort('blockedbyclient') }
      return route.continue()
    })
    const sample = await context.newPage(), actual = await context.newPage()
    for (const page of [sample, actual]) {
      page.on('pageerror', error => errors.push({ view, width, error: String(error) }))
      await page.clock.setFixedTime(new Date(clock.fixedAt))
    }
    await sample.goto(pathToFileURL(SAMPLE).href + '#' + encodeURIComponent(view), { waitUntil: 'domcontentloaded' })
    const position = { tab: view === '简介' ? '简介' : '精髓', essence: view === '简介' ? 'overview' : view.slice('精髓-'.length), entry: 'overview', node: 'book', chapter: 'home', open: [] }
    await actual.addInitScript(({ book, position }) => {
      localStorage.removeItem('zhibi.ball')
      localStorage.setItem('zhibi:editorial-dock', 'ball')
      localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 }))
      sessionStorage.setItem('zhibi:workspace-reading:' + book, JSON.stringify(position))
    }, { book: BOOK, position })
    await actual.goto(`${BASE}/desk/${BOOK}`, { waitUntil: 'domcontentloaded' })
    await actual.locator('.desk-v2 .page h1').waitFor()
    await Promise.all([sample.evaluate(() => document.fonts.ready), actual.evaluate(() => document.fonts.ready)])
    await actual.waitForTimeout(750)
    const [a, b, ta, tb, sampleStructure, actualStructure] = await Promise.all([computed(sample), computed(actual), text(sample), text(actual), structure(sample), structure(actual)])
    const domChecks = {
      tabs: JSON.stringify(sampleStructure.tabs) === JSON.stringify(actualStructure.tabs),
      tocRowsText: JSON.stringify(sampleStructure.rows.map(row => row.text)) === JSON.stringify(actualStructure.rows.map(row => row.text)),
      archive: sampleStructure.footer === actualStructure.footer,
      zoom: sampleStructure.zoom === actualStructure.zoom,
      ballText: sampleStructure.ball?.text === actualStructure.ball?.text,
      ballBounds: JSON.stringify(sampleStructure.ball?.rect) === JSON.stringify(actualStructure.ball?.rect),
      searchLabel: sampleStructure.search.length === actualStructure.search.length && sampleStructure.search.every((search, index) => search.text === (actualStructure.search[index].placeholder ?? actualStructure.search[index].text)),
    }
    const rows = []
    for (const [cls, values] of Object.entries(a)) for (const [property, expected] of Object.entries(values)) rows.push({ class: cls, property, expected, actual: b[cls]?.[property] ?? '(missing class)', same: b[cls] !== undefined && same(expected, b[cls][property]) })
    const prefix = `${width}x${height}-${view}`
    const sa = PNG.sync.read(await sample.screenshot()), sb = PNG.sync.read(await actual.screenshot())
    fs.writeFileSync(path.join(OUT, prefix + '-样张.png'), PNG.sync.write(sa))
    fs.writeFileSync(path.join(OUT, prefix + '-页面.png'), PNG.sync.write(sb))
    const diff = new PNG({ width, height })
    const pixels = pixelmatch(sa.data, sb.data, diff.data, width, height, { threshold: .1, diffColor: [255, 0, 0] })
    fs.writeFileSync(path.join(OUT, prefix + '-差异.png'), PNG.sync.write(diff))
    const styleFailures = rows.filter(row => !row.same)
    const result = { view, width, height, classes: Object.keys(a).length, rows, styleFailures, unexplainedStyleFailures: styleFailures, text: { sample: ta, actual: tb, same: ta.page === tb.page && ta.rail === tb.rail }, structure: { sample: sampleStructure, actual: actualStructure }, domChecks, masks: [], pixels, pixelPercent: pixels / (width * height) * 100, pixelPass: pixels / (width * height) <= .005 }
    fs.writeFileSync(path.join(OUT, prefix + '.json'), JSON.stringify(result, null, 2))
    results.push(result)
    console.log(`${prefix}: ${styleFailures.length}/${rows.length} style differences; text=${result.text.same}; pixels=${result.pixelPercent.toFixed(4)}%`)
    await context.close()
  }
} catch (error) {
  errors.push({ ...currentCase, error: String(error), stack: error.stack })
} finally { await browser.close() }
fs.writeFileSync(path.join(OUT, 'parity-summary.json'), JSON.stringify({ at: new Date().toISOString(), base: BASE, api: API, book: BOOK, data: { book: actualBook, essenceSha256: sha(fixture.essence), sampleSha256: sha(fs.readFileSync(SAMPLE, 'utf8')), fixtureSha256: sha(fs.readFileSync(DATA, 'utf8')) }, clock, textScope: ['page.innerText', 'rail.innerText'], computedProperties: props, threshold: .1, allowedPixelPercent: .5, lengthTolerancePx: .5, masks: [], errors, blockedWrites, externalRequests, results: results.map(({ rows: _rows, styleFailures, text, structure: _structure, ...result }) => ({ ...result, styleFailures: styleFailures.length, textSame: text.same })) }, null, 2))
fs.writeFileSync(path.join(OUT, 'DOM结构核验.json'), JSON.stringify({ policy: '额外 DOM 审计：顶栏标签、目录行文字和数字、存档、zoom、印章文字及坐标；样张搜索文字对应真实 input placeholder。完整 top/toc 的未归一化文字仍记录在各组 structure 中；不修改 DOM、不遮挡。', passed: results.every(result => Object.values(result.domChecks).every(Boolean)), groups: results.map(({ view, width, height, domChecks }) => ({ view, width, height, checks: domChecks })) }, null, 2))
if (errors.length || blockedWrites.length || externalRequests.length) throw new Error(JSON.stringify({ errors, blockedWrites, externalRequests }))
if (!process.env.ZHIBI_PARITY_DIAGNOSTIC && results.some(result => result.unexplainedStyleFailures.length || !result.text.same || !result.pixelPass)) process.exitCode = 1
