import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { FLOAT_KEY, fitFloatPosition, parseFloatPosition } from '../src/pages/workspace/floatPosition.ts'

const source = readFileSync(new URL('../src/pages/workspace/Workspace.tsx', import.meta.url), 'utf8')

test('浮窗位置只认有限的 x、y，坏的存档都回右下角', () => {
  assert.equal(FLOAT_KEY, 'zhibi:editorial-float')
  for (const raw of [null, '', 'broken', 'null', '{}', '[]', 'true', '1', '{"x":10}', '{"x":"10","y":20}', '{"x":10,"y":1e1000}', '{"x":null,"y":20}']) {
    assert.equal(parseFloatPosition(raw), null, String(raw))
  }
  assert.deepEqual(parseFloatPosition('{"x":120.5,"y":80}'), { x: 120.5, y: 80 })
  assert.deepEqual(parseFloatPosition('{"x":-30,"y":9999,"extra":1}'), { x: -30, y: 9999 })
})

test('放回去时夹在屏幕里：左右留 8，上面让开顶栏 64，下面留 8；按放大倍数换算', () => {
  const box = { width: 520, height: 640 }
  const view = { width: 1600, height: 900 }
  assert.deepEqual(fitFloatPosition({ x: 300, y: 120 }, box, view, 1), { x: 300, y: 120 })
  assert.deepEqual(fitFloatPosition({ x: -50, y: 10 }, box, view, 1), { x: 8, y: 64 })
  assert.deepEqual(fitFloatPosition({ x: 5000, y: 5000 }, box, view, 1), { x: 1600 - 520 - 8, y: 900 - 640 - 8 })
  // 放大 1.5 倍：存的是放大前的 CSS px，夹的时候按屏幕上的大小算，再换回去
  const zoomed = fitFloatPosition({ x: 5000, y: 0 }, { width: 780, height: 960 }, { width: 2560, height: 1312 }, 1.5)
  assert.deepEqual(zoomed, { x: (2560 - 780 - 8) / 1.5, y: 64 })
})

test('浮窗打开时读上次的位置，拖完在别处松手才记，拖到右边缘贴边时不记', () => {
  assert.match(source, /parseFloatPosition\(localStorage\.getItem\(FLOAT_KEY\)\)/)
  assert.match(source, /if \(e\.clientX > window\.innerWidth - 48\) setDock\('side'\)\n\s+else if \(dropped\.current\) \{\n\s+try \{ localStorage\.setItem\(FLOAT_KEY, JSON\.stringify\(dropped\.current\)\) \}/)
  assert.match(source, /window\.addEventListener\('resize', fit\)/)
})
