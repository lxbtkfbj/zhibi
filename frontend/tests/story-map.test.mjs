import assert from 'node:assert/strict'
import test from 'node:test'
import { directionsArtifact, loreArtifact, NODE_STATUS, outlineArtifact, spineArtifactNodes } from '../src/lib/storyMap.ts'

test('historical spine cards preserve opening, sorted milestones, and ending without mutation', () => {
  const milestones = Object.freeze([
    Object.freeze({ index: 2, title: '第二转折', event: '发现真相', volume: 3, change: '旧结果' }),
    Object.freeze({ index: 1, title: '第一转折', event: '离开家乡', volume: 1 }),
  ])
  const old = Object.freeze({ opening: '旧开篇', milestones, ending: '旧结局' })
  assert.deepEqual(spineArtifactNodes(old), [
    { kind: 'opening', title: '开篇', event: '旧开篇', volume: null },
    { kind: 'milestone', title: '第一转折', event: '离开家乡', volume: 1 },
    { kind: 'milestone', title: '第二转折', event: '发现真相', volume: 3, consequence: '旧结果' },
    { kind: 'ending', title: '结局', event: '旧结局', volume: null },
  ])
  assert.equal(milestones[0].index, 2)
})

test('new spine cards use ordered nodes and tolerate empty node fields', () => {
  assert.deepEqual(spineArtifactNodes({ opening: '不应重复显示的旧开篇', nodes: [
    { kind: 'opening', title: '新的开始', event: '第一幕', volume: 1 },
    { kind: 'milestone', status: 'empty' },
    { kind: 'ending', event: '最后一幕' },
  ] }), [
    { kind: 'opening', title: '新的开始', event: '第一幕', volume: 1 },
    { kind: 'milestone', title: '（未命名节点）', event: '', volume: null },
    { kind: 'ending', title: '结局', event: '最后一幕', volume: null },
  ])
})

test('missing historical fields and malformed empty payloads never crash', () => {
  for (const input of [undefined, null, {}, { milestones: null }, { nodes: [] }]) assert.deepEqual(spineArtifactNodes(input), [])
  assert.equal(spineArtifactNodes({ milestones: [{ title: '只有转折' }] })[0].title, '只有转折')
  assert.deepEqual(spineArtifactNodes({ ending: '只有结局' }).map(node => node.kind), ['ending'])
  assert.doesNotThrow(() => spineArtifactNodes({ nodes: [null, {}] }))
})

test('three node statuses have the agreed Chinese labels', () => {
  assert.deepEqual(NODE_STATUS, { pinned: '铁钉', pencil: '暂定', empty: '留空' })
})

test('new spine supports AI Chinese kinds, prerequisites, and consequences', () => {
  assert.deepEqual(spineArtifactNodes({ nodes: [{ kind: '开篇', title: '初见', prerequisite: '', consequence: '主角决定出发' }, { kind: '节点', title: '归来', prerequisite: '修为足够', consequence: '宗门易主' }, { kind: '结局', title: '终局' }] }).map(n => [n.kind, n.prerequisite, n.consequence]), [
    ['opening', undefined, '主角决定出发'], ['milestone', '修为足够', '宗门易主'], ['ending', undefined, undefined],
  ])
})

test('lore snapshots show anchors and both draft and persisted knowers', () => {
  const lore = loreArtifact({ characters: [{ name: '林岚', role_type: '主角' }], anchors: [{ character: '林岚', node: 3, kind: '登场', note: '山门初遇' }], secrets: [{ seq: 2, title: '血脉', truth: '世家后人', knowers: ['林岚', { name: '师尊', how: '开书设定' }, null], reader_knows: '部分' }] })
  assert.equal(lore.anchors[0].node, 3)
  assert.deepEqual(lore.secrets[0].knowers, ['林岚', '师尊'])
  assert.equal(lore.secrets[0].code, 'S2')
  assert.equal(lore.characters[0].abilities, '')
})

