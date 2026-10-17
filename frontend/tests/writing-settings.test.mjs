import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { automaticPlaybookName, bookLengthEstimate, parseTargetLength, requirementSource } from '../src/lib/writingSettings.ts'

test('automatic playbook requires both fantasy and payoff tags', () => {
  assert.equal(automaticPlaybookName({ genre: '玄幻', tags: ['热血'] }), '通用')
  assert.equal(automaticPlaybookName({ genre: '都市', tags: ['后宫'] }), '通用')
  assert.equal(automaticPlaybookName({ genre: '仙侠', tags: ['多女主'] }), '后宫玄幻爽文')
  assert.equal(automaticPlaybookName({ genre: '高武爽文', tags: [] }), '后宫玄幻爽文')
  assert.equal(automaticPlaybookName({ genre: '都市', title: '后宫玄幻爽文' }), '通用')
  assert.equal(automaticPlaybookName(null), '通用')
})

test('author requirement source labels preserve all supported origins', () => {
  for (const [source, label] of [['answer', '动笔前的回答'], ['note', '插话'], ['trial', '试读意见'], ['manual', '手动添加'], ['legacy', '旧记录'], ['plan', '方案卡'], ['volume:12', '第 12 卷卷纲意见'], ['private:lorekeeper', '私聊设定师'], ['private:chief', '私聊主编'], ['private:writer', '私聊写手'], ['private:reviewer', '私聊审稿']]) {
    assert.equal(requirementSource(source), label)
  }
})

test('全书篇幅仅接受 5–1000 万字整数，空白与越界不会偷偷改成边界值', () => {
  for (const length of [5, 6, 300, 1000]) assert.equal(parseTargetLength(String(length)), length)
  assert.equal(parseTargetLength(' 50 '), 50)
  for (const invalid of ['', ' ', '0', '4', '1001', '5.5', '-5', 'NaN', 'Infinity', '五十']) assert.equal(parseTargetLength(invalid), null)
})

test('篇幅章数按本书章字数、概念章字数、3000 字依次回退', () => {
  assert.deepEqual(bookLengthEstimate(30, 2000, 4000), { chapterWords: 2000, chapters: 150 })
  assert.deepEqual(bookLengthEstimate(30, null, 4000), { chapterWords: 4000, chapters: 75 })
  assert.deepEqual(bookLengthEstimate(30), { chapterWords: 3000, chapters: 100 })
  assert.deepEqual(bookLengthEstimate(5, 0, -1), { chapterWords: 3000, chapters: 17 })
  assert.deepEqual(bookLengthEstimate(null, 2000), { chapterWords: 2000, chapters: null })
})

test('新书默认与本书共用段确认开关，篇幅只注入本书写作偏好之后', () => {
  const shared = readFileSync(new URL('../src/components/settings/WritingSettings.tsx', import.meta.url), 'utf8')
  const book = readFileSync(new URL('../src/pages/BookSettingsPage.tsx', import.meta.url), 'utf8')
  assert.ok(shared.indexOf('每卷卷纲都要我拍板') < shared.indexOf('每一篇开写前先给我确认'))
  assert.ok(shared.indexOf('每一篇开写前先给我确认') < shared.indexOf('新书前 3 章先给我试读'))
  assert.match(shared, /checked=\{value.segment_approval \?\? true\}/u)
  assert.ok(shared.indexOf('{afterPreferences}') < shared.indexOf('<SettingsGroup title="编辑部力度">'))
  assert.match(book, /afterPreferences=\{<BookLengthSettings/u)
  assert.match(book, /concept: \{ target_length: targetLength \}/u)
  assert.match(book, /disabled=\{working \|\| update.isPending\}/u)
  assert.match(book, /onBlur=\{\(\) => void save\(\)\}/u)
  assert.match(book, /event.key === 'Enter'/u)
  assert.match(book, /编辑部工作时不能改，等这一步做完/u)
})
