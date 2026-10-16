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