test('outline snapshots preserve target node and E codes without inventing missing numbers', () => {
  const outline = outlineArtifact({ volumes: [{ index: 2, title: '入山', target_node: 4, reaches_node: true }], foreshadowings: [{ seq: 1 }], expectations: [{ seq: 2, description: '三年之约', plant_volume: 1, payoff_volume: 3 }, { description: '未编号期待' }] })
  assert.equal(outline.volumes[0].target_node, 4)
  assert.equal(outline.volumes[0].reaches_node, true)
  assert.equal(outline.foreshadowings[0].code, 'F1')
  assert.deepEqual(outline.expectations.map(f => f.code), ['E2', ''])
})

test('directions snapshots keep the three distinct direction summaries', () => {
  const directions = directionsArtifact({ directions: ['青灯', '古镜', '剑修'].map(name => ({ name, logline: `${name}的故事`, selling_points: ['悬念', '成长'] })) })
  assert.deepEqual(directions.map(d => d.name), ['青灯', '古镜', '剑修'])
  assert.deepEqual(directions[0].selling_points, ['悬念', '成长'])
})

test('old and missing lore, outline, directions fields remain displayable', () => {
  for (const data of [null, undefined, {}, { characters: null, volumes: null, directions: null }, { characters: [null], secrets: [null], anchors: [null], volumes: [null], directions: [null] }]) {
    assert.deepEqual(loreArtifact(data), { characters: [], world_entries: [], anchors: [], secrets: [] })
    assert.deepEqual(outlineArtifact(data), { volumes: [], foreshadowings: [], expectations: [] })
    assert.deepEqual(directionsArtifact(data), [])
  }
  assert.deepEqual(loreArtifact({ characters: [{ name: '旧人物', secrets: ['旧秘密'] }], world_entries: [{ name: '旧世界' }] }).characters.map(c => c.name), ['旧人物'])
})

import { PIECES, nodeCounts, pieceStatuses, segments } from '../src/lib/storyMap.ts'
import { isWritingComplete, plannedVolumeChapters, storyMapNodeChapters, storyMapWritingIndex, visibleStoryMapNodes, writingPosition, writingPositionText } from '../src/lib/storyMap.ts'

test('all five puzzle pieces have stable keys and destination paths', () => {
  assert.deepEqual(PIECES.map(({key,path}) => [key,path]), [['concept','/concept'],['nodes','/spine'],['cast','/characters'],['fill','/spine'],['first_volume','/volume/1']])
})
test('piece statuses preserve confirmed, current, oneshot-done and missing legacy states', () => {
  const result = pieceStatuses({current:'nodes',pieces:{concept:'confirmed',nodes:'waiting',fill:'done'}})
  assert.equal(result.current,'nodes')
  assert.deepEqual(result.pieces.map(piece=>piece.status),['confirmed','waiting','todo','done','todo'])
  assert.equal(result.pieces.filter(piece=>piece.current).length,1)
  assert.deepEqual(pieceStatuses(undefined).pieces.map(piece=>piece.status), Array(5).fill('todo'))
})
test('node counts distinguish pins, pencil drafts and genuinely empty slots', () => {
  assert.deepEqual(nodeCounts([{status:'pinned'},{status:'pencil'},{status:'empty'},{status:'pinned'}]),{total:4,pinned:2,pencil:1,empty:1})
  assert.deepEqual(nodeCounts([]),{total:0,pinned:0,pencil:0,empty:0})
})
test('segments assign volumes to target intervals; unmapped legacy volumes remain in last segment', () => {
  const nodes=[{id:'end',index:3},{id:'start',index:1},{id:'middle',index:2}]
  const volumes=[{id:'v3',index:3,target_node_id:null,chapter_count:20},{id:'v2',index:2,target_node_id:'end',chapter_count:50},{id:'v1',index:1,target_node_id:'middle',chapter_count:40},{id:'v4',index:4,target_node_id:'removed',chapter_count:15}]
  const before=JSON.stringify([nodes,volumes])
  const result=segments(nodes,volumes)
  assert.deepEqual(result.map(s=>[s.from.id,s.to.id,s.volumes.map(v=>v.index),s.chapters,s.unassigned]),[['start','middle',[1],40,false],['middle','end',[2,3,4],85,true]])
  assert.deepEqual(result[1].unassignedVolumes.map(v=>v.index),[3,4])
  assert.equal(JSON.stringify([nodes,volumes]),before)
})
test('segments preserve volumes even without a node map and handle no volumes', () => {
  assert.deepEqual(segments([],[]),[])
  const result=segments([],[{id:'v1',index:1,target_node_id:null,chapter_count:30}])
  assert.equal(result[0].from,null)
  assert.equal(result[0].to,null)
  assert.equal(result[0].chapters,30)
  assert.equal(result[0].unassigned,true)
})

