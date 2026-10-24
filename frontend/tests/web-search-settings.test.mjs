import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import * as jsx from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

function compile(source, imports) {
  const module = { exports: {} }
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  new Function('require', 'module', 'exports', outputText)(name => imports[name] ?? {}, module, module.exports)
  return module.exports
}

const settingsList = compile(readFileSync(new URL('../src/components/settings/SettingsList.tsx', import.meta.url), 'utf8'), { 'react/jsx-runtime': jsx })
const source = readFileSync(new URL('../src/pages/SettingsPage.tsx', import.meta.url), 'utf8')
let webSearch = { data: { has_key: false } }
let mutations = {}
const { ProfileRow, WebSearchGroup } = compile(`${source}\nexport { ProfileRow, WebSearchGroup }`, {
  react: React,
  'react/jsx-runtime': jsx,
  '../api/hooks': { useProfileMutations: () => ({ remove: {}, test: {} }), useWebSearch: () => webSearch, useWebSearchMutations: () => mutations },
  '../components/settings/SettingsList': settingsList,
  '../components/ui': { ErrorText: () => null },
  'lucide-react': new Proxy({}, { get: () => () => null }),
})
const render = profile => renderToStaticMarkup(React.createElement(ProfileRow, { profile, onEdit: () => {} }))
const official = { id: 'official', name: '官方DeepSeek', provider: 'openai_compatible', model: 'deepseek-flash', has_key: true }
const idle = () => ({ save: {}, clear: {}, test: {} })
const renderSearch = (data, state = idle()) => {
  webSearch = { data }
  mutations = state
  return renderToStaticMarkup(React.createElement(WebSearchGroup))
}

test('模型列表那一行不再说联网搜索借它的密钥', () => {
  assert.match(render(official), /<div class="settings-row-hint">deepseek-flash · 已保存密钥<\/div>/u)
  assert.match(render({ ...official, has_key: false }), /deepseek-flash · 未填 Key/u)
  assert.match(render({ ...official, provider: 'demo' }), /演示模式 · 内置示例内容，不联网/u)
  for (const html of [render(official), render({ ...official, provider: 'demo' })]) assert.doesNotMatch(html, /联网搜索/u)
  assert.match(source, /<WebSearchGroup \/>\n {2}<\/>\n\}/u)
})

test('联网搜索单独一块：没填说清不搜、怎么开；填了能测试、清除', () => {
  const empty = renderSearch({ has_key: false })
  assert.match(empty, /<h3>联网搜索<\/h3>/u)
  assert.match(empty, /DeepSeek API Key/u)
  assert.match(empty, /没填，编辑部不上网搜。填一把 DeepSeek 开放平台的 API Key 就能搜，不用把 DeepSeek 加成模型/u)
  assert.match(empty, /type="password"/u)
  assert.match(empty, /placeholder="sk-…"/u)
  assert.doesNotMatch(empty, />清除</u)
  assert.equal((empty.match(/<button [^>]*disabled=""[^>]*>(测试|保存)<\/button>/gu) ?? []).length, 2, '没填也没存时测试、保存都点不了')

  const saved = renderSearch({ has_key: true })
  assert.match(saved, /已保存，不回显 · 群聊里编辑部拿不准时会自己上网搜/u)
  assert.match(saved, /placeholder="••••••••（填新的就换掉）"/u)
  assert.match(saved, /<button type="button" class="settings-button +is-danger ">清除<\/button>/u)
  assert.match(saved, /<button type="button" class="settings-button +">测试<\/button>/u, '存了密钥不填新的也能测试')
  assert.match(saved, /<button type="button" disabled="" class="settings-button is-primary +">保存<\/button>/u)
  assert.doesNotMatch(saved, /sk-[A-Za-z0-9]/u)
})

test('测试结果照后端的话显示', () => {
  const ok = renderSearch({ has_key: true }, { ...idle(), test: { data: { ok: true, message: '能搜：试搜「网络小说」，第一条是百度百科《网络小说》。' } } })
  assert.match(ok, /text-lore/u)
  assert.match(ok, /能搜：试搜「网络小说」，第一条是百度百科《网络小说》。/u)
  const bad = renderSearch({ has_key: true }, { ...idle(), test: { data: { ok: false, message: 'DeepSeek 不认这把密钥，看看有没有填错、是不是已经删了。' } } })
  assert.match(bad, /text-seal/u)
  assert.match(bad, /DeepSeek 不认这把密钥/u)
})
