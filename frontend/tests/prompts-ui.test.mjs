import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import React from 'react'
import * as jsx from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import { PROMPT_DIRECTORY_STORAGE_KEY, readCollapsedPromptGroups, writeCollapsedPromptGroups } from '../src/lib/promptDirectory.ts'

test('提示词目录默认只收起拆书两组，记下作者的展开状态并容错本机存储', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const storage = new Map()
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) } })
  try {
    assert.deepEqual(readCollapsedPromptGroups(), { 拆书: true, 拆书精髓: true })
    const changed = { 拆书: false, 拆书精髓: true, 聊天: true }
    writeCollapsedPromptGroups(changed)
    assert.deepEqual(JSON.parse(storage.get(PROMPT_DIRECTORY_STORAGE_KEY)), changed)
    assert.deepEqual(readCollapsedPromptGroups(), changed)
    storage.set(PROMPT_DIRECTORY_STORAGE_KEY, '{broken-json')
    assert.deepEqual(readCollapsedPromptGroups(), { 拆书: true, 拆书精髓: true })
    storage.set(PROMPT_DIRECTORY_STORAGE_KEY, JSON.stringify({ 拆书: false, 聊天: 'false' }))
    assert.deepEqual(readCollapsedPromptGroups(), { 拆书: false, 拆书精髓: true })
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, get: () => { throw new Error('storage disabled') } })
    assert.deepEqual(readCollapsedPromptGroups(), { 拆书: true, 拆书精髓: true })
    assert.doesNotThrow(() => writeCollapsedPromptGroups(changed))
  } finally {
    if (original) Object.defineProperty(globalThis, 'localStorage', original)
    else delete globalThis.localStorage
  }
})

const source = readFileSync(new URL('../src/components/UsedPrompts.tsx', import.meta.url), 'utf8')
const imports = { react: React, 'react/jsx-runtime': jsx }
const component = { exports: {} }
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
new Function('require', 'module', 'exports', outputText)(name => imports[name], component, component.exports)
const render = props => renderToStaticMarkup(React.createElement(component.exports.UsedPrompts, { onSelect: () => {}, ...props }))
const chief = { name: 'persona_chief', title: '主编人设' }
const manner = { name: 'chat_manner', title: '聊天的做法' }
const material = { name: 'chat_material', title: '聊天带的资料' }

test('一起发的保留来源先后与两段标签，当前提示词加粗不可点，其余可选中', () => {
  const html = render({ used: { parts: { system: [chief, manner], user: [material] }, names: [chief, manner, material] }, current: manner.name })
  assert.match(html, /系统提示/u)
  assert.match(html, /用户提示/u)
  assert.ok(html.indexOf(chief.title) < html.indexOf(manner.title))
  assert.ok(html.indexOf(manner.title) < html.indexOf(material.title))
  assert.match(html, /<strong>聊天的做法<\/strong>/u)
  assert.match(html, /<button[^>]+>主编人设<\/button>/u)
  assert.match(html, / → /u)
  assert.equal((html.match(/<button /gu) ?? []).length, 2)
  assert.doesNotMatch(render({ used: { parts: { system: [], user: [material] }, names: [material] } }), /系统提示/u)
  assert.doesNotMatch(render({ used: { parts: { system: [chief], user: [] }, names: [chief] } }), /用户提示/u)
})

test('旧记录用顿号及精确说明，详情有用到的标签，调用详情每个名字都能点', () => {
  const used = { parts: null, names: [chief, manner] }
  const prompt = render({ used, current: manner.name, legacyLabel: '用到的' })
  assert.match(prompt, /用到的/u)
  assert.match(prompt, /、/u)
  assert.match(prompt, /（旧记录，分不出系统提示和用户提示）/u)
  assert.doesNotMatch(prompt, /系统提示<\/span>|用户提示<\/span>/u)
  const call = render({ used })
  assert.equal((call.match(/<button /gu) ?? []).length, 2)
  assert.doesNotMatch(call, /used-prompts-label/u)
})