test('new artifact annotations survive while absent historical metadata remains absent', () => {
  const annotation = { editor_note: '让读者先看到希望', techniques: ['欲扬先抑'] }
  const node = spineArtifactNodes({ nodes: [{ title: '破局', ...annotation }] })[0]
  const volume = outlineArtifact({ volumes: [{ title: '出山', ...annotation }] }).volumes[0]
  const direction = directionsArtifact({ directions: [{ name: '重来', ...annotation }] })[0]
  for (const item of [node, volume, direction]) {
    assert.equal(item.editor_note, annotation.editor_note)
    assert.deepEqual(item.techniques, annotation.techniques)
  }
  assert.equal(Object.hasOwn(spineArtifactNodes({ nodes: [{ title: '旧稿' }] })[0], 'editor_note'), false)
})

const mapNodes = [
  { id: 'opening', index: 1, kind: 'opening', title: '山村初醒', volume: 1 },
  { id: 'ascend', index: 2, kind: 'milestone', title: '飞升神界', volume: 2 },
  { id: 'ending', index: 3, kind: 'ending', title: '终局', volume: 3 },
]
const mapVolumes = [
  { id: 'v1', index: 1, chapter_count: 10, units: [{ chapter_count: 3 }, { chapter_count: 3 }], target_node_id: 'ascend', reaches_node: false, status: 'approved' },
  { id: 'v2', index: 2, chapter_count: 8, units: [], target_node_id: 'ascend', reaches_node: true, status: 'planned' },
  { id: 'v3', index: 3, chapter_count: 6, units: [], target_node_id: 'ending', reaches_node: true, status: 'planned' },
]
const mapChapters = (volume, count, start = 1) => Array.from({ length: count }, (_, index) => ({ id: `${volume}-${index}`, volume_id: volume, index: start + index, status: 'final' }))

test('writing position stays hidden before the first finalized chapter, including a first draft', () => {
  const actual = writingPosition(mapNodes, mapVolumes, [{ index: 1, volume_id: 'v1', status: 'drafting' }])
  assert.deepEqual(actual, { volume: null, doneInVolume: 0, volumeChapters: 0, nextNode: null, chaptersToNode: null, passed: [], ratio: 0 })
  assert.equal(writingPositionText(actual, mapVolumes, []), '')
})

test('middle of a volume uses units for planning and sums every volume leading to the next node', () => {
  const chapters = mapChapters('v1', 3)
  const before = JSON.stringify([mapNodes, mapVolumes, chapters])
  const actual = writingPosition(mapNodes, mapVolumes, chapters)
  assert.deepEqual(actual, { volume: 1, doneInVolume: 3, volumeChapters: 6, nextNode: mapNodes[1], chaptersToNode: 11, passed: ['opening'], ratio: 0.15 })
  assert.equal(plannedVolumeChapters(mapVolumes[0]), 6)
  assert.equal(writingPositionText(actual, mapVolumes, chapters), '第 1 卷 3/6 章 · 离「飞升神界」还有 11 章')
  assert.equal(JSON.stringify([mapNodes, mapVolumes, chapters]), before)
})

test('at a completed intermediate volume the cursor advances without prematurely passing its target', () => {
  const actual = writingPosition(mapNodes, mapVolumes, mapChapters('v1', 6))
  assert.equal(actual.volume, 2)
  assert.equal(actual.doneInVolume, 0)
  assert.equal(actual.nextNode.id, 'ascend')
  assert.equal(actual.chaptersToNode, 8)
  assert.deepEqual(actual.passed, ['opening'])
})

