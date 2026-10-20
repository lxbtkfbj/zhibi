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

test('装修后的正文沿用只读与作者编辑能力，新首页和翻章仍连接真实入口', () => {
  const source = readFileSync(new URL('../src/pages/workspace/desk-v2/ManuscriptPages.tsx', import.meta.url), 'utf8')
  const outline = readFileSync(new URL('../src/pages/workspace/desk-v2/OutlinePages.tsx', import.meta.url), 'utf8')
  const workspace = readFileSync(new URL('../src/pages/workspace/Workspace.tsx', import.meta.url), 'utf8')
  for (const wording of ['从第 1 章读起', "resume ? '接着读' : '从头读'", '按单元读', '导出这一章 TXT', '按意见重写这一章', '让设定师照改过的重看一遍']) assert.ok(source.includes(wording), wording)
  assert.match(source, /book\.source === 'teardown'/)
  assert.match(source, /readOnly=\{teardown\} searchWord=\{searchWord\} searchToken=\{searchToken\} onSave=\{!teardown && writing/)
  assert.match(source, /readingArrow\(event\)[\s\S]+?if \(target\) \{ event\.preventDefault\(\); nav\.openChapter\(target\.id\) \}/)
  assert.match(source, /writeTeardownReading\(book\.id, chapterNumber\)/)
  assert.match(source, /!teardown && writing && <>[\s\S]+?writing\.redigest/)
  assert.match(source, /<section className="page reader">/)
  assert.match(source, /<div className="reading-prose"/)
  assert.match(outline, /<small>上一章<\/small>/)
  assert.match(outline, /<small>下一章<\/small>/)
  assert.match(workspace, /tab === '正文' && <DeskManuscript/)
  assert.doesNotMatch(workspace, /<ManuscriptHome|<ManuscriptChapter/)
})

test('重复点相同搜索词仍重新定位，加载失败显示后台错误并能重试，不冒充空原文', () => {
  const textEditor = readFileSync(new URL('../src/pages/workspace/Manuscript.tsx', import.meta.url), 'utf8')
  const source = readFileSync(new URL('../src/pages/workspace/desk-v2/ManuscriptPages.tsx', import.meta.url), 'utf8')
  const query = readFileSync(new URL('../src/pages/workspace/desk-v2/OutlinePages.tsx', import.meta.url), 'utf8')
  assert.match(textEditor, /export function ChapterText/)
  assert.match(textEditor, /\[text, searchWord, searchToken\]/)
  assert.match(textEditor, /querySelector\('\[data-text-match\]'\)\?\.scrollIntoView/)
  assert.match(source, /query\.isError \?[^\n]+role="alert">\{errorText\(query\.error\)\}/)
  assert.match(source, /onClick=\{\(\) => void query\.refetch\(\)\}>重新加载/)
  assert.match(query, /queryKey: \['desk-v2-chapter', book\.id, node\?\.id/)
  assert.match(query, /writing\.loadChapter\(node!\)/)
  assert.match(query, /retry: false/)
  assert.doesNotMatch(query, /catch[^\n]+text: ''/)
})

test('装修后的作者大纲保留手改原文、空段入口和编辑部结构操作', () => {
  const source = readFileSync(new URL('../src/pages/workspace/desk-v2/OutlinePages.tsx', import.meta.url), 'utf8')
  assert.match(source, /editableNodeName = \(node: VNode\) => node\.title\.includes\('　'\) \? splitTitle\(node\.title\)\[1\]/)
  assert.match(source, /value=\{node\.sections\?\.find\(field => field\.label === '发生什么'\)\?\.text \?\? node\.text\}/)
  assert.doesNotMatch(source, /value=\{\[outline\.goal, \.\.\.outline\.scenes\]\.join/)
  assert.match(source, /chapterRest\(text\) \|\| \(!teardown \? '还没写' : ''\)/)
  assert.match(source, /node\.text \|\| \(!teardown \? '还没写' : ''\)/)
  for (const capability of ['<CountField node={node}', '<WriteHelp node={node}', '<SplitPanel node={node}', '<GateCard gate={gate}', 'actions.deleteNode(node)', "onInsert(node, 'before')", "onInsert(node, 'after')", "onMove(node, 'up')", "onMove(node, 'down')", 'onAdd(node.id)']) assert.ok(source.includes(capability), capability)
  assert.match(source, /!teardown && <AuthorControls/)
})
