import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import * as jsx from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import * as chat from '../src/lib/chat.ts'

// 直接渲染真正的 ChatOutcome；只替换数据 hooks，React 和 JSX 照常运行。
const row = { id: 'requirement-1', text: '快一点', label: '只管第 3 章', scope: 'chapter' }
const noop = () => {}
const source = readFileSync(new URL('../src/pages/book/ChatActions.tsx', import.meta.url), 'utf8')
const imports = {
  react: React,
  'react/jsx-runtime': jsx,
  '@tanstack/react-query': { useQuery: () => ({ data: {} }), useQueryClient: () => ({ invalidateQueries: noop }) },
  '../../api/client': { get: noop, patch: noop, post: noop },
  '../../api/library': { useLibrary: () => ({ data: { entries: [] } }), useRevertVersion: noop },
  '../../api/settings': { useAuthorRequirements: () => ({ data: [row] }), settingsKeys: { requirements: id => ['author-requirements', id] } },
  '../../components/RequirementDialog': { RequirementDialog: () => null },
  '../../components/ui': { ErrorText: () => null, TypingDots: () => React.createElement('i', { 'data-typing': true }) },
  '../../lib/chat': chat,
  './context': { useBookContext: () => ({ bookId: 'outcome-book', messages: [], manualNavigate: noop }) },
}
const module = { exports: {} }
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
new Function('require', 'module', 'exports', outputText)(name => {
  assert.ok(name in imports, `未模拟的依赖 ${name}`)
  return imports[name]
}, module, module.exports)
const render = outcome => renderToStaticMarkup(React.createElement(module.exports.ChatOutcome, {
  message: { id: 1, speaker: 'author', content: '作者的话', created_at: new Date().toISOString(), payload: { outcome } },
}))

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

test('写作要求继续能改，有前后对照与交给编辑部时都用加要求的新字', () => {
  const plain = render({ kind: 'requirement', requirement_id: row.id })
  assert.match(plain, /加了一条写作要求：「快一点」（只管第 3 章）/u)
  assert.match(plain, /<button[^>]*>改一下<\/button>/u)
  const diff = [{ label: '写作要求', before: '', after: row.text }]
  for (const [kind, text] of [['requirement', '加了一条写作要求'], ['to_job', '交给了编辑部：加一条写作要求']]) {
    const html = render({ kind, requirement_id: row.id, diff, change: ['requirement-1'] })
    assert.ok(html.includes(`<p>${text}</p>`))
    assert.match(html, /换回原来的/u)
    assert.match(html, /改一下/u)
    assert.doesNotMatch(html, /记成/u)
  }
})

test('在看、在做和再改一版失败的原有状态保留', () => {
  assert.match(render({ kind: 'pending' }), /主编在看….*data-typing/u)
  assert.match(render({ kind: 'working', text: '主编在做' }), /主编在做….*data-typing/u)
  const redo = render({ kind: 'failed', redo_failed: true, reason: '没等到结果' })
  assert.match(redo, /再改一版没做成（没等到结果），这一处现在是改之前的样子。/u)
  assert.doesNotMatch(redo, /<button/u)
})

test('要求编辑框使用作者补充指定的新字，不再出现记下', () => {
  const dialogSource = readFileSync(new URL('../src/components/RequirementDialog.tsx', import.meta.url), 'utf8')
  const dialogImports = {
    react: React,
    'react/jsx-runtime': jsx,
    '../lib/chat': chat,
    './ui': {
      Modal: ({ title, children, footer }) => React.createElement('section', { role: 'dialog', 'aria-label': title }, children, footer),
      Button: ({ loading: _loading, variant: _variant, ...props }) => React.createElement('button', props),
      ErrorText: () => null,
      inputClass: 'input',
    },
  }
  const dialogModule = { exports: {} }
  const transpiled = ts.transpileModule(dialogSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  new Function('require', 'module', 'exports', transpiled.outputText)(name => {
    assert.ok(name in dialogImports, `未模拟的依赖 ${name}`)
    return dialogImports[name]
  }, dialogModule, dialogModule.exports)
  const html = renderToStaticMarkup(React.createElement(dialogModule.exports.RequirementDialog, { initial: row.text, onClose: noop, onSave: noop }))
  assert.match(html, /role="dialog" aria-label="修改写作要求"/u)
  assert.match(html, /aria-label="写作要求"/u)
  assert.match(html, /<button[^>]*>保存<\/button>/u)
  assert.match(html, /<button[^>]*>取消<\/button>/u)
  assert.doesNotMatch(html, /记下/u)
})
