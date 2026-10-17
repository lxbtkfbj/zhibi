import assert from 'node:assert/strict'
import test from 'node:test'
import { arcStarted, arcText, buildOutlineTree, defaultOutlineExpanded, flattenOutline, outlineAncestors, outlineRange, outlineStatusText, unitStarted, unitStatus, volumeStarted } from '../src/lib/outlineTree.ts'

const chapter = (index, status = 'planned') => ({ index, title: `章节${index}`, status })
const unit = (id, chapters = []) => ({ id, index: 1, title: '入门', summary: '先救人。再查案。', chapter_count: 3, status: 'outlined', locked: false, chapters })
const volume = (index, status = 'planned', units = [unit(`u${index}`)]) => ({ id: `v${index}`, index, title: '青阳城', summary: '离开小镇。', chapter_count: 12, status, locked: false, units })
const arc = (id, status = 'planned', volumes = [volume(1)]) => ({ node_id: id, title: '走出山门', text: '为母亲寻药。', status, locked: false, planned: true, end: { title: '终点', event: '破局离城。', kind: 'milestone' }, volumes })
const fixture = () => ({ segmented: true, arcs: [arc('a1'), { ...arc('end', 'later', []), planned: false, text: '结局不能出现在这里。', end: { title: '终局', event: '所有人重获自由。', kind: 'ending' } }], ending: { node_id: 'end', title: '归家', event: '所有人重获自由。' } })

test('开书默认只展开全书、第一篇与第 1 卷，不预先展开单元和未来篇', () => {
  const data = fixture()
  data.arcs[0].volumes.push(volume(2))
  const before = JSON.stringify(data)
  const root = buildOutlineTree(data, '长夜灯')
  assert.deepEqual(defaultOutlineExpanded(root), ['book', 'segment-a1', 'volume-1'])
  assert.equal(root.name, '长夜灯')
  assert.equal(root.children[0].name, '第 1 篇 · 走出山门')
  assert.equal(JSON.stringify(data), before)
})

test('默认展开正在写的篇和卷，已完成篇不会抢占当前位置', () => {
  const data = fixture()
  data.arcs.unshift(arc('before', 'done', [volume(1, 'done')]))
  data.arcs[1] = arc('current', 'writing', [volume(2, 'done'), volume(3, 'writing'), volume(4)])
  assert.deepEqual(defaultOutlineExpanded(buildOutlineTree(data)), ['book', 'segment-current', 'volume-3'])
})

test('后面的篇不编号、不重复结局；其余未来篇连续编号，结局独占最后一行', () => {
  const data = fixture()
  data.arcs.splice(1, 0, { ...arc('future', 'later', []), planned: false })
  const root = buildOutlineTree(data)
  assert.deepEqual(root.children.map(item => item.name), ['第 1 篇 · 走出山门', '第 2 篇 · 走出山门', '后面的篇', '结局 · 归家'])
  assert.equal(arcText(data.arcs[2]), '')
  assert.equal(root.children.at(-1).ending.event, '所有人重获自由。')
  assert.equal(outlineStatusText(root.children[2].status), '写到再定')
})

test('第二包已规划篇没有一段话时读终点发生什么；未规划节点不编造内容', () => {
  const old = { ...arc('old'), text: '' }
  assert.equal(arcText(old), '破局离城。')
  assert.equal(arcText({ ...old, text: ' \n ' }), '破局离城。')
  assert.equal(arcText({ ...old, end: null }), '')
  assert.equal(arcText({ ...old, planned: false }), '')
  assert.equal(arcText({ ...old, text: '作者的新稿' }), '作者的新稿')
  assert.equal(arcText({ ...old, text: '  作者的新稿。\n' }), '  作者的新稿。\n')
})

test('没分篇的历史书仍保留全书卷树；空树也有稳定默认展开', () => {
  const root = buildOutlineTree({ segmented: false, arcs: [{ ...arc(null), end: null }], ending: null })
  assert.equal(root.children[0].name, '全书')
  assert.deepEqual(defaultOutlineExpanded(root), ['book', 'segment-1', 'volume-1'])
  assert.deepEqual(defaultOutlineExpanded(buildOutlineTree({ segmented: false, arcs: [], ending: null })), ['book'])
})

test('状态以真实章节为准：章纲不算开写，重写中的单元不会假报写完', () => {
  assert.deepEqual(['done', 'writing', 'planned', 'later', 'final', 'drafting', 'outlined'].map(outlineStatusText), ['已写完', '正在写', '已规划', '写到再定', '已写完', '正在写', '已规划'])
  assert.equal(unitStarted(unit('u', [chapter(1)])), false)
  assert.equal(unitStarted(unit('u', [chapter(1, 'drafting')])), true)
  assert.equal(unitStatus(unit('u', [chapter(1, 'final')])), 'writing')
  assert.equal(unitStatus({ ...unit('u', [chapter(1, 'final'), chapter(2, 'final'), chapter(3, 'drafting')]), status: 'done' }), 'writing')
  assert.equal(unitStatus(unit('u', [chapter(1, 'final'), chapter(2, 'final'), chapter(3, 'final')])), 'done')
  assert.equal(unitStatus(unit('u', [chapter(1), chapter(2), chapter(3)])), 'planned')
  assert.equal(volumeStarted(volume(1, 'writing', [])), true)
  assert.equal(volumeStarted(volume(1, 'planned', [unit('u', [chapter(1, 'final')])])), true)
  assert.equal(arcStarted(arc('a', 'planned', [volume(1, 'planned', [unit('u', [chapter(1)])])])), false)
})

test('章数范围保留尚未生成的计划，URL 深链接可展开正确祖先', () => {
  const data = fixture()
  data.arcs[0].volumes[0].units = [unit('u1', [chapter(1), chapter(2)]), { ...unit('u2', []), index: 2, chapter_count: 4 }]
  const root = buildOutlineTree(data)
  const all = flattenOutline(root)
  assert.equal(outlineRange(all.find(item => item.key === 'volume-1')), '第 1–2 章 · 共 7 章')
  assert.equal(outlineRange(all.find(item => item.key === 'unit-u1')), '第 1–2 章 · 共 3 章')
  assert.equal(outlineRange(all.find(item => item.key === 'unit-u2')), '4 章')
  assert.equal(outlineRange(all.find(item => item.key === 'chapter-2')), '第 2 章')
  assert.deepEqual(outlineAncestors(root, 'chapter-2'), ['book', 'segment-a1', 'volume-1', 'unit-u1'])
  assert.deepEqual(outlineAncestors(root, 'missing'), [])
})
