import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import React from 'react'
import * as jsx from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import clsx from 'clsx'
import * as icons from 'lucide-react'
import * as model from '../src/pages/workspace/chatModel.ts'

const source = readFileSync(new URL('../src/pages/workspace/Chat.tsx', import.meta.url), 'utf8')
const imports = { react: React, 'react/jsx-runtime': jsx, 'lucide-react': icons, clsx, './chatModel': model, './chatBrowser': {}, '../../components/ui': {} }
const module = { exports: {} }
const { outputText } = ts.transpileModule(`${source}\nexport { AuthorBubble, Reply }`, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
new Function('require', 'module', 'exports', outputText)(name => imports[name], module, module.exports)
const render = (name, props) => renderToStaticMarkup(React.createElement(module.exports[name], props))
const noop = () => {}
const author = { id: 'author', who: '作者', text: '给编辑部的一句话', rewind: {} }

test('作者气泡先于按钮，复制在修改前，85%宽度不再扣除按钮', () => {
  const html = render('AuthorBubble', { message: author, canRewind: true, onRewind: noop, editing: false, chat: {}, endRewind: noop })
  assert.ok(html.indexOf('author-bubble') < html.indexOf('author-actions'))
  assert.ok(html.indexOf('复制') < html.indexOf('修改'))
  assert.match(html, /max-w-\[85%\] flex-col items-end/u)
  assert.match(html, /opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100/u)
  const decision = render('AuthorBubble', { message: { ...author, rewind: undefined }, canRewind: true, onRewind: noop, editing: false, chat: {}, endRewind: noop })
  assert.match(decision, /复制/u)
  assert.doesNotMatch(decision, /修改/u)
})

test('回答下记忆小框在共同行前；旧回答只淡出按钮，查阅不淡出', () => {
  const html = render('Reply', { message: { id: 'reply', who: '主编', text: '答复', state: 'done', replyTo: 'author', looked: [{ label: '主角', text: '查到的原文' }], memories: React.createElement('div', null, '记住了：留悬念') }, latest: false, answering: false, onAgain: noop })
  assert.ok(html.indexOf('chat-memory-box') < html.indexOf('reply-footer'))
  assert.match(html, /rounded-lg border border-line bg-card px-3 py-2/u)
  assert.ok(html.indexOf('查了：') < html.indexOf('复制'))
  assert.ok(html.indexOf('查了：') < html.indexOf('opacity-0'))
  assert.doesNotMatch(html, /重新回答/u)
})

test('合成带话确认在同一个作者气泡内另起一行，只有复制；作者记忆也进同款框', () => {
  const text = '批准这一卷的卷纲，开写。\n以后每章结尾留悬念。\n人物不要自言自语。'
  const html = render('AuthorBubble', { message: { id: 'decision', who: '作者', text, memories: React.createElement('div', null, '记住了：留悬念') }, canRewind: true, onRewind: noop, editing: false, chat: {}, endRewind: noop })
  assert.equal((html.match(/data-testid="author-bubble"/gu) ?? []).length, 1)
  assert.ok(html.includes(text))
  assert.match(html, /whitespace-pre-wrap/u)
  assert.match(html, /复制/u)
  assert.doesNotMatch(html, /修改|你：/u)
  assert.match(html, /data-testid="chat-memory-box"/u)
  assert.ok(html.indexOf('author-bubble') < html.indexOf('chat-memory-box'))
})
