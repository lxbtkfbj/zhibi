import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { readTeardownReading, readingArrow, readingChapterNumber, teardownDefaultVolume, textMatches, writeTeardownReading } from '../src/lib/teardownReading.ts'

function withStorage(storage, run) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage })
  try { run() } finally {
    if (original) Object.defineProperty(globalThis, 'localStorage', original)
    else delete globalThis.localStorage
  }
}
const memoryStorage = () => {
  const values = new Map()
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
}
const chapter = (index) => ({ id: `c${index}`, kind: '章', title: `第${index}章　章名`, ref: { type: 'chapter', id: String(index) } })
const book = { id: 'reading', outline: { id: 'book', kind: '全书', children: [
  { id: 'v1', kind: '卷', children: [{ id: 'u1', kind: '单元', children: [chapter(1), chapter(2)] }] },
  { id: 'v2', kind: '卷', children: [{ id: 'u2', kind: '单元', children: [chapter(3), chapter(4)] }] },
] } }

test('拆书读到哪按书分开，键和值只存章号和时间', () => {
  const storage = memoryStorage()
  withStorage(storage, () => {
    assert.equal(readTeardownReading('one'), null)
    writeTeardownReading('one', 312)
    const value = JSON.parse(storage.values.get('zhibi:teardown-reading:one'))
    assert.deepEqual(Object.keys(value).sort(), ['at', 'chapter'])
    assert.equal(value.chapter, 312)
    assert.ok(Number.isFinite(value.at))
    assert.deepEqual(readTeardownReading('one'), value)
    assert.equal(readTeardownReading('two'), null)
    writeTeardownReading('two', 1)
    assert.equal(readTeardownReading('one').chapter, 312)
  })
})

test('localStorage 读取、写入和访问本身失败都不影响阅读', () => {
  const bad = () => { throw new Error('浏览器不允许存储') }
  withStorage({ getItem: bad, setItem: bad }, () => {
    assert.equal(readTeardownReading('blocked'), null)
    assert.doesNotThrow(() => writeTeardownReading('blocked', 2))
  })
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get: bad })
  try {
    assert.equal(readTeardownReading('blocked-access'), null)
    assert.doesNotThrow(() => writeTeardownReading('blocked-access', 1))
  } finally {
    if (original) Object.defineProperty(globalThis, 'localStorage', original)
    else delete globalThis.localStorage
  }
})

test('坏记录、错误形状和无效章号当没读过，不写无效记录', () => {
  const storage = memoryStorage()
  withStorage(storage, () => {
    for (const raw of ['{坏了', 'null', '[]', '42', '{}', '{"chapter":0,"at":1}', '{"chapter":1.1,"at":1}', '{"chapter":2,"at":"昨天"}', '{"chapter":"2","at":1}']) {
      storage.values.set('zhibi:teardown-reading:bad', raw)
      assert.equal(readTeardownReading('bad'), null, raw)
    }
    for (const value of [0, -1, 1.5, Infinity, NaN]) writeTeardownReading('invalid', value)
    assert.equal(storage.values.has('zhibi:teardown-reading:invalid'), false)
  })
})

test('目录默认只定位上次读的卷，没读过或过期章号回第一卷', () => {
  withStorage(memoryStorage(), () => {
    assert.equal(teardownDefaultVolume(book), 'v1')
    writeTeardownReading(book.id, 3)
    assert.equal(teardownDefaultVolume(book), 'v2')
    writeTeardownReading(book.id, 999)
    assert.equal(teardownDefaultVolume(book), 'v1')
    assert.equal(teardownDefaultVolume({ id: 'empty', outline: { id: 'book', kind: '全书', children: [] } }), undefined)
  })
})

test('章号优先后台引用，兼容范围、空章名和旧标题', () => {
  assert.equal(readingChapterNumber(chapter(312)), 312)
  assert.equal(readingChapterNumber({ title: '第 12 章' }), 12)
  assert.equal(readingChapterNumber({ title: '', range: [7, 7] }), 7)
  assert.equal(readingChapterNumber({ title: '' }), 0)
})

