import assert from 'node:assert/strict'
import test from 'node:test'
import { decisionCopy } from '../src/lib/decision.ts'
import { nextSegmentFields } from '../src/lib/setupPresentation.ts'
import { isWritingComplete, storyMapNodeChapters, storyMapWritingIndex, writingPosition, writingPositionText } from '../src/lib/storyMap.ts'
import { artifactTarget, composerRoute, currentTarget, pendingTarget, progressText } from '../src/lib/workspace.ts'
import { requirementSource } from '../src/lib/writingSettings.ts'

const pending = { kind: 'segment_review', flow: 3, number: 3, round: 1, warnings: ['上一篇的期待仍然开着。', '人物还没写什么时候登场。'], flags: {}, decisions: [], plan: {}, split: { volumes: [] } }
const job = { id: 'job', kind: 'write_book', status: 'waiting_author', pending }
const message = type => ({ id: 1, job_id: 'job', kind: 'artifact', payload: { type, data: {} } })

test('下一篇确认和写作产出跟随大纲待确认节点，开书分卷跟随大纲树的第一篇', () => {
  assert.deepEqual(pendingTarget(pending, 'book'), { path: '/books/book/outline?node=pending', label: '第 3 篇' })
  assert.deepEqual(artifactTarget(message('segment_plan'), 'book'), { path: '/books/book/outline?node=pending', label: '下一篇' })
  assert.deepEqual(currentTarget('book', job, [], null), pendingTarget(pending, 'book'))
  for (const type of ['segment_plan', 'segment_volumes']) {
    assert.equal(currentTarget('book', { ...job, status: 'running', pending: null }, [message(type)], null).path, '/books/book/outline?node=pending')
  }
  assert.equal(currentTarget('book', { ...job, status: 'running', pending: null }, [{ ...message('segment_plan'), job_id: 'old' }], null), null)
  assert.equal(artifactTarget(message('segment_volumes'), 'book').path, '/books/book/outline?node=first-arc')
  assert.equal(artifactTarget({ ...message('segment_volumes'), payload: { type: 'segment_volumes', data: { volumes: [{ index: 2 }] } } }, 'book').path, '/books/book/outline?node=pending')
})

test('下一篇提意见走专用接口路由，文案、提醒和来源准确', () => {
  assert.deepEqual(composerRoute(job, '保留原地图', null), { kind: 'segment', action: 'revise' })
  assert.deepEqual(composerRoute({ ...job, status: 'running' }, '下次再改', null), { kind: 'note' })
  const copy = decisionCopy(pending, 'book')
  assert.equal(copy.title, '待你确认：第 3 篇')
  assert.equal(copy.approve, '确认这一篇')
  assert.equal(copy.placeholder, '说说下一篇想怎么改…')
  assert.deepEqual(copy.issues, pending.warnings)
  assert.equal(requirementSource('segment:3'), '第 3 篇规划意见')
  assert.equal(progressText({ active_job: job, chapters_final: 0 }, [], null, pendingTarget(pending, 'book')), '等你确认：第 3 篇')
})

test('下一篇会议卡显示本轮快照中的终点、地图、目标和追求，兼容空快照', () => {
  const plan = Object.freeze({ end: Object.freeze({ title: '寒原追查', event: '找到师兄留下的证据' }), map: '北境寒原', goal: '先拿到入城资格', pursuit: '从寻找师兄升级为查清失踪真相', carried: 'E1' })
  assert.deepEqual(nextSegmentFields(plan), [
    { label: '终点', value: '寒原追查：找到师兄留下的证据' }, { label: '地图', value: '北境寒原' },
    { label: '目标', value: '先拿到入城资格' }, { label: '主角的追求', value: '从寻找师兄升级为查清失踪真相' },
  ])
  for (const missing of [null, undefined, {}]) assert.deepEqual(nextSegmentFields(missing), [])
})

