import assert from 'node:assert/strict'
import test from 'node:test'
import { canPlanNextSegment, isWritingComplete, nextUnplanned, segmentBands, segmentNumber, segmentFinishedText, segments, storyMapNodeChapters, storyMapWritingIndex, writingPosition, writingPositionText, writingSegmentNumber, writingTotalChapters } from '../src/lib/storyMap.ts'
import { progressText } from '../src/lib/workspace.ts'

const plan = (number, status = 'confirmed') => ({ number, status, goal: `第 ${number} 篇的目标` })
const nodes = [
  { id: 'opening', index: 1, kind: 'opening', title: '开篇', segment: null },
  { id: 'first', index: 2, kind: 'milestone', title: '走出山门', segment: plan(1) },
  { id: 'second', index: 3, kind: 'milestone', title: '寒原追查', segment: null },
  { id: 'third', index: 4, kind: 'milestone', title: '王城决战', segment: null },
  { id: 'ending', index: 5, kind: 'ending', title: '结局', segment: null },
]
const volume = (index, target, count = 6) => ({ id: `v${index}`, index, chapter_count: count, units: [], status: 'planned', target_node_id: target, reaches_node: true })
const volumes = [volume(1, 'first')]
const finals = (index, count = 6, start = 1) => Array.from({ length: count }, (_, at) => ({ index: start + at, volume_id: `v${index}`, status: 'final' }))
const concept = { target_length: 36, chapter_words: 3000 }

test('第三包只有title/text的篇按节点顺序编号，地图、写作位置与顶栏一致', () => {
  const fresh = [...nodes].reverse().map(node => node.id === 'first' ? { ...node, segment: { title: '走出山门', text: '救人，离城。' } } : node)
  const before = JSON.stringify(fresh)
  const bands = segmentBands(fresh, volumes, finals(1, 3))
  assert.deepEqual(bands.map(band => [band.to.id, band.number]), [['first', 1], ['second', 2], ['third', 3], ['ending', null]])
  const position = writingPosition(fresh, volumes, finals(1, 3), concept)
  assert.equal(writingSegmentNumber(fresh, volumes, position), 1)
  assert.equal(writingPositionText(position, volumes, finals(1, 3), fresh), '第 1 篇 · 第 1 卷 3/6 章 · 离「走出山门」还有 3 章')
  assert.equal(progressText({ chapters_final: 3, status: 'writing', concept, active_job: null }, [], null, null, { nodes: fresh, volumes, chapters: finals(1, 3) }), '第 1 篇 · 第 1 卷 3/6 章 · 离「走出山门」还有 3 章 · 编辑部空闲')
  assert.equal(segmentFinishedText(fresh, volumes), '第 1 篇写完了 · 下一篇写到再定')
  assert.equal(JSON.stringify(fresh), before)
})

test('旧显式编号原样保留，新篇不按已规划篇的数量错编号，规划到结局后结局篇也编号', () => {
  const mixed = nodes.map(node => node.id === 'first' ? { ...node, segment: { number: 7, title: '旧篇' } } : node.id === 'third' ? { ...node, segment: { title: '王城', text: '取回证物。' } } : node)
  const own = [volume(1, 'first'), volume(3, 'third')]
  assert.equal(segmentNumber(mixed, 'first'), 7)
  assert.equal(segmentNumber(mixed, 'third'), 3)
  assert.equal(segmentFinishedText(mixed, own), '第 3 篇写完了 · 下一篇写到再定')
  assert.equal(segmentNumber(mixed, 'opening'), null)
  assert.equal(segmentNumber(mixed, 'ending'), null)
  const finale = mixed.map(node => node.kind === 'ending' ? { ...node, segment: { title: '终章', text: '所有人归家。' } } : node)
  assert.equal(segmentBands(finale, own, []).at(-1).number, 4)
  assert.equal(writingSegmentNumber(finale, [volume(4, 'ending')], { volume: 4 }), 4)
  assert.equal(segmentFinishedText(finale, [volume(4, 'ending')]), '第 4 篇写完了 · 下一篇写到再定')
  assert.equal(segmentNumber(nodes.map(node => ({ ...node, segment: null })), 'first'), null)
})

test('节点还没载入时只报实际章数，不误称最后一篇、全书完结或第0篇', () => {
  for (const chapters of [finals(1, 3), finals(1)]) {
    const position = writingPosition([], volumes, chapters, concept)
    assert.equal(writingPositionText(position, volumes, chapters, []), `第 1 卷 ${chapters.length}/6 章 · 已定稿 ${chapters.length} 章`)
    const progress = progressText({ chapters_final: chapters.length, status: 'writing', concept, active_job: null }, [], null, null, { nodes: [], volumes, chapters })
    assert.equal(progress, `第 1 卷 · 已定稿 ${chapters.length} 章 · 编辑部空闲`)
    assert.doesNotMatch(progress, /最后一篇|全书完结|第 0 篇/)
  }
})