test('finishing the volume where a node happens advances to the next target and marks the node passed', () => {
  const actual = writingPosition(mapNodes, mapVolumes, [...mapChapters('v1', 6), ...mapChapters('v2', 8, 7)])
  assert.equal(actual.volume, 3)
  assert.equal(actual.nextNode.id, 'ending')
  assert.equal(actual.chaptersToNode, 6)
  assert.deepEqual(actual.passed, ['opening', 'ascend'])
})

test('active drafting takes precedence over the last finalized chapter; planned outlines do not', () => {
  const chapters = [...mapChapters('v1', 3), { index: 4, volume_id: 'v2', status: 'drafting' }, { index: 10, volume_id: 'v3', status: 'planned' }]
  const actual = writingPosition(mapNodes, mapVolumes, chapters)
  assert.equal(actual.volume, 2)
  assert.equal(actual.ratio, 3 / 20)
  assert.equal(actual.chaptersToNode, 8)
})

test('whole-book completion keeps the last volume, reaches every node and has no next target', () => {
  const chapters = [...mapChapters('v1', 6), ...mapChapters('v2', 8, 7), ...mapChapters('v3', 6, 15)]
  const actual = writingPosition(mapNodes, mapVolumes, chapters)
  assert.deepEqual(actual, { volume: 3, doneInVolume: 6, volumeChapters: 6, nextNode: null, chaptersToNode: null, passed: ['opening', 'ascend', 'ending'], ratio: 1 })
  assert.equal(writingPositionText(actual, mapVolumes, chapters), '全书完结')
})

test('legacy untargeted volumes show chapter progress without claiming a node or a final segment', () => {
  const volumes = mapVolumes.map(volume => ({ ...volume, target_node_id: null }))
  const chapters = mapChapters('v1', 3)
  const actual = writingPosition(mapNodes, volumes, chapters)
  assert.equal(actual.volume, 1)
  assert.equal(actual.nextNode, null)
  assert.equal(actual.chaptersToNode, null)
  assert.equal(actual.ratio, 0.15)
  assert.equal(writingPositionText(actual, volumes, chapters), '第 1 卷 3/6 章 · 全书已定稿 3/20 章')
  assert.equal(writingPosition([], [], chapters).volume, null)
})

test('a final untargeted stretch in an otherwise mapped book counts chapters to the ending', () => {
  const volumes = mapVolumes.map(volume => volume.index === 3 ? { ...volume, target_node_id: null } : volume)
  const chapters = [...mapChapters('v1', 6), ...mapChapters('v2', 8, 7), ...mapChapters('v3', 2, 15)]
  assert.equal(writingPositionText(writingPosition(mapNodes, volumes, chapters), volumes, chapters), '第 3 卷 2/6 章 · 正在写最后一段，离结局还有 4 章')
})

test('map cursor interpolates actual finalized chapters between chapter-positioned nodes', () => {
  const positions = storyMapNodeChapters(mapNodes, mapVolumes)
  assert.deepEqual(positions, [1, 14, 20])
  assert.equal(storyMapWritingIndex(positions, 1), 0)
  assert.equal(storyMapWritingIndex(positions, 3), 2 / 13)
  assert.equal(storyMapWritingIndex(positions, 17), 1.5)
  assert.equal(storyMapWritingIndex(positions, 20), 2)
  assert.equal(storyMapWritingIndex([1, 1, 4], 1), 1)
  assert.equal(storyMapWritingIndex([], 3), 0)
})

test('map omission keeps endpoints and two neighbors on either side, inserting one gap per skipped group', () => {
  const nodes = Array.from({ length: 12 }, (_, index) => ({ id: `n${index}`, index: index + 1 }))
  const ids = values => values.map(node => node?.id ?? '…')
  assert.deepEqual(ids(visibleStoryMapNodes(nodes, 5.5, 900)), ['n0', '…', 'n4', 'n5', 'n6', 'n7', '…', 'n11'])
  assert.deepEqual(ids(visibleStoryMapNodes(nodes, 0.5, 900)), ['n0', 'n1', 'n2', '…', 'n11'])
  assert.deepEqual(ids(visibleStoryMapNodes(nodes.slice(0, 8), 3.5, 559)), ['n0', '…', 'n2', 'n3', 'n4', 'n5', '…', 'n7'])
  assert.equal(visibleStoryMapNodes(nodes.slice(0, 8), 3.5, 560).length, 8)
  assert.deepEqual(visibleStoryMapNodes([], 0, 300), [])
})

