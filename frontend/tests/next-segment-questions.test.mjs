import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { NEXT_SEGMENT_QUESTIONS, nextSegmentQuestionFlags, segmentReviewKey } from '../src/lib/nextSegmentQuestions.ts'
import { questionWhen } from '../src/lib/setupQuestions.ts'

test('定下一段十四题键、题目、顺序和重点看逐字对应任务 4 第 3.5 节', () => {
  const task = readFileSync(new URL('../../docs/codex任务/第二包/4-定下一段.md', import.meta.url), 'utf8')
  const table = task.split('### 3.5 ')[1].split('检查（文字逐字照抄）')[0]
  const expected = table.split('\n').filter(line => /^\| [a-z_]+ \|/.test(line)).map(line => {
    const [, key, title, focus] = line.split('|').map(cell => cell.trim())
    return { key, title, focus: focus === '★' }
  })
  assert.equal(expected.length, 14)
  assert.deepEqual(NEXT_SEGMENT_QUESTIONS.map(({ key, title, focus }) => ({ key, title, focus })), expected)
  assert.deepEqual(NEXT_SEGMENT_QUESTIONS.filter(question => question.focus).map(question => question.key), ['pursuit', 'goal', 'end'])
  assert.ok(NEXT_SEGMENT_QUESTIONS.every(question => questionWhen(question) === 'before'))
})

test('下一段提醒只能出现在对应题，开书、其他状态或未知键不串入', () => {
  const pending = { kind: 'segment_review', number: 2, round: 1, flags: { carried: ['E1 还开着。', '', '  '], end: ['还没写之前得先有。'], unknown: ['不要显示'] } }
  assert.deepEqual(nextSegmentQuestionFlags('carried', pending), ['E1 还开着。'])
  assert.deepEqual(nextSegmentQuestionFlags('end', pending), ['还没写之前得先有。'])
  assert.deepEqual(nextSegmentQuestionFlags('goal', pending), [])
  assert.deepEqual(nextSegmentQuestionFlags('unknown', pending), [])
  assert.deepEqual(nextSegmentQuestionFlags('end', { ...pending, kind: 'setup_piece' }), [])
  assert.deepEqual(nextSegmentQuestionFlags('end', null), [])
})

test('钉死选择的身份边界包含任务、段号和轮次，离开待确认稿失效', () => {
  const pending = { kind: 'segment_review', number: 2, round: 1 }
  assert.equal(segmentReviewKey('a', pending), 'a:2:1')
  for (const key of [segmentReviewKey('b', pending), segmentReviewKey('a', { ...pending, number: 3 }), segmentReviewKey('a', { ...pending, round: 2 }), segmentReviewKey('a', null)]) assert.notEqual(key, 'a:2:1')
  assert.equal(segmentReviewKey('a', { kind: 'volume_review' }), '')
})
