import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parseTeardownUpto, teardownModelName } from '../src/lib/teardownStart.ts'
import { ROLE_KEYS, ROLE_KEY_LABEL } from '../src/lib/roles.ts'

const source = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')

test('拆书分工排在审稿后且一直显示，说明逐字使用任务文件', () => {
  assert.equal(ROLE_KEYS[ROLE_KEYS.indexOf('reviewer') + 1], 'teardown')
  assert.equal(ROLE_KEY_LABEL.teardown, '拆书')
  const page = source('../src/pages/SettingsPage.tsx')
  assert.ok(page.includes("teardown: '拆书时读原文、归单元归卷都用它：一本书要调几百次，挑便宜快、格式稳的'"))
  assert.match(page, /ROLE_KEYS\.filter\(role => role !== 'router' \|\| roles\.data\?\.router\)/)
  assert.ok(page.includes('跟随默认${defaultName ? `（${defaultName}）`'))
})

test('拆到第几章：空是全本，超过章数按全本，0负数和非整数不能开始', () => {
  assert.equal(parseTeardownUpto('', 40), null)
  assert.equal(parseTeardownUpto('  ', 40), null)
  assert.equal(parseTeardownUpto('20', 40), 20)
  assert.equal(parseTeardownUpto('40', 40), 40)
  assert.equal(parseTeardownUpto('41', 40), null)
  assert.equal(parseTeardownUpto('999999', 40), null)
  for (const value of ['0', '-1', '1.5', 'NaN', 'Infinity', 'abc']) assert.equal(parseTeardownUpto(value, 40), undefined, value)
})

test('费用提醒按拆书、默认、第一个、演示模式的顺序取模型名', () => {
  const profiles = [{ id: 'first', name: '第一个模型' }, { id: 'default', name: '默认模型' }, { id: 'teardown', name: '拆书模型' }]
  assert.equal(teardownModelName(profiles, { default: 'default', teardown: 'teardown' }), '拆书模型')
  assert.equal(teardownModelName(profiles, { default: 'default', teardown: null }), '默认模型')
  assert.equal(teardownModelName(profiles, { default: null }), '第一个模型')
  assert.equal(teardownModelName(profiles, { default: 'deleted', teardown: 'deleted' }), '第一个模型')
  assert.equal(teardownModelName([], { default: null, teardown: null }), '演示模式')
})

test('确认页的三个按钮、共用范围与费用文字、原来的字段保存均保留', () => {
  const page = source('../src/pages/Teardown.tsx')
  const options = source('../src/components/TeardownStart.tsx')
  for (const text of ['开始拆', '先只导入，不拆', '不导入了']) assert.ok(page.includes(text), text)
  for (const text of ['拆到第几章', '不填就是全本（${total} 章）', '至少拆 1 章', '只想学开篇，或者没读过怕剧透，就填一个数', '拆书要把整本原文发给模型，书越长调用越多，费用可能不小。用的是系统设置里「拆书」那一行的模型（现在是 {model.name}）。']) assert.ok(options.includes(text), text)
  assert.match(options, /border border-seal\/40/)
  assert.match(page, /teardownPreviewTotals\(preview, include\)\.chapters/)
  assert.match(page, /void importBook\(true\)/)
  assert.match(page, /void importBook\(false\)/)
  assert.match(page, /disabled=\{busy !== null \|\| upto === undefined/)
  const importFlow = page.slice(page.indexOf('const importBook'), page.indexOf('const cancel'))
  assert.ok(importFlow.indexOf('await saveFields()') < importFlow.indexOf('await importTeardown('))
  assert.match(importFlow, /start \? \{ upto \} : undefined/)
})

test('已导入的开始窗居中宣纸、Esc与Tab焦点边界、提交失败留窗显示原样错误', () => {
  const dialog = source('../src/components/TeardownStart.tsx')
  assert.ok(dialog.includes('开始拆《{title}》'))
  assert.ok(dialog.includes('先不拆'))
  assert.match(dialog, /fixed inset-0.*items-center justify-center.*backdrop-blur-\[6px\]/)
  assert.match(dialog, /border border-line bg-paper/)
  assert.match(dialog, /role="dialog" aria-modal="true"/)
  assert.match(dialog, /event\.key === 'Escape'/)
  assert.match(dialog, /event\.key !== 'Tab'/)
  assert.match(dialog, /previous\?\.focus\(\)/)
  assert.match(dialog, /await onStart\(upto\); onClose\(\)/)
  assert.match(dialog, /catch \(reason\) \{ setError\(reason\) \}/)
  assert.match(dialog, /<ErrorText error=\{error\}/)
  assert.match(dialog, /if \(operating\.current \|\| !model\.ready \|\| upto === undefined\) return/)
  assert.match(dialog, /open \? createPortal\(<StartDialog/)
})

test('开始停下和导入带start只使用任务1现有接口', () => {
  const api = source('../src/api/teardown.ts')
  assert.match(api, /start\?: \{ upto: number \| null \}/)
  assert.match(api, /\.\.\.\(start \? \{ start \} : \{\}\)/)
  assert.match(api, /startTeardown = \(bookId: string, upto: number \| null\) => post<Job>\(`\/teardown\/\$\{bookId\}\/start`, \{ upto \}\)/)
  assert.match(api, /stopTeardown = \(bookId: string\) => post<Job>\(`\/teardown\/\$\{bookId\}\/stop`\)/)
})
