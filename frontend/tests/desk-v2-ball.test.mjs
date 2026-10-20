import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { BALL_KEY, ballDragPosition, ballDropPosition, ballPlacement, isBallDrag, parseBallPosition } from '../src/pages/workspace/desk-v2/ballPosition.ts'

const source = readFileSync(new URL('../src/pages/workspace/desk-v2/DraggableBall.tsx', import.meta.url), 'utf8')
const chrome = readFileSync(new URL('../src/pages/workspace/desk-v2/Chrome.tsx', import.meta.url), 'utf8')
const prototype = readFileSync(new URL('../../docs/界面原型/精髓样张.html', import.meta.url), 'utf8')

test('精髓样张两类拆书页面保留literal返回字，装修页面及作者书仍用原SVG', () => {
  assert.match(prototype, /class="back">‹ 书房<\/a>/)
  assert.match(chrome, /teardown && \(tab === '简介' \|\| tab === '精髓'\) \? '‹ 书房' : <><Icon name="l" \/>书房<\/>/)
})

test('精髓样张两类拆书页面空作者不多出间隔点，其余旧页和作者书不改', () => {
  assert.match(prototype, /'拆的书' \+ \(M.author \? ' · ' \+ M.author : ''\)/)
  assert.match(chrome, /teardown && <span className="tag">\{\(tab === '简介' \|\| tab === '精髓'\) && !book.teardown\?\.author \? '拆的书' : <>拆的书 · \{book.teardown\?\.author\}<\/>\}/)
})

test('印章位置只接受有效side和有限高度比例，坏localStorage都回默认', () => {
  assert.equal(BALL_KEY, 'zhibi.ball')
  for (const raw of [null, '', 'broken', 'null', '{}', '[]', 'true', '1', '"left"', '{"side":"left"}', '{"side":"top","top":0.5}', '{"side":"left","top":"0.5"}', '{"side":"left","top":1e1000}']) assert.equal(parseBallPosition(raw), null, String(raw))
  // Captured pointers can leave the viewport: like the sample, place() clamps
  // these finite saved ratios instead of losing a legitimate edge drag.
  for (const side of ['left', 'right']) for (const top of [-1, 0, 0.4, 1, 1.1]) assert.deepEqual(parseBallPosition(JSON.stringify({ side, top })), { side, top })
})

test('拖动门槛逐字照样张hypot<4；移动本身按zoom换回CSS坐标', () => {
  assert.equal(isBallDrag(0, 0), false)
  assert.equal(isBallDrag(3, 2), false)
  assert.equal(isBallDrag(0, 4), true)
  assert.equal(isBallDrag(-4, 0), true)
  assert.deepEqual(ballDragPosition({ left: 240, top: 180, width: 75 }, -180, 120, 1.5), { left: '40px', top: '200px', right: 'auto', bottom: 'auto' })
})

test('松手取最近边和高度比例，固定24px边距、顶栏54+16及底边16，缩放不漂移', () => {
  const left = ballDropPosition({ left: 140, top: 400, width: 75 }, 2560, 1312, 1.5)
  assert.equal(left.side, 'left')
  assert.equal(left.top, (400 / 1.5) / (1312 / 1.5))
  assert.equal(ballDropPosition({ left: 775, top: 400, width: 50 }, 1600, 900, 1).side, 'right')
  assert.deepEqual(ballPlacement({ side: 'left', top: 0 }, 900, 1, 50), { top: '70px', bottom: 'auto', left: '24px', right: 'auto' })
  assert.deepEqual(ballPlacement({ side: 'right', top: 1 }, 900, 1, 50), { top: '834px', bottom: 'auto', left: 'auto', right: '24px' })
  assert.deepEqual(ballPlacement({ side: 'left', top: 0.5 }, 1200, 1.5, 50), { top: '400px', bottom: 'auto', left: '24px', right: 'auto' })
})

test('两种验收尺寸及作者缩放的坐标方程与样张place/drop逐项一致', () => {
  assert.match(prototype, /KEY = 'zhibi.ball', GAP = 24, EDGE = 16, TOP = 54/)
  assert.match(prototype, /Math\.hypot\(dx, dy\) < 4/)
  assert.match(prototype, /Math\.min\(Math\.max\(TOP \+ EDGE, pos.top \* h\), h - size - EDGE\)/)
  for (const [width, height] of [[1600, 900], [2560, 1312]]) for (const zoom of [0.8, 1, 1.2, 1.5, 1.8]) {
    for (const side of ['left', 'right']) for (const top of [-1, 0, 0.3, 0.95, 1.2]) {
      const actual = ballPlacement({ side, top }, height, zoom, 50)
      const h = height / zoom
      assert.deepEqual(actual, { top: Math.min(Math.max(54 + 16, top * h), h - 50 - 16) + 'px', bottom: 'auto', left: side === 'left' ? '24px' : 'auto', right: side === 'left' ? 'auto' : '24px' })
      const rect = { left: side === 'left' ? 50 : width - 100, top: top * height, width: 50 * zoom }
      assert.deepEqual(ballDropPosition(rect, width, height, zoom), { side: rect.left + rect.width / 2 < width / 2 ? 'left' : 'right', top: (rect.top / zoom) / (height / zoom) })
    }
  }
})

test('真实印章pointer capture拖动不打开，点击和键盘仍打开，刷新/resize/zoom均恢复', () => {
  for (const hook of ['onPointerDown', 'onPointerMove', 'onPointerUp', 'onPointerCancel', 'onClick', 'onKeyDown']) assert.ok(source.includes(hook))
  assert.match(source, /setPointerCapture\(event.pointerId\)/)
  assert.match(source, /classList.add\('dragging'\)/)
  assert.match(source, /classList.remove\('dragging'\)/)
  assert.match(source, /if \(moved.current\) \{ event.preventDefault\(\); event.stopPropagation\(\); return \} onClick\(\)/)
  assert.match(source, /localStorage.setItem\(BALL_KEY, JSON.stringify\(pos\)\)/)
  assert.match(source, /window.addEventListener\('resize', restore\)/)
  assert.match(source, /MutationObserver/)
  assert.match(source, /else for \(const property of \['left', 'right', 'top', 'bottom'\]\) ball.style.removeProperty\(property\)/)
})

test('设定分类和纲卷单元已展开且选中时只收起，小箭头独立展开不导航', () => {
  assert.match(chrome, /if \(expanded && selected === id\) onToggle\(id\); else onSelect\(id\)/)
  assert.match(chrome, /selectRow\(volume.id, expanded\)/)
  assert.match(chrome, /selectRow\(unit.id, expandedUnit\)/)
  assert.match(chrome, /selectRow\(id, expanded\)/)
  for (const id of ['id', 'volume.id', 'unit.id']) assert.ok(chrome.includes(`e.stopPropagation(); onToggle(${id})`))
  assert.match(chrome, /const expanded = open.includes\(id\)/)
  assert.doesNotMatch(chrome, /currentCategory\?\.name === category.name/)
})
