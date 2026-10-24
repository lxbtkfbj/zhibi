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
const { ProfileRow } = compile(`${source}\nexport { ProfileRow }`, {
  react: React,
  'react/jsx-runtime': jsx,
  '../api/hooks': { useProfileMutations: () => ({ remove: {}, test: {} }) },
  '../components/settings/SettingsList': settingsList,
  '../components/ui': { ErrorText: () => null },
})
const render = profile => renderToStaticMarkup(React.createElement(ProfileRow, { profile, onEdit: () => {} }))
const official = { id: 'official', name: '官方DeepSeek', provider: 'openai_compatible', model: 'deepseek-flash', has_key: true, web_search: true }

test('系统设置只在 API 挑中的配置行说明后追加逐字联网搜索说明', () => {
  const selected = render(official)
  assert.match(selected, /<div class="settings-row-hint">deepseek-flash · 已保存密钥 · 联网搜索用它的密钥<\/div>/u)
  assert.equal((selected.match(/联网搜索用它的密钥/gu) ?? []).length, 1)
  const unselected = render({ ...official, id: 'other', web_search: false })
  assert.match(unselected, /<div class="settings-row-hint">deepseek-flash · 已保存密钥<\/div>/u)
  assert.doesNotMatch(unselected, /联网搜索/u)
})

test('未填密钥和演示配置保持原说明，不新增开关或填密钥控件', () => {
  const missing = render({ ...official, has_key: false, web_search: false })
  assert.match(missing, /deepseek-flash · 未填 Key/u)
  const demo = render({ ...official, provider: 'demo', web_search: false })
  assert.match(demo, /演示模式 · 内置示例内容，不联网/u)
  for (const html of [render(official), missing, demo]) {
    assert.doesNotMatch(html, /<input|role="switch"/u)
    assert.equal((html.match(/<button /gu) ?? []).length, 3)
  }
  assert.doesNotMatch(missing + demo, /联网搜索用它的密钥/u)
})
