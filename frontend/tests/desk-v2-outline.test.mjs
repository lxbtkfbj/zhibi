import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const outline = readFileSync(new URL('../src/pages/workspace/desk-v2/OutlinePages.tsx', import.meta.url), 'utf8')
const workspace = readFileSync(new URL('../src/pages/workspace/Workspace.tsx', import.meta.url), 'utf8')
const actions = readFileSync(new URL('../src/pages/workspace/liveActions.ts', import.meta.url), 'utf8')
const parsed = ts.createSourceFile('Workspace.tsx', workspace, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const locateNode = parsed.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'locate')
assert.ok(locateNode)
const locateJs = ts.transpileModule(locateNode.getText(parsed), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const locate = vm.runInNewContext(`${locateJs}\nlocate`, {
  readText: host => host.value,
  document: { createRange: () => ({ selectNodeContents() {}, setEnd(_container, at) { this.at = at }, toString() { return 'x'.repeat(this.at) } }) },
})
const position = (value, picked, offset, guess = 0) => {
  const found = locate({ value, dataset: offset === undefined ? {} : { spotOffset: String(offset) } }, { startContainer: {}, startOffset: guess }, picked)
  return found && Array.from(found)
}

test('原来的大纲 n 协议恢复，章节不杜撰后端不支持的 s 协议', () => {
  assert.match(actions, /if \(kind === 'n'\)[\s\S]+?node\.ref\.type === 'volume' \|\| node\.ref\.type === 'unit'/)
  assert.match(outline, /label="那段话" spot=\{!teardown && !node\.virtual \? `n\|\$\{node\.id\}` : undefined\}/)
  assert.match(outline, /label="单元那段话" spot=\{!teardown \? `n\|\$\{node\.id\}` : undefined\}/)
  assert.doesNotMatch(outline, /spot=\{`s\|/)
  assert.match(outline, /'data-spot': spot/)
  assert.match(outline, /'data-spot-offset': spotOffset/)
  assert.match(outline, /whiteSpace: 'pre-wrap'/)
})

test('普通整段和同段重复词仍按光标附近的出现定位', () => {
  assert.deepEqual(position('甲词\n乙词', '乙词', undefined), [3, 5])
  assert.deepEqual(position('重复在前，重复在后', '重复', 0, 6), [5, 7])
  assert.equal(position('这一段', '别的', 10), null)
})

test('四格中重复短语按分号原文的累计偏移定位，不计入四格的小标题', () => {
  const text = '第一次重复；第二次重复；重复，重复；末尾重复。'
  const parts = text.replace(/。$/, '').split('；')
  const offsets = parts.map((_, index) => parts.slice(0, index).reduce((sum, part) => sum + part.length + 1, 0))
  assert.deepEqual(offsets, [0, 6, 12, 18])
  assert.deepEqual(position(parts[0], '重复', offsets[0], 3), [3, 5])
  assert.deepEqual(position(parts[1], '重复', offsets[1], 3), [9, 11])
  assert.deepEqual(position(parts[2], '重复', offsets[2], 4), [15, 17])
  assert.deepEqual(position(parts[3], '重复', offsets[3], 2), [20, 22])
  assert.match(outline, /<b style=\{!teardown \? \{ userSelect: 'none' \} : undefined\}>\{label\}<\/b><NodeEdit as="span"/)
  assert.match(outline, /spotOffset=\{!teardown \? parts\.slice\(0, index\)\.reduce\(\(sum, part\) => sum \+ part\.length \+ 1, 0\) : undefined\}/)
})

test('data 偏移不是非负安全整数时不能污染已有选区范围', () => {
  for (const offset of [-1, 'bad', 'Infinity', '1.2', Number.MAX_SAFE_INTEGER + 1]) assert.deepEqual(position('原文', '文', offset), [1, 2], String(offset))
})

test('拖选不会触发 NodeEdit 手改重挂而销毁选区，单击仍能进入手改', () => {
  assert.match(outline, /const selection = window\.getSelection\(\); if \(selection && !selection\.isCollapsed && selection\.toString\(\)\.trim\(\)\) return; setDraft\(value\); setEditing\(true\)/)
  assert.match(outline, /onBlur=\{\(\) => \{ setEditing\(false\); if \(draft !== value\) save\(draft\) \}\}/)
})

test('已写但没有章纲的旧作者章仍展示已存摘要，而非三个空章纲占位', () => {
  const fromApi = readFileSync(new URL('../src/pages/workspace/fromApi.ts', import.meta.url), 'utf8')
  assert.match(fromApi, /\[\{ label: '这一章写了什么', text: text\(brief\?\.summary\) \}\]/)
  assert.match(outline, /const extraFields = teardown \? \[\] : node\.sections\?\.filter/)
  assert.match(outline, /const showOutline = teardown \|\| !extraFields\.length \|\| node\.sections\?\.some/)
  assert.match(outline, /showOutline && <>/)
  assert.match(outline, /extraFields\.map\(field => <section[^\n]+\{field\.label\}[^\n]+value=\{field\.text\}/)
})

test('编辑部帮写沿用原业务入口，打开和收起用次按钮、提交写用主按钮', () => {
  const helper = parsed.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'WriteHelp')?.getText(parsed)
  assert.ok(helper)
  assert.match(helper, /className="btn seal-line" onClick=\{\(\) => setOpen\(true\)\}/)
  assert.match(helper, /onClick=\{\(\) => setOpen\(false\)\} className="btn seal-line ml-auto">收起/)
  assert.match(helper, /onClick=\{go\} className="btn solid shrink-0">写/)
  assert.match(helper, /actions\.writeNode!\(node, request\.trim\(\)\)/)
  assert.match(helper, /actions\.saveNode\(node, reply\.before\)/)
  assert.doesNotMatch(workspace, /import \{ AskButton \}/)
})
