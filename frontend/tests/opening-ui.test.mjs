import assert from 'node:assert/strict'
import test from 'node:test'
import { appliedSelectionText, characterRange, selectionPath, storySentences } from '../src/lib/textSelection.ts'
import { followOnBookOpen, legacyBookRoute } from '../src/lib/bookRoutes.ts'
import { pendingTarget } from '../src/lib/workspace.ts'

test('选中文字按字符定位，跨行、全角标点和非BMP字符不偏移', () => {
  const text = '青灯亮了。\n他问：“谁？”😀归来！'
  const part = '他问：“谁？”😀'
  const start = text.indexOf(part)
  assert.equal(selectionPath('story', text, start, start + part.length), 'story@6:14')
  assert.deepEqual(characterRange(text, text.length, 6), { start: 6, end: 17 })
  assert.equal(selectionPath('content', text, 4, 4), null)
  assert.equal(storySentences(text).join(''), text)
  assert.equal(storySentences('第一行\n第二行。！！全角，标点；保留').join(''), '第一行\n第二行。！！全角，标点；保留')
})

test('旧路由落到新页和指定类别/卷，未知路径不擅自改写', () => {
  for (const [path, target] of Object.entries({ protagonist: 'library?view=focus', characters: 'library?cat=角色卡片', world: 'library?cat=世界与地图', spine: 'outline?view=map', threads: 'outline?view=threads', 'volume/12': 'outline?node=volume-12' })) assert.equal(legacyBookRoute(path), target)
  assert.equal(legacyBookRoute('settings'), null)
  assert.equal(followOnBookOpen('/books/b', 'b'), true)
  for (const path of ['concept', 'library', 'outline', 'chapter/3', 'protagonist', 'spine', 'settings']) assert.equal(followOnBookOpen(`/books/b/${path}`, 'b'), false)
})

test('四种三步等待直接跟随正式页面与节点', () => {
  assert.equal(pendingTarget({ kind: 'setup_pitches', flow: 3 }, 'b').path, '/books/b/concept')
  for (const [piece, target] of [['concept', 'concept'], ['settings', 'library?view=focus'], ['outline', 'outline?node=first-arc']]) assert.equal(pendingTarget({ kind: 'setup_piece', flow: 3, piece }, 'b').path, `/books/b/${target}`)
})

test('直接AI修改的标黄从完整字段响应取回选区，不把整字段错当替换片段', () => {
  assert.equal(appliedSelectionText({ path: 'story@3:5', before: '灯😀亮甲乙尾', after: '灯😀亮新的一句尾' }), '新的一句')
  assert.equal(appliedSelectionText({ path: 'content', before: '旧全文', after: '新全文' }), '新全文')
  assert.equal(appliedSelectionText({ path: 'summary@1:3', before: '甲乙丙丁', after: '甲丁' }), '')
})
