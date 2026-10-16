import assert from 'node:assert/strict'
import test from 'node:test'
import { LATER_ANSWER, LEGACY_SETUP_NOTICE, needsSetupRestart, protagonistFields, segmentFields, setupOverviewStats, worldFields } from '../src/lib/setupPresentation.ts'
import { isWritingComplete, targetPiece, writingPosition, writingPositionText } from '../src/lib/storyMap.ts'
import { progressText } from '../src/lib/workspace.ts'

test('主角简版逐项显示，两个写到再定字段保留未来问题，作者内容原样显示', () => {
  const card = Object.freeze({ name: '陆远', trigger: '救妹妹', pursuit: '找到妹妹', root: '亏欠', finger: '青灯', cared: [{ name: '妹妹', relation: '亲人', why: '彼此依靠' }], interlock: '解谜推动寻找' })
  const fields = protagonistFields(card)
  assert.deepEqual(fields.map(item => item.label), ['姓名', '起点', '开局动机', '长线追求', '情感根源', '怎么升级', '性格', '做事风格', '底线', '说话方式', '金手指·现在', '金手指·以后', '软肋', '成长的终点', '在乎的人', '三件套怎么咬合'])
  assert.equal(fields.filter(item => item.value === LATER_ANSWER).length, 2)
  assert.equal(fields.find(item => item.label === '在乎的人').value, '妹妹（亲人：彼此依靠）')
  assert.equal(protagonistFields({ ...card, escalation: '去京城找线索', finger_later: '看见前世' }).some(item => item.value === LATER_ANSWER), false)
})

test('世界标题与 format_world 同名，完整保留地图及谜面谜底，兼容模型 first_map 快照', () => {
  const map = { name: '青石镇', powers: '镇守', ceiling: '镇守最强', rules: '夜不出门', start: '杂役', gains: '线索' }
  const world = Object.freeze({ surface: '力量公开', power: '修炼', maps: [map], trouble: '催债', opponent: '镇守', far_maps: [{ name: '京城', line: '贵人云集' }, { name: '边关' }], shadow: '暗中的大手', mystery: '妹妹去了哪里', mystery_answer: '北方' })
  const fields = worldFields(world)
  assert.deepEqual(fields.map(item => item.label), ['世界的表里', '力量规则', '地图「青石镇」', '第一段·开篇的小麻烦', '第一段·大对手', '后面的地图', '终极敌人的影子', '核心谜团'])
  assert.equal(fields[2].value, '谁说了算：镇守\n天花板：镇守最强\n特有的规矩：夜不出门\n主角从这里起步：杂役\n能拿到：线索')
  assert.equal(fields[5].value, '京城（贵人云集） → 边关')
  assert.equal(fields[7].value, '谜面：妹妹去了哪里\n谜底：北方')
  assert.equal(worldFields({ first_map: map })[2].value, fields[2].value)
})

test('第一段快照既能读原始产出也能读节点 segment，旧的空消息不报错', () => {
  const segment = { goal: '通过考核', goal_link: '进入档案库找妹妹', wait: { description: '三个月后考核' }, opening: { scene: '遭到催债', pressure: '交不起钱' }, reveal: '拿到信封' }
  assert.deepEqual(segmentFields(segment), segmentFields({ nodes: [{ kind: 'opening' }, { segment }] }))
  assert.equal(segmentFields({ ...segment, wait: '等考核' }).find(item => item.label === '让读者等什么').value, '等考核')
  for (const data of [undefined, null, {}, { nodes: [null, {}] }]) {
    assert.doesNotThrow(() => protagonistFields(data))
    assert.doesNotThrow(() => worldFields(data))
    assert.deepEqual(segmentFields(data), [])
  }
  assert.deepEqual(targetPiece, { concept: 'concept', protagonist: 'protagonist', world: 'world', segment: 'segment', volumes: 'segment', first_volume: 'first_volume' })
})

test('旧任务只在开书中的等待、失败、已停止状态显示重开，不让旧书或新流程误重开', () => {
  const job = { kind: 'book_setup', setup_flow: 1 }
  for (const status of ['setting_up', 'awaiting_approval']) for (const state of ['waiting_author', 'failed', 'cancelled']) assert.equal(needsSetupRestart({ status }, { ...job, status: state }), true)
  for (const status of ['queued', 'running', 'succeeded']) assert.equal(needsSetupRestart({ status: 'setting_up' }, { ...job, status }), false)
  for (const status of ['ready', 'writing', 'completed']) assert.equal(needsSetupRestart({ status }, { ...job, status: 'failed' }), false)
  for (const setup_flow of [null, 2]) assert.equal(needsSetupRestart({ status: 'setting_up' }, { ...job, setup_flow, status: 'failed' }), false)
  assert.equal(needsSetupRestart({ status: 'setting_up' }, null), false)
  assert.equal(LEGACY_SETUP_NOTICE, '这个开书任务是按旧流程开的，开书流程已经更新。请点「按新流程重开」：保留你的点子、作者要求、已选的方向和已确认的定调，其余按新步骤重做。')
})

test('新书第一段写完但未到结局时不显示全书完结，旧书与真正结局照旧', () => {
  const nodes = [{ id: 'opening', kind: 'opening', index: 1 }, { id: 'end', kind: 'milestone', index: 2, segment: { number: 1 } }, { id: 'final', kind: 'ending', index: 3 }]
  const volumes = [{ id: 'v1', index: 1, chapter_count: 1, units: [], status: 'done', target_node_id: 'end', reaches_node: true }]
  const chapters = [{ id: 'c1', index: 1, volume_id: 'v1', status: 'final' }]
  assert.equal(isWritingComplete(volumes, chapters, nodes), false)
  assert.equal(isWritingComplete(volumes, chapters), true)
  assert.equal(isWritingComplete([{ ...volumes[0], target_node_id: 'final' }], chapters, nodes), true)
  assert.equal(writingPositionText(writingPosition(nodes, volumes, chapters), volumes, chapters, nodes), '第 1 段写完了 · 下一段写到再定')
  assert.equal(progressText({ chapters_final: 1, status: 'writing', active_job: null }, [], null, null, { nodes, volumes, chapters }), '第 1 段写完了 · 下一段写到再定')
})


test('分段书只统计已规划卷，全书约章数来自概念；旧书仍按完整卷卡统计', () => {
  const concept = { target_length: 200, chapter_words: 3000 }
  const volumes = [{ chapter_count: 31 }, { chapter_count: 30 }]
  assert.deepEqual(setupOverviewStats(concept, volumes, [{ segment: { number: 1 } }]), { segmented: true, volumeLabel: '已规划 2 卷', chapters: 667 })
  assert.deepEqual(setupOverviewStats(concept, volumes, [{ segment: null }, { segment: {} }]), { segmented: false, volumeLabel: '全书 2 卷', chapters: 61 })
  assert.equal(setupOverviewStats({}, volumes, [{ segment: { number: 1 } }]).chapters, 0)
})
