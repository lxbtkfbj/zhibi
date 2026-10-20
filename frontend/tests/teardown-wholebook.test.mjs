import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import * as jsx from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import * as model from '../src/pages/workspace/model.ts'
import * as reading from '../src/lib/teardownReading.ts'
import * as closing from '../src/lib/teardownWholebook.ts'
import * as start from '../src/lib/teardownStart.ts'
import * as settings from '../src/pages/workspace/desk-v2/settingsData.ts'
import { teardownProgressView } from '../src/lib/teardownProgress.ts'
import { teardownAppendNotes, teardownAppendSelection } from '../src/lib/teardownAppend.ts'
import { bookFromApi } from '../src/pages/workspace/fromApi.ts'
import { resolveWorkspaceReadingPosition } from '../src/lib/workspaceReadingPosition.ts'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
function load(file, imports, extra = '') {
  const { outputText } = ts.transpileModule(read(file) + extra, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => {
    if (name === 'react') return React
    if (name === 'react/jsx-runtime') return jsx
    assert.ok(name in imports, `未模拟的依赖 ${name}`)
    return imports[name]
  }, module, module.exports)
  return module.exports
}
const noop = () => {}, nullComponent = () => null
let ledger, digest, control, queries
const actions = { canEdit: () => true, canAdd: () => false, canArrange: () => false, canDelete: () => false, saveNode: noop, live: false }
const workspace = { useWorkspace: () => ({ actions, report: noop }), useSave: () => noop, childKind: node => node.children?.[0]?.kind ?? node.childKind }
const query = { useQuery: options => { queries.push(options); return { data: options.queryKey[0] === 'desk-v2-waits' ? ledger : options.queryKey[0] === 'desk-v2-digest' ? digest : undefined } } }
const shared = load('../src/pages/workspace/desk-v2/shared.tsx', {})
const outline = load('../src/pages/workspace/desk-v2/OutlinePages.tsx', {
  '@tanstack/react-query': query, '../../../api/client': {}, '../../../lib/teardownReading': reading,
  '../../../lib/teardownWholebook': closing, '../actions': workspace,
  '../Workspace': { CountField: nullComponent, WriteHelp: nullComponent }, '../Inbox': { PendingNote: nullComponent },
  '../Manuscript': { GateCard: nullComponent }, '../model': model, '../Split': { SplitPanel: nullComponent },
  '../useSplit': { useSplit: () => ({}) }, '../TeardownProgress': { useTeardownControl: () => control },
  '../writing': {}, './shared': shared, './settingsData': settings,
})
const chrome = load('../src/pages/workspace/desk-v2/Chrome.tsx', {
  '@tanstack/react-query': query, 'react-router-dom': { Link: ({ to, children, ...props }) => React.createElement('a', { href: to, ...props }, children) },
  '../../../api/textSearch': {}, '../../../lib/teardownReading': { ...reading, readTeardownReading: () => null },
  '../../../lib/teardownProgress': { teardownProgressView }, '../../../lib/teardownStart': start,
  '../TeardownProgress': { useTeardownControl: () => control }, '../model': model, '../actions': workspace, './shared': shared, './settingsData': settings,
})
const dialog = load('../src/components/TeardownStart.tsx', {
  clsx: (...args) => args.filter(Boolean).join(' '), 'lucide-react': { X: nullComponent },
  'react-dom': { createPortal: node => node }, '../api/teardown': { useTeardownModel: () => ({ name: '演示模型', ready: true }) },
  '../lib/teardownStart': start, './ui': { Button: ({ variant, loading: _loading, ...props }) => React.createElement('button', { 'data-variant': variant, ...props }), ErrorText: nullComponent, inputClass: 'input' },
}, '\nexport { StartDialog }')
const item = (code, planted, resolved, hints = [], kind = '期待') => ({ code, planted, resolved, hints, kind, what: code + '那件事', how: '事情了结' })
function book(stage = 'stopped') {
  const volume = (index, first, last) => ({ id: `v:${index}`, kind: '卷', title: `第${model.cn(index)}卷　卷名${index}`, text: '卷的一段话', range: [first, last], uses: [], ref: { type: 'volume', id: `v${index}` }, children: [{ id: `u:${index}`, kind: '单元', text: '', range: [first, last], uses: [], children: [] }] })
  return { id: 'test', source: 'teardown', title: '测试书', categories: [], teardown: { stage, chapters: 300, last_read: 100, read: 100, needs_closing: true }, outline: { id: 'book', kind: '全书', title: '全书', text: '', uses: [], range: [1, 300], children: [volume(1, 1, 100), volume(2, 101, 200), volume(3, 201, 300)] } }
}
const nav = { openNode: noop, openEntry: noop, openChapter: noop }
function render(book, id = 'book') {
  queries = []
  return renderToStaticMarkup(React.createElement(outline.DeskOutline, { book, id, nav, fresh: false, onAdd: noop, onInsert: noop, onMove: noop }))
}
function reset() { ledger = undefined; digest = undefined; control = null; queries = [] }

