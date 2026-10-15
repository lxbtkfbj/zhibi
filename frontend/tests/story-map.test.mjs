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