test('开书刚完成时第一篇已规划，后续段写到再定，输入排序不变', () => {
  const input = Object.freeze([...nodes].reverse().map(Object.freeze))
  const result = segmentBands(input, volumes, [])
  assert.deepEqual(result.map(band => [band.from.id, band.to.id, band.number, band.status, band.chapters]), [
    ['opening', 'first', 1, 'planned', 6], ['first', 'second', 2, 'later', 0],
    ['second', 'third', 3, 'later', 0], ['third', 'ending', null, 'later', 0],
  ])
  assert.equal(result[0].plan, nodes[1].segment)
  assert.equal(result[0].auto, false)
  assert.equal(nextUnplanned(result), result[1])
  assert.equal(input[0].id, 'ending')
})

test('一段中有正在写或定稿章才算正在写，预生成章纲不算开写', () => {
  for (const status of ['drafting', 'final']) assert.equal(segmentBands(nodes, volumes, [{ volume_id: 'v1', status }])[0].status, 'writing')
  assert.equal(segmentBands(nodes, volumes, [{ volume_id: 'v1', status: 'planned' }])[0].status, 'planned')
  assert.equal(segmentBands(nodes, volumes, finals(1, 3))[0].status, 'writing')
})

test('第一篇写完下一篇未定，以及第二段保存但尚未开写，状态明确区分', () => {
  assert.deepEqual(segmentBands(nodes, volumes, finals(1)).map(band => band.status), ['done', 'later', 'later', 'later'])
  const plannedNodes = nodes.map(node => node.id === 'second' ? { ...node, segment: plan(2) } : node)
  const plannedVolumes = [...volumes, volume(2, 'second')]
  const bands = segmentBands(plannedNodes, plannedVolumes, finals(1))
  assert.deepEqual(bands.map(band => band.status), ['done', 'planned', 'later', 'later'])
  assert.equal(nextUnplanned(bands).to.id, 'third')
  assert.equal(writingSegmentNumber(plannedNodes, plannedVolumes, writingPosition(plannedNodes, plannedVolumes, finals(1))), 2)
})

test('自动通过与完成状态独立，多卷段须全部写完；重写的 done 卷不误报', () => {
  const autoNodes = nodes.map(node => node.id === 'first' ? { ...node, segment: plan(1, 'auto') } : node)
  const twoVolumes = [{ ...volume(1, 'first', 2), reaches_node: false }, { ...volume(2, 'first'), units: [{ chapter_count: 3 }, { chapter_count: 2 }] }]
  const chapters = [...finals(1, 2), ...finals(2, 4, 3)]
  assert.equal(segmentBands(autoNodes, twoVolumes, chapters)[0].status, 'writing')
  assert.equal(segmentBands(autoNodes, twoVolumes, chapters)[0].chapters, 7)
  const completed = segmentBands(autoNodes, twoVolumes, [...chapters, ...finals(2, 1, 7)])[0]
  assert.equal(completed.status, 'done')
  assert.equal(completed.auto, true)
  assert.equal(segmentBands(autoNodes, twoVolumes.map(item => ({ ...item, status: 'done' })), [...chapters, { index: 7, volume_id: 'v2', status: 'drafting' }])[0].status, 'writing')
  assert.equal(segmentBands(autoNodes, [], [])[0].status, 'planned')
})

test('规划到结局后没有下一篇；旧书留在原 segments 路径', () => {
  const plannedNodes = nodes.map((node, index) => index ? { ...node, segment: plan(index) } : node)
  assert.equal(nextUnplanned(segmentBands(plannedNodes, volumes, [])), null)
  assert.equal(nextUnplanned([]), null)
  const legacy = nodes.map(({ segment: _segment, ...node }) => node)
  assert.deepEqual(segmentBands(legacy, volumes, []), [])
  assert.equal(segments(legacy, volumes)[0].chapters, 6)
})

test('全书总章数取概念与已规划卷较大值，ratio 不把第一篇当整本书', () => {
  assert.equal(writingTotalChapters(nodes, volumes, concept), 120)
  assert.equal(writingPosition(nodes, volumes, finals(1, 3), concept).ratio, 3 / 120)
  assert.equal(writingTotalChapters(nodes, [volume(1, 'first', 150)], concept), 150)
  assert.equal(writingTotalChapters(nodes, volumes, { target_length: 36 }), 120)
  assert.equal(writingTotalChapters(nodes, volumes, undefined), 6)
  assert.equal(writingTotalChapters([], volumes, concept), 6)
  assert.equal(writingPosition([], volumes, finals(1, 3), concept).ratio, 0.5)
})

