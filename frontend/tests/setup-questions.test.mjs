import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { SETUP_QUESTIONS, hasAnswer, questionFlags, questionWhen, showLaterPlaceholder } from '../src/lib/setupQuestions.ts'
import { splitStageLadder } from '../src/lib/stageLadder.ts'

const expected = {
  concept: [['positioning', '写给谁看？'], ['logline', '一句话讲什么？'], ['selling_points', '读者会为哪种场面叫好？'], ['core_loop', '主角每个单元反复做什么？'], ['tone', '读起来什么味道？'], ['length_title', '写多长、叫什么？']],
  protagonist: [['start', '他从哪里起步？'], ['drive', '他为什么要往前走？'], ['person', '他是个什么样的人？'], ['finger', '他凭什么走得动？'], ['flaw_arc', '他的软肋是什么，最后变成谁？'], ['cared', '他在乎谁？'], ['interlock', '三件套咬得上吗？']],
  world: [['surface', '超凡的力量是明是暗？'], ['power', '升级靠什么？'], ['first_map', '第一张地图上谁说了算？'], ['opponents', '主角和谁打？'], ['people', '他身边有谁？'], ['shadows', '远处还有什么？']],
  segment: [['opening', '开篇怎么开？'], ['goal', '这一段主角想做成什么？'], ['wait', '这一段让读者等什么？'], ['reveal', '这一段揭开什么？'], ['end', '这一段走到哪里结束？'], ['cast', '人物什么时候登场？'], ['volumes', '这一段分几卷？'], ['direction', '结局大概往哪去？']],
  first_volume: [['want', '这一卷想做成什么？'], ['pressure', '卷首主角被什么压着？'], ['climax', '卷末最大的场面是什么、结果如何？'], ['rival', '这一卷和谁斗？'], ['units', '这一卷拆成哪些剧情单元？'], ['growth', '主角这一卷长了什么？'], ['newcomers', '谁第一次登场？'], ['landing', '开篇落在哪里？']],
}

test('五块的题目键、问题文字和顺序逐字符合任务 2 第 2 节，不混入任务 5', () => {
  assert.deepEqual(Object.fromEntries(Object.entries(SETUP_QUESTIONS).map(([piece, questions]) => [piece, questions.map(({ key, title }) => [key, title])])), expected)
  const document = readFileSync(new URL('../../docs/codex任务/第二包/2-开书新五步.md', import.meta.url), 'utf8')
  const table = document.split('## 2. 必答题表')[1].split('\n## 3.')[0]
  const rows = table.split('\n').filter(line => /^\| (concept|protagonist|world|segment|first_volume) \|/u.test(line)).map(line => line.split('|').slice(1, -1).map(value => value.trim()))
  assert.equal(rows.length, Object.values(expected).flat().length)
  for (const [piece, key, title, , , focus] of rows) {
    const question = SETUP_QUESTIONS[piece].find(question => question.key === key)
    assert.equal(question?.title, title)
    assert.equal(question?.focus, focus === '★')
  }
})

test('同节全为开写前时用标题标签，混合项只在各项标明时间，每块二到三道重点看', () => {
  for (const questions of Object.values(SETUP_QUESTIONS)) {
    assert.ok([2, 3].includes(questions.filter(question => question.focus).length))
    for (const question of questions) {
      assert.ok(question.rows.length > 0)
      for (const row of question.rows) assert.ok(row.name && ['before', 'later'].includes(row.when))
    }
  }
  assert.equal(questionWhen(SETUP_QUESTIONS.protagonist.find(question => question.key === 'drive')), null)
  assert.equal(questionWhen(SETUP_QUESTIONS.protagonist.find(question => question.key === 'finger')), null)
  assert.equal(questionWhen(SETUP_QUESTIONS.concept[0]), 'before')
  assert.equal(questionWhen(SETUP_QUESTIONS.segment.at(-1)), null)
})

test('写到再定的空字符串、空对象、空列表显示占位，有正文后正常显示，不把开写前误当远期', () => {
  for (const value of [undefined, null, '', ' \n ', [], {}, [{ name: '', line: ' ' }]]) {
    assert.equal(hasAnswer(value), false)
    assert.equal(showLaterPlaceholder('later', value), true)
    assert.equal(showLaterPlaceholder('before', value), false)
  }
  for (const value of ['已有后期能力', [{ name: '京城', line: '' }], { answer: '谜底' }, 0]) assert.equal(showLaterPlaceholder('later', value), false)
})

test('flags 只归到当前等待块已有的题，其他块、未知键和其他等待种类不泄漏', () => {
  const pending = { kind: 'setup_piece', piece: 'protagonist', flags: { drive: ['要有具体动机', '再检查追求', ''], person: ['性格过于抽象'], unknown: ['不应出现'] } }
  assert.deepEqual(questionFlags('protagonist', 'drive', pending), ['要有具体动机', '再检查追求'])
  assert.deepEqual(questionFlags('protagonist', 'person', pending), ['性格过于抽象'])
  assert.deepEqual(questionFlags('protagonist', 'finger', pending), [])
  assert.deepEqual(questionFlags('concept', 'drive', pending), [])
  assert.deepEqual(questionFlags('protagonist', 'unknown', pending), [])
  assert.deepEqual(questionFlags('protagonist', 'drive', { ...pending, kind: 'setup_review' }), [])
  assert.deepEqual(questionFlags('protagonist', 'drive', null), [])
})

test('舞台阶梯认识四种箭头，空项不生成台阶，一层和空值自然退化', () => {
  for (const arrow of ['→', '->', '—>', '＞']) assert.deepEqual(splitStageLadder(`青石镇 ${arrow} 京城 ${arrow} 天外`), ['青石镇', '京城', '天外'])
  assert.deepEqual(splitStageLadder('青石镇 → 京城 -> 边关 —> 天外 ＞ 归乡'), ['青石镇', '京城', '边关', '天外', '归乡'])
  assert.deepEqual(splitStageLadder(' → 青石镇 → → '), ['青石镇'])
  assert.deepEqual(splitStageLadder('一张地图'), ['一张地图'])
  for (const value of ['', ' ', null, undefined]) assert.deepEqual(splitStageLadder(value), [])
})

test('事实表各行共享本表最长名称列，上限 9em，窄稿件栏保持上下排列', () => {
  const css = readFileSync(new URL('../src/components/setupQuestions.css', import.meta.url), 'utf8')
  assert.match(css, /\.setup-facts \{[^}]*grid-template-columns: fit-content\(9em\) minmax\(0, 1fr\)/u)
  assert.match(css, /\.setup-fact-row \{[^}]*grid-template-columns: subgrid/u)
  assert.match(css, /\.setup-fact-row > dt \{[^}]*max-width: 9em/u)
  assert.match(css, /@container manuscript \(width < 480px\) \{\s*\.setup-facts \{ grid-template-columns: minmax\(0, 1fr\); \}/u)
  assert.match(css, /\.setup-fact-row \{ grid-template-columns: minmax\(0, 1fr\); gap: \.5rem; \}/u)
})