const keyEvent = (key, target = null, extra = {}) => ({ key, target, defaultPrevented: false, altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, isComposing: false, ...extra })
test('← → 只翻普通阅读区，不抢输入框、群聊输入、可编辑字和输入法', () => {
  assert.equal(readingArrow(keyEvent('ArrowLeft')), -1)
  assert.equal(readingArrow(keyEvent('ArrowRight')), 1)
  assert.equal(readingArrow(keyEvent('Enter')), 0)
  const selector = 'input, textarea, select, [role="textbox"], [contenteditable]:not([contenteditable="false"])'
  for (const name of ['input', '群聊 textarea', 'select', 'textbox', 'contenteditable 子节点']) {
    const target = { closest: value => { assert.equal(value, selector, name); return {} } }
    assert.equal(readingArrow(keyEvent('ArrowLeft', target)), 0)
    assert.equal(readingArrow(keyEvent('ArrowRight', target)), 0)
  }
  assert.equal(readingArrow(keyEvent('ArrowRight', { isContentEditable: true })), 0)
  assert.equal(readingArrow(keyEvent('ArrowRight', { isContentEditable: false, closest: () => null })), 1)
  for (const flag of ['defaultPrevented', 'altKey', 'ctrlKey', 'metaKey', 'shiftKey', 'isComposing']) assert.equal(readingArrow(keyEvent('ArrowRight', null, { [flag]: true })), 0, flag)
})

test('搜索高亮是纯文字子串匹配，多个命中、标点、HTML 和中文完整保留', () => {
  const parts = textMatches('前天毒珠中天毒珠后', '天毒珠')
  assert.equal(parts.filter(part => part.match).length, 2)
  assert.equal(parts.map(part => part.text).join(''), '前天毒珠中天毒珠后')
  assert.deepEqual(textMatches('a.*b', '.*'), [{ text: 'a', match: false }, { text: '.*', match: true }, { text: 'b', match: false }])
  assert.deepEqual(textMatches('<script>', '<script>'), [{ text: '<script>', match: true }])
  assert.deepEqual(textMatches('没有', '词'), [{ text: '没有', match: false }])
  assert.deepEqual(textMatches('文字', ''), [{ text: '文字', match: false }])
})

test('正文组件按 source 分流只读，原作者编辑路径和导出保留，首页与翻章文案照任务', () => {
  const source = readFileSync(new URL('../src/pages/workspace/Manuscript.tsx', import.meta.url), 'utf8')
  for (const wording of ['找章节、搜原文……', '从第 1 章读起', '接着读第 ', '<TeardownProgress book={book} embedded', "teardown ? '上一章'", "teardown ? '下一章'", '导出这一章 TXT']) assert.ok(source.includes(wording), wording)
  assert.match(source, /book\.source === 'teardown'/)
  assert.match(source, /readOnly=\{teardown\} searchWord=\{searchWord\} searchToken=\{searchToken\} onSave=\{teardown \? undefined/)
  assert.match(source, /if \(!target\) return\s+event\.preventDefault\(\)\s+nav\.openChapter\(target\.id\)/)
  assert.match(source, /!teardown && writing\.redigest/)
  assert.match(source, /immediateSearch\.current \? 0 : 400/)
  assert.match(source, /controller\.abort\(\)/)
  assert.match(source, /querySelector\('\[data-text-match\]'\)\?\.scrollIntoView/)
})

test('重复点相同搜索词仍重新定位，加载失败显示后台错误并能重试，不冒充空原文', () => {
  const source = readFileSync(new URL('../src/pages/workspace/Manuscript.tsx', import.meta.url), 'utf8')
  assert.match(source, /\[text, searchWord, searchToken\]/)
  assert.match(source, /setLoadResult\(\{ node, attempt: loadAttempt, error: errorText\(error\) \}\)/)
  assert.match(source, /role="alert"[^>]*>\{loadError\}/)
  assert.match(source, /onClick=\{\(\) => setLoadAttempt\(attempt => attempt \+ 1\)\}>重新加载/)
  assert.match(source, /loadChapter, loadAttempt\]/)
  assert.doesNotMatch(source, /setLoaded\(\{ text: '' \}\)/)
})