test('最后已规划终点之后的未规划节点均分剩余篇幅，结局放在全书总章数', () => {
  const positions = storyMapNodeChapters(nodes, volumes, concept)
  assert.deepEqual(positions, [1, 6, 44, 82, 120])
  assert.equal(storyMapWritingIndex(positions, 3, 1), 0.4)
  assert.equal(storyMapWritingIndex(positions, 6, 1), 1)
  const plannedNodes = nodes.map(node => node.id === 'second' ? { ...node, segment: plan(2) } : node)
  assert.deepEqual(storyMapNodeChapters(plannedNodes, [...volumes, volume(2, 'second', 14)], concept), [1, 6, 20, 70, 120])
  // 作者缩短篇幅时也不能把同点的未来节点标成已经走到。
  const shortened = storyMapNodeChapters(nodes, volumes, { target_length: 0.3, chapter_words: 3000 })
  assert.deepEqual(shortened, [1, 6, 6, 6, 6])
  assert.equal(storyMapWritingIndex(shortened, 6, 1), 1)
  const legacy = nodes.map(({ segment: _segment, ...node }) => node)
  assert.deepEqual(storyMapNodeChapters(legacy, volumes, concept), storyMapNodeChapters(legacy, volumes))
})

test('分段位置文字带段号、段末不冒充完结，旧书文字不变', () => {
  const chapters = finals(1, 3)
  assert.equal(writingPositionText(writingPosition(nodes, volumes, chapters, concept), volumes, chapters, nodes), '第 1 篇 · 第 1 卷 3/6 章 · 离「走出山门」还有 3 章')
  assert.equal(writingPositionText(writingPosition(nodes, volumes, finals(1), concept), volumes, finals(1), nodes), '第 1 篇写完了 · 下一篇写到再定')
  const legacy = nodes.map(({ segment: _segment, ...node }) => node)
  assert.equal(writingPositionText(writingPosition(legacy, volumes, chapters, concept), volumes, chapters, legacy), '第 1 卷 3/6 章 · 离「走出山门」还有 3 章')
  const endingNodes = nodes.map(node => node.id === 'ending' ? { ...node, segment: plan(2) } : node)
  const finalVolumes = [...volumes, volume(2, 'ending')]
  const all = [...finals(1), ...finals(2, 6, 7)]
  assert.equal(writingPositionText(writingPosition(endingNodes, finalVolumes, all, concept), finalVolumes, all, endingNodes), '全书完结')
})

test('现在就规划下一篇只在首个未规划段、可写状态、编辑部完全空闲时出现', () => {
  const bands = segmentBands(nodes, volumes, [])
  for (const book of ['ready', 'writing']) for (const job of [null, undefined, 'succeeded', 'failed', 'cancelled']) assert.equal(canPlanNextSegment(book, job, bands, 'second'), true)
  for (const job of ['queued', 'running', 'waiting_author']) assert.equal(canPlanNextSegment('writing', job, bands, 'second'), false)
  for (const book of ['setting_up', 'awaiting_approval', 'completed']) assert.equal(canPlanNextSegment(book, null, bands, 'second'), false)
  for (const id of ['opening', 'first', 'third', 'ending']) assert.equal(canPlanNextSegment('writing', null, bands, id), false)
  assert.equal(canPlanNextSegment('ready', null, [], 'second'), false)
  // 收尾规划可直接沿用结局，作者保留在中间的远景节点不应再次提供规划入口。
  const finale = nodes.map(node => node.kind === 'ending' ? { ...node, segment: plan(2) } : node)
  assert.equal(canPlanNextSegment('writing', null, segmentBands(finale, [...volumes, volume(2, 'ending')], []), 'second'), false)
})

test('实际完成全书时地图游标抵达结局，但计划篇幅的 ratio 仍按较大值计算', () => {
  const finaleNodes = nodes.map(node => node.kind === 'ending' ? { ...node, segment: plan(2) } : node)
  const finalVolumes = [...volumes, volume(2, 'ending', 12)]
  const chapters = [...finals(1), ...finals(2, 12, 7)]
  const intended = { target_length: 100, chapter_words: 3000 }
  const axis = storyMapNodeChapters(finaleNodes, finalVolumes, intended)
  assert.equal(axis.at(-1), 333)
  assert.equal(writingPosition(finaleNodes, finalVolumes, chapters, intended).ratio, 18 / 333)
  assert.equal(storyMapWritingIndex(axis, 18, axis.length - 1, isWritingComplete(finalVolumes, chapters, finaleNodes)), axis.length - 1)
  const drafting = chapters.map(chapter => chapter.index === 18 ? { ...chapter, status: 'drafting' } : chapter)
  assert.ok(storyMapWritingIndex(axis, 17, axis.length - 1, isWritingComplete(finalVolumes, drafting, finaleNodes)) < axis.length - 1)
  assert.equal(storyMapWritingIndex([], 0, 0, true), 0)
})