test('9.1目录：全书后紧接等待账，账/未整理和虚篇class与选择id逐字对应', () => {
  reset(); const b = book(); b.outline.children = [{ id: 'a:unassigned', kind: '篇', title: '还没归篇', virtual: true, children: b.outline.children }]
  const html = renderToStaticMarkup(React.createElement(chrome.DeskDirectory, { book: b, tab: '大纲', selected: 'waits', open: [], onSelect: noop, onToggle: noop }))
  assert.match(html, /全书.*读者在等的事.*还没整理.*row top1 virtual.*还没归篇/)
  b.teardown.waits = { upto: 100, total: 9, open: 3 }
  const withLedger = renderToStaticMarkup(React.createElement(chrome.DeskDirectory, { book: b, tab: '大纲', selected: 'waits', open: [], onSelect: noop, onToggle: noop }))
  assert.match(withLedger, /row top1 on[^<]*.*读者在等的事.*3 件还吊着/)
  b.source = 'new'
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(chrome.DeskDirectory, { book: b, tab: '大纲', selected: 'book', open: [], onSelect: noop, onToggle: noop })), /读者在等的事/)
})

test('9.2全书结局四种空状态，不把章目标当最后读到；总章数/卷/单元和无篇节奏卡片', () => {
  reset(); const b = book()
  assert.match(render(b), /300 章 · 3 卷 · 3 个单元/)
  assert.match(render(b), /现在拆到第 100 章，一共 300 章。/)
  assert.match(render(b), /一格一卷，宽窄是章数/)
  assert.doesNotMatch(render(b), /data-editable="给全书/)
  assert.equal(closing.endingState(null, 0, 300), '还没开拆。拆到最后一章以后，这里写全书结局。')
  assert.equal(closing.endingState({ stage: 'done', ending: { upto: 300, ended: false } }, 300, 300), '主编看了最后几章：原书到第 300 章还没收住全书，所以没写结局。补上后面的章节、拆到最后一章以后再看。')
  assert.equal(closing.endingState({ stage: 'done' }, 300, 300), '全书都拆过了，结局还没写：点右上角「补上整理」。')
  assert.equal(closing.endingState({ stage: 'stopped' }, 100, 300), '拆到最后一章以后，这里写全书结局：主线怎么了结、主角最后到了哪、各人的去向、停在什么画面。现在拆到第 100 章，一共 300 章。')
})

test('9.2全书有结局四格并能手改，非四句整段lead；有篇包含虚篇节奏但不出虚篇卡', () => {
  reset(); const b = book('done'), volumes = b.outline.children
  b.outline.ref = { type: 'segment', id: 'ending' }; b.outline.text = '甲；乙；丙；丁。'
  b.outline.children = [{ id: 'a:one', kind: '篇', title: '第一篇　第一篇名', text: '篇的一段话', range: [1, 200], ref: { type: 'segment', id: 'one' }, children: volumes.slice(0, 2), uses: [] }, { id: 'a:unassigned', kind: '篇', title: '还没归篇', virtual: true, range: [201, 300], children: volumes.slice(2), uses: [] }]
  const html = render(b)
  for (const text of ['300 章 · 1 篇 · 3 卷 · 3 个单元', '原书在第 300 章完结', '主线怎么了结', '主角最后到了哪', '各人的去向', '停在什么画面', '一格一篇，宽窄是章数', '第 3–3 卷还没归篇', '第 1–200 章 · 200 章 · 2 卷']) assert.ok(html.includes(text), text)
  assert.equal((html.match(/class="beat"/g) ?? []).length, 4)
  assert.equal((html.match(/class="ucard"/g) ?? []).length, 1)
  assert.match(html, /data-editable="全书结局"/)
  b.outline.text = '一整段'
  assert.match(render(b), /class="lead" data-editable="全书结局">一整段/)
})

test('9.3篇的范围、卷数、arc汇总参数、右栏标题；9.4虚篇无右栏与编辑', () => {
  reset(); const b = book(), volumes = b.outline.children
  b.outline.children = [{ id: 'a:one', kind: '篇', title: '第一篇　第一篇名', text: '篇的一段话', range: [1, 300], ref: { type: 'segment', id: 'one' }, children: volumes, uses: [] }]
  digest = { people: [{ name: '主角', chapters: 80 }], changes: [{ chapter: 80, change: '变强' }], waits: [], things: [] }
  const html = render(b, 'a:one')
  for (const text of ['300 章 · 第 1–300 章 · 3 卷', '一格一卷，宽窄是章数', '这一篇的人', '主角这一篇怎么变的']) assert.ok(html.includes(text), text)
  const q = queries.find(option => option.queryKey[0] === 'desk-v2-digest')
  assert.equal(q.enabled, true)
  assert.match(read('../src/pages/workspace/desk-v2/OutlinePages.tsx'), /node.kind === '篇' \? 'arc'/)
  b.outline.children[0] = { ...b.outline.children[0], id: 'a:unassigned', virtual: true, title: '还没归篇', ref: undefined }
  const virtual = render(b, 'a:unassigned')
  assert.match(virtual, /这几卷还没归篇：拆到后面、凑够一个大阶段，收尾时主编再把它们归成篇。/)
  assert.doesNotMatch(virtual, /class="rail"|data-editable/)
})

test('作者篇保留原卷数量词和目录样式，仅拆书篇用新meta与选中on；两者节奏小字按卷纠正', () => {
  reset(); const b = book(), volumes = b.outline.children
  b.outline.children = [{ id: 'a:one', kind: '篇', title: '第一篇　第一篇名', text: '篇的一段话', range: [1, 300], ref: { type: 'segment', id: 'one' }, children: volumes, uses: [] }]
  const directory = () => renderToStaticMarkup(React.createElement(chrome.DeskDirectory, { book: b, tab: '大纲', selected: 'a:one', open: [], onSelect: noop, onToggle: noop }))
  const teardown = render(b, 'a:one')
  assert.ok(teardown.includes('300 章 · 第 1–300 章 · 3 卷'))
  assert.ok(teardown.includes('一格一卷，宽窄是章数'))
  assert.match(directory(), /class="row top1 on"/)
  b.source = 'new'
  const author = render(b, 'a:one')
  assert.ok(author.includes('300 章 · 第 1–300 章 · 3 个卷'))
  assert.ok(author.includes('一格一卷，宽窄是章数'))
  assert.doesNotMatch(directory(), /class="row top1 on"/)
  assert.doesNotMatch(author, /这一篇的人|读者在等的事/)
})

test('9.5等待账两类、颜色、按立下/时长排序、提起次数、30件展开；无账四句', () => {
  reset(); const b = book()
  ledger = { upto: 100, last: 100, items: [item('E1', 1, null), item('F2', 2, null, [3, 4], '伏笔'), item('E3', 3, 50, [9]), item('F4', 10, 90, [], '伏笔')] }
  const html = render(b, 'waits')
  for (const text of ['整理到第 100 章 · 一共 4 件 · 兑现了 2 件 · 还吊着 2 件', '期待：读者知道会发生，等着看怎么发生；伏笔：读者不知道答案，等着揭开。从立下到兑现隔了几章，就是读者被吊了多久。', '2 件，按立下先后', '2 件，吊得久的在前', '第 1 章立下', '第 10 章 → 第 90 章', '（吊了 98 章，中间提起 2 次）', 'F4那件事：事情了结', 'chip ochre', 'chip indigo']) assert.ok(html.includes(text), text)
  assert.ok(html.indexOf('F4那件事') < html.indexOf('E3那件事'))
  assert.doesNotMatch(html, /class="rail"/)
  ledger.items = Array.from({ length: 31 }, (_, i) => item('E' + i, i + 1, null))
  assert.match(render(b, 'waits'), /还有 1 件，展开/)
  assert.equal(closing.waitsState(0, 'done', false), '还没开拆。拆过的章会把读者在等的事连起来：哪章立下、哪章兑现、吊了读者多久。')
  assert.equal(closing.waitsState(100, 'running', true), '拆书收尾时整理，到时这里就有了。')
  assert.equal(closing.waitsState(100, 'done', false), '还没整理：点右上角「补上整理」，不重读原文。')
  assert.equal(closing.waitsState(100, 'stopped', false), '还没整理：点右上角「接着拆」，选「只整理前 100 章」，不重读原文。')
})

test('9.2全书右栏总账仅total>0出现，混排最长5件，链接立下章与全部账', () => {
  reset(); const b = book(); b.teardown.waits = { upto: 100, total: 6, open: 3 }
  ledger = { upto: 100, last: 100, items: [item('E1', 1, null), item('E2', 2, 50), item('E3', 3, null), item('F4', 4, 70), item('E5', 5, null), item('F6', 6, 7)] }
  const html = render(b)
  for (const text of ['一共 6 件：兑现了 3 件，还吊着 3 件。下面是吊得最久的。', '第 1 章 → 还吊着', 'E1那件事（99 章）', '全部 6 件 ›']) assert.ok(html.includes(text), text)
  assert.doesNotMatch(html, /F6那件事/)
  b.teardown.waits.total = 0
  assert.doesNotMatch(render(b), /class="rail"/)
})

test('9.6三种新进度和settings逐字；按钮imported/done需补/done无需/其余', () => {
  reset(); const b = book()
  for (const [doing, text] of [['arcs', '主编在归篇'], ['ending', '主编在写全书结局'], ['waits', '主编在理读者在等的事：第 81–100 章'], ['settings', '设定师在整理设定']]) {
    const job = { kind: 'teardown', status: 'running', pending: { teardown: { doing, waits: { first: 81, last: 100 }, read: 100, target: 100, total: 300 } } }
    assert.equal(teardownProgressView(b, job).text, text)
  }
  for (const [stage, needsClosing, text] of [['imported', false, '开始拆'], ['done', true, '补上整理'], ['done', false, null], ['stopped', false, '接着拆']]) assert.equal(start.teardownStartLabel(stage, needsClosing), text)
  for (const [stage, needsClosing, text] of [['imported', false, '开始拆'], ['done', true, '补上整理'], ['stopped', false, '接着拆']]) {
    b.teardown.stage = stage; b.teardown.needs_closing = needsClosing
    assert.ok(renderToStaticMarkup(React.createElement(chrome.DeskTop, { book: b, tab: '大纲', onTab: noop })).includes(text))
  }
})

test('9.7两种对话框逐字与三个按钮条件、已有目标预填、全读不显示范围', () => {
  reset(); const props = { title: '测试书', total: 300, last: 100, needsClosing: true, stage: 'stopped', initialUpto: 100, onClose: noop, onStart: noop }
  const partial = renderToStaticMarkup(React.createElement(dialog.StartDialog, props))
  for (const text of ['开始拆《测试书》', '已经拆到第 100 章，一共 300 章。', '先不拆', '只整理前 100 章', '开始拆', 'data-variant="outline"']) assert.ok(partial.includes(text), text)
  assert.match(partial, /value=""/)
  assert.match(renderToStaticMarkup(React.createElement(dialog.StartDialog, { ...props, initialUpto: 200 })), /value="200"/)
  for (const change of [{ last: 0 }, { needsClosing: false }]) assert.doesNotMatch(renderToStaticMarkup(React.createElement(dialog.StartDialog, { ...props, ...change })), /只整理前/)
  const full = renderToStaticMarkup(React.createElement(dialog.StartDialog, { ...props, last: 300 }))
  for (const text of ['补上整理《测试书》', '全书 300 章都读过了。这次不重读原文，只把收尾补上：没归完的单元和卷、篇、全书结局、设定、读者在等的事、精髓，做好了的不重做。', '先不整理', '开始整理', '拆书要把整本原文发给模型']) assert.ok(full.includes(text), text)
  assert.doesNotMatch(full, /拆到第几章|只整理前/)
  const source = read('../src/components/TeardownStart.tsx')
  assert.match(source, /start = async \(target = allRead \? null : upto\)/)
  assert.match(source, /onClick=\{\(\) => void start\(last\)\}/)
})

test('9.8done空设定与摘要last_read；补章确认新增结局条且勾回不会丢失', () => {
  reset(); const b = book('done')
  assert.equal(settings.emptyTeardownSettingsMeta(b, null), '设定还没整理：点右上角「补上整理」，不重读原文')
  assert.equal(settings.currentRead(b), 100)
  const preview = { reopen: [{ kind: 'ending' }], previous: { chapters: 100, original_volumes: false }, junction: {}, duplicates: { leading: [], content: 0 }, volumes: [], selection: [{ order: 0, excluded: false, title: '新章', number: 101, flags: [], volume: 1 }], reopen_context: { last_volume: { index: 1, title: '旧卷', summary: false }, original_volumes: false, open_volume_id: 'v1', tail_unit: null }, last_numbered: null }
  assert.deepEqual(teardownAppendNotes(preview), ['全书结局会删掉：补上以后拆到最后一章，再看原书完没完'])
  assert.deepEqual(teardownAppendSelection(preview, []).reopen, [{ kind: 'ending' }])
})

test('虚篇映射为稳定只读id且不认下一篇，等待账阅读记忆仅拆书能恢复', () => {
  const parts = { book: { id: 'x', title: '书', genre: '', source: 'teardown', concept: {} }, library: { characters: [], entries: [], categories: [] }, relationships: [], chapters: [], outline: { ending: null, segmented: true, arcs: [{ node_id: null, virtual: true, title: '还没归篇', text: '', planned: true, locked: true, status: 'done', end: null, volumes: [] }] } }
  const virtual = bookFromApi(parts).outline.children[0]
  assert.equal(virtual.kind, '篇'); assert.equal(virtual.virtual, true); assert.equal(virtual.id, 'a:unassigned'); assert.equal(virtual.title, '还没归篇'); assert.equal(virtual.ref, undefined); assert.equal(virtual.next, false)
  const b = book(), fallback = { tab: '大纲', entry: 'overview', node: 'book', chapter: 'home', open: [] }
  assert.equal(resolveWorkspaceReadingPosition(b, { node: 'waits' }, fallback, true).node, 'waits')
  b.source = 'new'
  assert.equal(resolveWorkspaceReadingPosition(b, { node: 'waits' }, fallback, true).node, 'book')
})
