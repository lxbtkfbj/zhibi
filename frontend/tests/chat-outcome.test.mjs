import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import * as jsx from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import * as chat from '../src/lib/chat.ts'
import * as memory from '../src/lib/memory.ts'
import clsx from 'clsx'
import { ArrowLeft, NotebookPen } from 'lucide-react'

// 直接渲染真正的 ChatOutcome；只替换数据 hooks，React 和 JSX 照常运行。
const row = { id: 1, version: 1, summary: '快一点', detail: '快一点', book_id: 'outcome-book', kind: 'writing', label: '只管第 3 章', scope: 'chapter' }
let memoryRows = [row]
let memoryItem = row
const noop = () => {}
const source = readFileSync(new URL('../src/pages/book/ChatActions.tsx', import.meta.url), 'utf8')
const imports = {
  react: React,
  'react/jsx-runtime': jsx,
  '@tanstack/react-query': { useQuery: () => ({ data: memoryItem }), useQueryClient: () => ({ invalidateQueries: noop }) },
  '../../api/client': { get: noop, patch: noop, post: noop },
  '../../api/library': { useLibrary: () => ({ data: { entries: [] } }), useRevertVersion: noop },
  '../../api/settings': { useAuthorRequirements: () => ({ data: [row] }), settingsKeys: { requirements: id => ['author-requirements', id] } },
  './MemoryNotice': null,
  '../../api/memories': { useMemories: () => ({ data: memoryRows }), memoryKeys: { all: ['memories'], book: id => ['memories', id] } },
  '../../lib/memory': memory,
  '../../components/ui': { ErrorText: () => null, TypingDots: () => React.createElement('i', { 'data-typing': true }) },
  '../../lib/chat': chat,
  './context': { useBookContext: () => ({ bookId: 'outcome-book', messages: [], manualNavigate: noop }) },
}
function compile(source, imports) {
  const module = { exports: {} }
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  new Function('require', 'module', 'exports', outputText)(name => {
    assert.ok(name in imports, `未模拟的依赖 ${name}`)
    return imports[name]
  }, module, module.exports)
  return module
}
const notice = compile(readFileSync(new URL('../src/pages/book/MemoryNotice.tsx', import.meta.url), 'utf8'), imports)
imports['./MemoryNotice'] = notice.exports
const module = compile(source, imports)
const live = compile(`${readFileSync(new URL('../src/pages/workspace/LiveChat.tsx', import.meta.url), 'utf8')}\nexport { toChat }`, {
  ...imports,
  '../book/MemoryNotice': notice.exports,
  'lucide-react': {},
  '../../lib/workspace': {},
  '../book/context': imports['./context'],
  '../book/MeetingFeed': {},
  '../book/PlanCard': {},
  '../book/useGroupFeedback': {},
  './Chat': {},
  './convs': {},
  './chatModel': {},
  './writing': {},
})
const render = outcome => renderToStaticMarkup(React.createElement(module.exports.ChatOutcome, {
  message: { id: 1, speaker: 'author', content: '作者的话', created_at: new Date().toISOString(), payload: { outcome } },
}))

test('看稿判断带写作任务也保留主编回话和可撤销记忆行，不开放重新回答', () => {
  const answer = { id: 30, job_id: 'writing-job', speaker: 'chief', kind: 'speech', content: '以后都照做的已经记下了。', payload: { feedback_to: 29, memories: [{ kind: 'memory', memory: row }] } }
  const [message] = live.exports.toChat([answer], undefined, undefined)
  assert.equal(message.id, '30')
  assert.equal(message.who, '主编')
  assert.equal(message.text, answer.content)
  assert.equal(message.replyTo, undefined)
  assert.equal(message.custom, undefined, '不能折成工作记录小字行而吞掉回执')
  const html = renderToStaticMarkup(React.createElement(React.Fragment, null, message.below))
  assert.match(html, /记住了：快一点/u)
  assert.match(html, /撤销/u)
  assert.doesNotMatch(html, /重新回答/u)
  const [nothing] = live.exports.toChat([{ ...answer, payload: { feedback_to: 29, memories: [] }, content: '这段只改眼前这一处，不记。' }], undefined, undefined)
  assert.equal(nothing.text, '这段只改眼前这一处，不记。')
  assert.equal(nothing.custom, undefined)
  assert.deepEqual(nothing.below, [])
})

test('纯聊天和空结果不渲染任何节点，不留空行', () => {
  for (const kind of ['chat', 'agent', 'feedback']) assert.equal(render({ kind }), '')
})

test('没判断出来和等拍板逐字显示新字，不留手动加要求按钮', () => {
  const failed = render({ kind: 'failed', reason: '判断超时' })
  assert.match(failed, /没判断出这句话要做什么（判断超时），书没改。换个说法再说一次试试。/u)
  assert.doesNotMatch(failed, /<button|其实要记下|记成写作要求/u)
  const late = render({ kind: 'too_late' })
  assert.match(late, /编辑部在等你拍板，这句话没改书。要改，就在拍板的地方提意见，或者说「总结一下」整理成方案。/u)
  assert.doesNotMatch(late, /<button/u)
})

