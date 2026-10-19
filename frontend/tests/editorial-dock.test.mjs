import assert from 'node:assert/strict'
import test from 'node:test'
import { readEditorialDock, writeEditorialDock } from '../src/lib/editorialDock.ts'

function withStorage(storage, run) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage })
  try { run() } finally {
    if (original) Object.defineProperty(globalThis, 'localStorage', original)
    else delete globalThis.localStorage
  }
}

test('new browsers default to the ball and all three editorial modes round-trip', () => {
  const values = new Map()
  withStorage({ getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }, () => {
    assert.equal(readEditorialDock(true), 'ball')
    for (const mode of ['side', 'float', 'ball']) {
      writeEditorialDock(mode, true)
      assert.equal(values.get('zhibi:editorial-dock'), mode)
      assert.equal(readEditorialDock(true), mode)
    }
    assert.equal(values.size, 1, 'Only the browser UI mode is stored, not book or chat data')
  })
})

test('prototype and live workspace preferences never overwrite each other', () => {
  const values = new Map()
  withStorage({ getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }, () => {
    writeEditorialDock('side', true)
    assert.equal(readEditorialDock(false), 'ball')
    writeEditorialDock('float', false)
    assert.equal(readEditorialDock(true), 'side')
    assert.equal(readEditorialDock(false), 'float')
    writeEditorialDock('ball', true)
    assert.equal(readEditorialDock(false), 'float')
    assert.deepEqual([...values.keys()].sort(), ['zhibi:editorial-dock', 'zhibi:prototype-editorial-dock'])
  })
})

test('unknown and corrupted saved modes safely fall back to the ball', () => {
  for (const value of [null, '', 'null', 'SIDE', 'docked', 'undefined', '{broken', '{}', '"side"']) {
    withStorage({ getItem: () => value }, () => assert.equal(readEditorialDock(true), 'ball'))
  }
})

test('denied reads and failed writes do not prevent opening or switching the editorial panel', () => {
  const unavailable = () => { throw new Error('Storage is disabled') }
  withStorage({ getItem: unavailable, setItem: unavailable }, () => {
    assert.equal(readEditorialDock(true), 'ball')
    for (const mode of ['side', 'float', 'ball']) assert.doesNotThrow(() => writeEditorialDock(mode, true))
  })
  withStorage(undefined, () => {
    assert.equal(readEditorialDock(false), 'ball')
    assert.doesNotThrow(() => writeEditorialDock('side', false))
  })
})
