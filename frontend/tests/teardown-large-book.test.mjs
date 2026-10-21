import assert from 'node:assert/strict'
import test from 'node:test'
import { essenceNumber, introVolumes } from '../src/pages/workspace/desk-v2/essenceData.ts'

const volume = (n, first, last, extra = {}) => ({
  id: `v:${n}`, ref: { id: String(n) }, kind: '卷', title: `第${essenceNumber(n)}卷　剧情${n}`, range: [first, last],
  children: [{ kind: '单元' }, { kind: '单元' }, { kind: '单元', virtual: true }], ...extra,
})
const book = (children, teardown = {}) => ({ outline: { kind: '全书', children }, teardown: { last_read: 60, ...teardown } })

test('简介与精髓印章复用大纲中文编号，二十至九十九不回退阿拉伯数字', () => {
  for (const [n, text] of [[1, '一'], [10, '十'], [19, '十九'], [20, '二十'], [21, '二十一'], [28, '二十八'], [30, '三十'], [99, '九十九'], [100, '100']]) assert.equal(essenceNumber(n), text)
})

test('卷格按大纲顺序全书编号，篇名沿用目录，范围和单元数不包含虚拟单元', () => {
  const result = introVolumes(book([
    { kind: '篇', title: '第一篇　起点', children: [volume(1, 1, 20), volume(2, 21, 40)] },
    { kind: '篇', title: '第二篇　转折', children: [volume(3, 41, 60)] },
  ]))
  assert.equal(result.groups.length, 2)
  assert.deepEqual(result.groups.map(group => group.arc), [{ title: '第一篇 起点', first: 1, last: 40 }, { title: '第二篇 转折', first: 41, last: 60 }])
  assert.deepEqual(result.groups.flatMap(group => group.volumes).map(({ id, n, title, first, last, units }) => [id, n, title, first, last, units]), [
    ['v:1', 1, '剧情1', 1, 20, 2], ['v:2', 2, '剧情2', 21, 40, 2], ['v:3', 3, '剧情3', 41, 60, 2],
  ])
  assert.equal(result.tail, null)
})

test('无篇不造篇头；open_volume_id、open、还没分卷与尚未读完的卷不出格，尾卡到last_read', () => {
  for (const extra of [{}, { open: true }, { title: '第八卷　还没分卷' }]) {
    const data = book([volume(7, 1, 20), volume(8, 21, 60, extra)], { open_volume_id: Object.keys(extra).length ? null : '8', last_read: 47 })
    const result = introVolumes(data)
    assert.equal(result.groups.length, 1)
    assert.equal(result.groups[0].arc, undefined)
    assert.equal(result.groups[0].volumes[0].n, 1)
    assert.deepEqual(result.tail, [21, 47])
  }
  // 已读到卷末但主编仍在归，也不能提前把它当成已收尾。
  for (const extra of [{ open: true }, { title: '第一卷　还没分卷' }]) assert.deepEqual(introVolumes(book([volume(1, 1, 60, extra)])).tail, [1, 60])
  assert.deepEqual(introVolumes(book([volume(1, 1, 60)], { open_volume_id: '1' })).tail, [1, 60])
  assert.deepEqual(introVolumes(book([], { last_read: 0 })), { groups: [], tail: null })
})