test('已规划卷写完仅说明对应段结束；最后一卷确实到结局且写完才全书完结', () => {
  const nodes = [{ id: 'end', index: 4, kind: 'ending', title: '结局' }, { id: 'second', index: 3, kind: 'milestone', segment: { number: 2 } }, { id: 'first', index: 2, kind: 'milestone', segment: { number: 1 } }]
  const volumes = [{ id: 'v2', index: 2, chapter_count: 1, status: 'done', units: [], target_node_id: 'second', reaches_node: true }, { id: 'v1', index: 1, chapter_count: 1, status: 'done', units: [], target_node_id: 'first', reaches_node: true }]
  const chapters = [{ index: 1, volume_id: 'v1', status: 'final' }, { index: 2, volume_id: 'v2', status: 'final' }]
  assert.equal(isWritingComplete(volumes, chapters, nodes), false)
  assert.equal(writingPositionText(writingPosition(nodes, volumes, chapters), volumes, chapters, nodes), '第 2 篇写完了 · 下一篇写到再定')
  assert.match(progressText({ chapters_final: 2, status: 'writing', active_job: null }, [], null, null, { nodes, volumes, chapters }), /第 2 篇写完了 · 下一篇写到再定$/)
  const finalVolumes = [{ ...volumes[0], target_node_id: 'end' }, volumes[1]]
  assert.equal(isWritingComplete(finalVolumes, chapters, nodes), true)
  assert.equal(writingPositionText(writingPosition(nodes, finalVolumes, chapters), finalVolumes, chapters, nodes), '全书完结')
  assert.equal(isWritingComplete(finalVolumes, [chapters[0], { ...chapters[1], status: 'drafting' }], nodes), false)
  assert.equal(isWritingComplete(volumes, chapters, []), true)
})

test('分段书的写作指针停在已规划终点，不越过等高的远景节点和未规划结局', () => {
  const nodes = [
    { id: 'opening', index: 1, kind: 'opening', volume: 1 },
    { id: 'first', index: 2, kind: 'milestone', volume: 1, segment: { number: 1 } },
    { id: 'future', index: 3, kind: 'milestone', volume: 2 },
    { id: 'ending', index: 4, kind: 'ending', volume: 3 },
  ]
  const volumes = [{ id: 'v1', index: 1, chapter_count: 6, units: [], target_node_id: 'first', reaches_node: true }]
  const concept = { target_length: 6, chapter_words: 3000 }
  const positions = storyMapNodeChapters(nodes, volumes, concept)
  assert.deepEqual(positions, [1, 6, 13, 20])
  assert.equal(storyMapWritingIndex(positions, 3, 1), 0.4)
  assert.equal(storyMapWritingIndex(positions, 6, 1), 1)
  assert.equal(storyMapWritingIndex(positions, 8, 1), 1)
  assert.equal(storyMapWritingIndex(storyMapNodeChapters(nodes, [], concept), 0, 0), 0)

  // 新段真正保存了卷卡片才扩展章数轴；只确认但未写章时指针仍在第一篇终点。
  const planned = nodes.map(node => node.id === 'future' ? { ...node, segment: { number: 2 } } : node)
  const nextVolumes = [...volumes, { ...volumes[0], id: 'v2', index: 2, target_node_id: 'future' }]
  const nextPositions = storyMapNodeChapters(planned, nextVolumes, concept)
  assert.deepEqual(nextPositions, [1, 6, 12, 20])
  assert.equal(storyMapWritingIndex(nextPositions, 6), 1)
  assert.equal(storyMapWritingIndex(nextPositions, 7), 1 + 1 / 6)
  assert.equal(storyMapWritingIndex(nextPositions, 12), 2)

  // 结局确实被最终卷走到后才能抵达结局；旧书仍保留原来的完整卷轴推算。
  const finalVolumes = [...nextVolumes, { ...volumes[0], id: 'v3', index: 3, target_node_id: 'ending' }]
  assert.deepEqual(storyMapNodeChapters(planned, finalVolumes), [1, 6, 12, 18])
  assert.equal(storyMapWritingIndex(storyMapNodeChapters(planned, finalVolumes), 18), 3)
  const legacy = nodes.map(({ segment: _segment, ...node }) => node)
  assert.deepEqual(storyMapNodeChapters(legacy, volumes), [1, 6, 6, 6])
  assert.equal(storyMapWritingIndex(storyMapNodeChapters(legacy, volumes), 6), 3)
})
