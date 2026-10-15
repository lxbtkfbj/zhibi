import assert from 'node:assert/strict'
import test from 'node:test'
import { NODE_STATUS, spineArtifactNodes } from '../src/lib/storyMap.ts'

test('historical spine cards preserve opening, sorted milestones, and ending without mutation', () => {
  const milestones = Object.freeze([
    Object.freeze({ index: 2, title: '第二转折', event: '发现真相', volume: 3, change: '旧结果' }),
    Object.freeze({ index: 1, title: '第一转折', event: '离开家乡', volume: 1 }),
  ])
  const old = Object.freeze({ opening: '旧开篇', milestones, ending: '旧结局' })
  assert.deepEqual(spineArtifactNodes(old), [
    { kind: 'opening', title: '开篇', event: '旧开篇', volume: null },
    { kind: 'milestone', title: '第一转折', event: '离开家乡', volume: 1 },
    { kind: 'milestone', title: '第二转折', event: '发现真相', volume: 3 },
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
