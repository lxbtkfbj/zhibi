import assert from 'node:assert/strict'
import test from 'node:test'
import { changedText, emotionPoint, emotionText, foreshadowAction, repeatedMoodChapters } from '../src/lib/writingUi.ts'

test('emotion coordinates map -2 to bottom, 0 to center and +2 to top within 32px', () => {
  assert.deepEqual([-2, -1, 0, 1, 2].map(value => emotionPoint(value, 0, 5, 100).y), [28, 22, 16, 10, 4])
  assert.deepEqual(emotionPoint(-2, 0, 5, 100), { x: 4, y: 28 })
  assert.deepEqual(emotionPoint(2, 4, 5, 100), { x: 96, y: 4 })
  assert.deepEqual(emotionPoint(0, 0, 1, 100), { x: 50, y: 16 })
  assert.equal(emotionPoint(0, 1, 3, 400).x, 200)
})

test('missing and invalid old emotion data never becomes a zero point', () => {
  for (const value of [undefined, null, '', '0', NaN, Infinity, -3, 3, 0.5]) {
    assert.equal(emotionPoint(value, 0, 1), null)
    assert.equal(emotionText(value), null)
  }
  assert.equal(emotionPoint(0, 0, 0), null)
  assert.equal(emotionPoint(0, 3, 3), null)
  assert.equal(emotionPoint(0, -1, 3), null)
  assert.equal(emotionText(2), '+2 爆发爽快')
  assert.equal(emotionText(-1), '-1 偏压')
  assert.equal(emotionText(0), '0 平稳或悬着')
})

const chapters = moods => moods.map((mood, index) => ({ id: `c${index + 1}`, index: index + 1, outline: { mood } }))

test('four repeated moods warn the entire run and include longer runs', () => {
  assert.deepEqual([...repeatedMoodChapters(chapters(['爽', '爽', '爽']))], [])
  assert.deepEqual([...repeatedMoodChapters(chapters(['爽', '爽', '爽', '爽', '爽', '悬']))], ['c1', 'c2', 'c3', 'c4', 'c5'])
  assert.deepEqual([...repeatedMoodChapters(chapters(['爽', '爽', '爽', '爽', '悬', '悬', '悬', '悬']))], ['c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8'])
})

test('missing moods and nonconsecutive chapters break the warning run', () => {
  assert.equal(repeatedMoodChapters(chapters(['爽', '爽', undefined, '爽', '爽'])).size, 0)
  const data = chapters(['爽', '爽', '爽', '爽'])
  data[3].index = 5
  assert.equal(repeatedMoodChapters(data).size, 0)
  assert.equal(repeatedMoodChapters(chapters([undefined, undefined, undefined, undefined])).size, 0)
  const unordered = chapters(['虐', '虐', '虐', '虐']).reverse()
  assert.equal(repeatedMoodChapters(unordered).size, 4)
  assert.equal(unordered[0].index, 4)
})

test('E actions read as 立下/提醒/兑现 while F actions preserve 埋下/回收', () => {
  assert.equal(foreshadowAction({ ref: 'E3', action: '埋下', detail: '' }).label, '立下')
  assert.equal(foreshadowAction({ ref: 'E3', action: '提醒', detail: '' }).label, '提醒')
  assert.equal(foreshadowAction({ ref: 'E3', action: '回收', detail: '' }).label, '兑现')
  assert.equal(foreshadowAction({ ref: 'F5', action: '埋下', detail: '' }).label, '埋下')
  assert.equal(foreshadowAction({ ref: 'F5', action: '回收', detail: '' }).label, '回收')
})

test('shared ledger sequence resolves old F prefix to current E number and includes content in hint', () => {
  const ledger = [{ seq: 3, code: 'E3', kind: '期待', description: '三年之约' }]
  assert.deepEqual(foreshadowAction({ ref: 'F3', action: '埋下', detail: '在擂台上立约' }, ledger), { label: '立下', code: 'E3', hint: '三年之约；在擂台上立约' })
  assert.equal(foreshadowAction({ ref: 'E9', action: '回收', detail: '' }).hint, '兑现 E9')
})

test('node comparison preserves unchanged prefix/suffix and marks only edits', () => {
  assert.deepEqual(changedText('主角飞升神界。', '主角登临神界。'), {
    before: { prefix: '主角', changed: '飞升', suffix: '神界。' },
    after: { prefix: '主角', changed: '登临', suffix: '神界。' }, differs: true,
  })
  assert.equal(changedText('一样', '一样').differs, false)
  assert.deepEqual(changedText('', '新节点').after, { prefix: '', changed: '新节点', suffix: '' })
  assert.deepEqual(changedText('旧节点', '').before, { prefix: '', changed: '旧节点', suffix: '' })
  assert.deepEqual(changedText('前后', '前中后').after, { prefix: '前', changed: '中', suffix: '后' })
})