test('segment chapter totals also use the actual planned units', () => {
  assert.equal(segments(mapNodes, mapVolumes)[0].chapters, 14)
})

test('rewriting a chapter in a done volume keeps that volume active and does not call the book complete', () => {
  const volumes = mapVolumes.map(volume => ({ ...volume, status: 'done' }))
  const chapters = [...mapChapters('v1', 6), ...mapChapters('v2', 8, 7), ...mapChapters('v3', 6, 15)]
    .map(chapter => chapter.index === 20 ? { ...chapter, status: 'drafting' } : chapter)
  const position = writingPosition(mapNodes, volumes, chapters)
  assert.equal(position.volume, 3)
  assert.equal(position.nextNode.id, 'ending')
  assert.equal(position.chaptersToNode, 1)
  assert.deepEqual(position.passed, ['opening', 'ascend'])
  assert.equal(isWritingComplete(volumes, chapters), false)
  assert.equal(writingPositionText(position, volumes, chapters), '第 3 卷 5/6 章 · 离「终局」还有 1 章')
})

test('a progress ratio of one does not mean complete when a stale plan still has an unfinished chapter', () => {
  const volumes = [{ ...mapVolumes[2], chapter_count: 2, status: 'done' }]
  for (const status of ['drafting', 'planned']) {
    const chapters = [...mapChapters('v3', 2), { volume_id: 'v3', index: 3, status }]
    const position = writingPosition(mapNodes, volumes, chapters)
    assert.equal(position.ratio, 1)
    assert.equal(position.nextNode.id, 'ending')
    assert.equal(isWritingComplete(volumes, chapters), false)
    assert.notEqual(writingPositionText(position, volumes, chapters), '全书完结')
  }
  assert.equal(isWritingComplete([], []), false)
  assert.equal(isWritingComplete(mapVolumes, []), false)
})

test('unassigned legacy volumes remain in the chapter axis between target-node boundaries', () => {
  const volumes = [
    { ...mapVolumes[0], chapter_count: 2, units: [], target_node_id: null },
    { ...mapVolumes[1], chapter_count: 4 },
    { ...mapVolumes[2], chapter_count: 3 },
  ]
  const positions = storyMapNodeChapters(mapNodes, volumes)
  assert.deepEqual(positions, [1, 6, 9])
  assert.equal(storyMapWritingIndex(positions, 2), 1 / 5)
  assert.equal(storyMapWritingIndex(positions, 6), 1)
  assert.equal(storyMapWritingIndex(positions, 7), 1 + 1 / 3)
  assert.equal(storyMapWritingIndex(positions, 100), 2)
})

test('chapter-axis interpolation stays finite at zero-length and coincident node boundaries', () => {
  assert.equal(storyMapWritingIndex([1, 5, 5, 9], 5), 2)
  assert.equal(storyMapWritingIndex([1, 5, 5, 9], 7), 2.5)
  assert.equal(storyMapWritingIndex([0, 0, 0], 0), 2)
  assert.deepEqual(storyMapNodeChapters(mapNodes, []), [0, 0, 0])
  assert.equal(storyMapWritingIndex([1, 5], -1), 0)
})

test('both adjacent node segments can span multiple volumes without re-counting earlier finalized volumes', () => {
  const volumes = [...mapVolumes.map(volume => volume.index === 3 ? { ...volume, reaches_node: false } : volume),
    { ...mapVolumes[2], id: 'v4', index: 4, chapter_count: 4, reaches_node: true }]
  const chapters = [...mapChapters('v1', 6), ...mapChapters('v2', 8, 7), ...mapChapters('v3', 2, 15)]
  const position = writingPosition(mapNodes, volumes, chapters)
  assert.equal(position.volume, 3)
  assert.equal(position.nextNode.id, 'ending')
  assert.equal(position.chaptersToNode, 8)
  assert.deepEqual(position.passed, ['opening', 'ascend'])
  assert.equal(storyMapWritingIndex(storyMapNodeChapters(mapNodes, volumes), 16), 1.2)
})