test('分流、make_changes 和方案卡的记忆都用同一行，没有旧对照和改一下', () => {
  for (const kind of ['requirement', 'to_job']) {
    const html = render({ kind, memory: { ...row, working: kind === 'to_job' }, diff: [{ label: '旧对照', before: '', after: row.detail }], change: ['legacy'] })
    assert.match(html, /记住了：快一点/u)
    assert.match(html, /写书时照做 · 这本书 · 只管第 3 章/u)
    assert.match(html, /撤销/u)
    assert.doesNotMatch(html, /改一下|换回原来的|旧对照|加了一条写作要求/u)
    if (kind === 'to_job') assert.match(html, /正在写的从下一步起照办/u)
  }
})

test('在看、在做和再改一版失败的原有状态保留', () => {
  assert.match(render({ kind: 'pending' }), /主编在看….*data-typing/u)
  assert.match(render({ kind: 'working', text: '主编在做' }), /主编在做….*data-typing/u)
  const redo = render({ kind: 'failed', redo_failed: true, reason: '没等到结果' })
  assert.match(redo, /再改一版没做成（没等到结果），这一处现在是改之前的样子。/u)
  assert.doesNotMatch(redo, /<button/u)
})

test('旧要求弹窗换成原地记忆编辑框，标签、默认值和保存取消逐字一致', () => {
  const component = compile(readFileSync(new URL('../src/pages/workspace/Memory.tsx', import.meta.url), 'utf8'), { ...imports,
    clsx, 'lucide-react': { ArrowLeft, NotebookPen },
    '../book/context': imports['./context'], './styles': { smallButton: 'button' },
    '../../components/ui': { ...imports['../../components/ui'], inputClass: 'input' },
  }).exports.MemoryEditor
  const html = renderToStaticMarkup(React.createElement(component, { library: 'outcome-book', bookId: 'outcome-book', onCancel: noop, onSave: noop }))
  for (const label of ['简述', '详细内容', '种类', '放在', '管多久']) assert.ok(html.includes(`aria-label="${label}"`))
  for (const label of ['写书时照做', '这本书', '一直有效']) assert.match(html, new RegExp(`selected="">${label}`, 'u'))
  assert.match(html, /<button[^>]*>保存<\/button>/u)
  assert.match(html, /<button[^>]*>取消<\/button>/u)
  assert.doesNotMatch(html, /修改写作要求|存好|记下/u)
})

test('统一记忆行真实渲染撤销后的字和两种变灰提示', () => {
  const renderNotice = (receipt, undone = false) => renderToStaticMarkup(React.createElement(notice.exports.MemoryNotice, { receipt, undone }))
  assert.match(renderNotice(row, true), /没记：快一点/u)
  assert.doesNotMatch(renderNotice(row, true), /撤销/u)
  memoryRows = [{ ...row, version: 2 }]
  let html = renderNotice(row)
  assert.match(html, /这条后来又改过，去「记忆」里改/u)
  assert.match(html, /<button[^>]*disabled=""[^>]*>撤销/u)
  memoryRows = []
  html = renderNotice(row)
  assert.match(html, /这条后来删掉了/u)
  assert.match(html, /<button[^>]*disabled=""[^>]*>撤销/u)
  memoryRows = [row]
})

test('方案卡真实渲染记忆类别与期限，而非旧写作要求标签', () => {
  const component = compile(readFileSync(new URL('../src/pages/book/PlanCard.tsx', import.meta.url), 'utf8'), { ...imports,
    clsx, 'lucide-react': { ChevronDown: () => null, X: () => null },
    './ChatActions': module.exports, '../../api/library': { ...imports['../../api/library'], useInvalidateLibrary: () => noop },
    '../../components/ui': { ...imports['../../components/ui'], Button: ({ loading: _loading, variant: _variant, size: _size, ...props }) => React.createElement('button', props) },
  }).exports.PlanCard
  const html = renderToStaticMarkup(React.createElement(component, { message: { id: 23, payload: { status: 'open', plan: { title: '方案', summary: '', items: [{ where: '写作要求', scope: '只管下一卷', change: '每卷有高潮' }], open_questions: [] } } } }))
  assert.match(html, /记忆 · 写书时照做 · 只管下一卷/u)
  assert.doesNotMatch(html, /写作要求 ·/u)
  assert.match(html, /按这个来/u)
})


test('三种记忆回执真实渲染，修改撤销显示原简述，忘掉行不是跳转按钮', () => {
  const renderNotice = (receipt, undone = false) => renderToStaticMarkup(React.createElement(notice.exports.MemoryNotice, { receipt, undone }))
  const previousRows = memoryRows
  memoryRows = [row]; memoryItem = row
  assert.match(renderNotice({ ...row, action: 'create' }), /记住了：快一点/u)
  assert.match(renderNotice({ ...row, action: 'update', before: { summary: '原来的规矩' } }), /改了一条记忆：快一点/u)
  assert.match(renderNotice({ ...row, action: 'update', before: { summary: '原来的规矩' } }, true), /换回了原来的：原来的规矩/u)
  memoryItem = { ...row, deleted_at: '2026-10-23' }
  const deleted = renderNotice({ ...row, action: 'forget' })
  assert.match(deleted, /<span>忘掉了：快一点<\/span>/u)
  assert.doesNotMatch(deleted, /disabled=|<button[^>]*>忘掉了/u)
  assert.match(renderNotice({ ...row, action: 'forget' }, true), /找回来了：快一点/u)
  memoryRows = previousRows; memoryItem = row
})
