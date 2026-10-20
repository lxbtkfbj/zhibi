import { chromium } from 'playwright'
import pixelmatch from 'pixelmatch'
import { PNG } from 'pngjs'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

// Real API data only: the UI is neither mocked nor replaced with the prototype.
const ROOT = path.resolve(import.meta.dirname, '../..')
const BASE = process.env.ZHIBI_DESK_URL ?? 'http://127.0.0.1:4351'
const API = process.env.ZHIBI_DESK_API ?? 'http://127.0.0.1:8051/api'
const BOOK = process.env.ZHIBI_DESK_BOOK ?? 'ff4aff0b-d1f1-46c4-b120-f7da9ac1ec2a'
const OUT = path.resolve(ROOT, process.env.ZHIBI_PARITY_OUT ?? 'docs/新书页装修验收')
const VIEWS = ['设定', '茉莉', '卷', '单元', '章', '章-没拆', '正文', '读']
const SIZES = process.env.ZHIBI_PARITY_SIZE ? [process.env.ZHIBI_PARITY_SIZE.split('x').map(Number)] : [[2560, 1312], [1600, 900]]
const views = process.env.ZHIBI_PARITY_VIEW ? process.env.ZHIBI_PARITY_VIEW.split(',') : VIEWS
const props = ['font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing', 'color', 'background-color', 'background-image', ...['top', 'right', 'bottom', 'left'].flatMap(s => [`border-${s}-width`, `border-${s}-style`, `border-${s}-color`]), ...['top-left', 'top-right', 'bottom-right', 'bottom-left'].map(c => `border-${c}-radius`), ...['top', 'right', 'bottom', 'left'].map(s => `padding-${s}`), ...['top', 'right', 'bottom', 'left'].map(s => `margin-${s}`), 'box-shadow', 'width', 'height', 'display', 'gap', 'grid-template-columns']
fs.mkdirSync(OUT, { recursive: true })
const api = async p => { const r = await fetch(`${API}/books/${BOOK}${p}`); if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.json() }
const [tree, library, saves] = await Promise.all([api('/outline-tree'), api('/library'), api('/saves?limit=1')])
if (!saves.items[0]?.created_at) throw new Error('验收副本缺少存档，不能按样张固定为 8 分钟前存过')
const clock = { latestSaveAt: saves.items[0].created_at, fixedAt: new Date(new Date(saves.items[0].created_at).getTime() + 8 * 60_000).toISOString() }
const volumes = tree.arcs.flatMap(a => a.volumes)
const first = volumes[0], unit = first.units.find(u => !u.virtual)
const molly = library.characters.find(c => c.name === '茉莉')
if (!first || !unit || !molly) throw new Error('缺少真实验收数据，请先运行隔离复制和 seed_teardown_trial.py')
const later = volumes.find(v => v.units.some(u => u.chapters.some(c => c.index === 102)))
const virtual = later?.units.find(u => u.chapters.some(c => c.index === 102))
const positions = {
  简介: { tab: '简介' }, 设定: { tab: '设定', entry: 'overview' }, 茉莉: { tab: '设定', entry: molly.id },
  卷: { tab: '大纲', node: `v:${first.id}`, open: ['book', `v:${first.id}`] },
  单元: { tab: '大纲', node: `u:${unit.id}`, open: ['book', `v:${first.id}`, `u:${unit.id}`] },
  章: { tab: '大纲', node: 'c4', open: ['book', `v:${first.id}`, `u:${unit.id}`] },
  '章-没拆': { tab: '大纲', node: 'c102', open: ['book', `v:${first.id}`, `v:${later.id}`, `u:${virtual.id}`] },
  正文: { tab: '正文', chapter: 'home' }, 读: { tab: '正文', chapter: 'c2' },
}
const executablePath = process.env.ZHIBI_CHROMIUM ?? ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Users/cxc/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe'].find(fs.existsSync)
const browser = await chromium.launch({ executablePath })
const results = [], errors = []
function same(a, b) {
  if (a === b) return true
  // Only lengths receive the specified 0.5 CSS px tolerance; colors and all
  // other tokens remain exact, including family, weight, display and images.
  const tokens = s => s.match(/-?\d*\.?\d+px/g) ?? []
  const aa = tokens(a), bb = tokens(b)
  return aa.length > 0 && aa.length === bb.length && a.replace(/-?\d*\.?\d+px/g, '#') === b.replace(/-?\d*\.?\d+px/g, '#') && aa.every((n, i) => Math.abs(parseFloat(n) - parseFloat(bb[i])) <= .5)
}
const computed = page => page.evaluate(props => {
  // 仅豁免后续任务明确新增的入口；不遮父级、既有文字或既有控件。
  const elements = [...document.querySelectorAll('[class]')].filter(e => !e.matches('[data-testid="teardown-append-entry"],[data-testid="teardown-waits-entry"]'))
  const classes = [...new Set(elements.flatMap(e => [...e.classList]))].filter(c => !['skel', 'placeholder-note'].includes(c))
  const result = {}
  for (const c of classes) { const e = elements.find(e => e.classList.contains(c)); const s = getComputedStyle(e); result[c] = Object.fromEntries(props.map(p => [p, s.getPropertyValue(p)])) }
  return result
}, props)
const text = page => page.evaluate(() => {
  const paper = document.querySelector('.page').cloneNode(true)
  paper.querySelectorAll('.skel,.placeholder-note,.reading-prose,.chapter-prose,[data-reading-body],[data-testid="teardown-append-entry"],[data-testid="teardown-waits-entry"]').forEach(e => e.remove())
  // clone must be attached for innerText's line breaks and hidden .rest nodes.
  paper.style.cssText += ';position:fixed;left:-20000px;top:0'
  document.querySelector('.page').parentElement.append(paper)
  const out = { page: paper.innerText, rail: document.querySelector('.rail')?.innerText ?? '' }
  paper.remove(); return out
})
const masks = page => page.evaluate(() => [...document.querySelectorAll('.skel,.placeholder-note,.reading-prose,.chapter-prose,[data-reading-body],[data-testid="teardown-append-entry"]')].map(e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height } }))
function blank(png, rects) { for (const r of rects) for (let y = Math.max(0, Math.floor(r.y)); y < Math.min(png.height, Math.ceil(r.y + r.height)); y++) for (let x = Math.max(0, Math.floor(r.x)); x < Math.min(png.width, Math.ceil(r.x + r.width)); x++) { const i = (y * png.width + x) * 4; png.data[i] = png.data[i + 1] = png.data[i + 2] = 255; png.data[i + 3] = 255 } }
try {
  for (const [width, height] of SIZES) {
    for (const view of views) {
      const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: 'light' })
      const sample = await context.newPage(), actual = await context.newPage()
      for (const p of [sample, actual]) await p.clock.setFixedTime(new Date(clock.fixedAt))
      for (const p of [sample, actual]) p.on('pageerror', e => errors.push({ view, width, error: String(e) }))
      await sample.goto(pathToFileURL(path.join(ROOT, 'docs/界面原型/装修样张.html')).href + '#' + encodeURIComponent(view), { waitUntil: 'domcontentloaded' })
      await actual.addInitScript(({ book, position }) => {
        localStorage.setItem('zhibi:teardown-reading:' + book, JSON.stringify({ chapter: 2, at: Date.now() }))
        localStorage.setItem('zhibi:editorial-dock', 'ball')
        localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 }))
        sessionStorage.setItem('zhibi:workspace-reading:' + book, JSON.stringify({ tab: '简介', entry: 'overview', node: 'book', chapter: 'home', open: [], ...position }))
      }, { book: BOOK, position: positions[view] })
      await actual.goto(`${BASE}/desk/${BOOK}`, { waitUntil: 'domcontentloaded' })
      await actual.locator('.desk-v2 .page h1').waitFor()
      // 新任务明确允许只遮新增入口。它会换行增高 statline，因此仅涂白
      // 仍会把这个按钮造成的排版增量误算成旧页面回归；比较期间仅隐藏它，
      // 不遮父容器、文字或任何其他控件。真实有按钮的截图由补章节验收保留。
      const appendEntryCount = await actual.locator('[data-testid="teardown-append-entry"]').count()
      const waitsEntryCount = await actual.locator('[data-testid="teardown-waits-entry"]').count()
      if (appendEntryCount || waitsEntryCount) await actual.addStyleTag({ content: '[data-testid="teardown-append-entry"],[data-testid="teardown-waits-entry"] { display: none !important; }' })
      await Promise.all([sample.evaluate(() => document.fonts.ready), actual.evaluate(() => document.fonts.ready)])
      await actual.waitForTimeout(750)
      const [a, b, ta, tb, ma, mb] = await Promise.all([computed(sample), computed(actual), text(sample), text(actual), masks(sample), masks(actual)])
      const rows = []
      for (const [cls, values] of Object.entries(a)) for (const [property, expected] of Object.entries(values)) rows.push({ class: cls, property, expected, actual: b[cls]?.[property] ?? '(missing class)', same: b[cls] !== undefined && same(expected, b[cls][property]) })
      const proof = {
        actualAppendEntries: appendEntryCount,
        actualWaitsEntries: waitsEntryCount,
        samplePlaceholderParagraphs: await sample.locator('.skel .p').count(),
        actualProseCharacters: (await actual.locator('.chapter-prose').allTextContents()).join('').length,
        sampleFirstKidsChapters: await sample.locator('.kids').first().locator('.row').count().catch(() => 0),
        actualFirstKidsChapters: await actual.locator('.kids').first().locator('.row').count().catch(() => 0),
      }
      // Keep every raw mismatch. Only the task's real-data exceptions can be
      // classified, and each is supported by counts taken from the live DOM.
      for (const row of rows.filter(r => !r.same)) {
        if (view === '读' && proof.samplePlaceholderParagraphs > 0 && proof.actualProseCharacters > 0) {
          if (row.class === 'p' && row.actual === '(missing class)') row.dataReason = '样张 .p 只在 .skel 内表示灰条间空段；真页面显示完整原文，不生成灰条段类。'
          if (row.class === 'foot' && row.property === 'margin-top') row.dataReason = '样张灰条内容短，页脚的 auto 上边距吸收空白；完整原文超出纸面后在纸内滚动，auto 上边距为 0。'
        }
        if (view === '章-没拆' && row.class === 'kids' && row.property === 'height' && proof.sampleFirstKidsChapters === 1 && proof.actualFirstKidsChapters === virtual.chapters.length) row.dataReason = `样张左树只列当前第 102 章；真实未归单元有第 102–498 章共 ${virtual.chapters.length} 章，按只读不删内容要求完整列出并内部滚动。`
      }
      const prefix = `${width}x${height}-${view}`
      const sa = PNG.sync.read(await sample.screenshot()), sb = PNG.sync.read(await actual.screenshot())
      fs.writeFileSync(path.join(OUT, prefix + '-样张.png'), PNG.sync.write(sa)); fs.writeFileSync(path.join(OUT, prefix + '-新书页.png'), PNG.sync.write(sb))
      const mask = [...ma, ...mb]; blank(sa, mask); blank(sb, mask)
      const diff = new PNG({ width, height })
      const pixels = pixelmatch(sa.data, sb.data, diff.data, width, height, { threshold: .1, diffColor: [255, 0, 0] })
      fs.writeFileSync(path.join(OUT, prefix + '-差异.png'), PNG.sync.write(diff))
      const result = { view, width, height, classes: Object.keys(a).length, rows, styleFailures: rows.filter(r => !r.same), unexplainedStyleFailures: rows.filter(r => !r.same && !r.dataReason), proof, text: { sample: ta, actual: tb, same: ta.page === tb.page && ta.rail === tb.rail }, masks: mask, pixels, pixelPercent: pixels / (width * height) * 100, pixelPass: pixels / (width * height) <= .005 }
      fs.writeFileSync(path.join(OUT, prefix + '.json'), JSON.stringify(result, null, 2)); results.push(result)
      console.log(`${prefix}: ${result.styleFailures.length}/${rows.length} style differences; text=${result.text.same}; pixels=${result.pixelPercent.toFixed(4)}%`)
      await context.close()
    }
  }
} finally { await browser.close() }
fs.writeFileSync(path.join(OUT, 'parity-summary.json'), JSON.stringify({ at: new Date().toISOString(), base: BASE, api: API, book: BOOK, clock, threshold: .1, allowedPixelPercent: .5, lengthTolerancePx: .5, errors, results: results.map(({ rows: _rows, styleFailures, text, masks: _masks, ...r }) => ({ ...r, styleFailures: styleFailures.length, textSame: text.same })) }, null, 2))
if (errors.length) throw new Error(JSON.stringify(errors))
if (!process.env.ZHIBI_PARITY_DIAGNOSTIC && results.some(r => r.unexplainedStyleFailures.length || !r.text.same || !r.pixelPass)) process.exitCode = 1
