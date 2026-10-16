import assert from 'node:assert/strict'
import test from 'node:test'
import { firstSegment, isUnplannedSegment, OPENING_FIELDS, showFirstSegment } from '../src/lib/setupSegment.ts'

const opening = Object.freeze({ id: 'opening', index: 1, kind: 'opening', segment: null, anchors: [] })
const endpoint = Object.freeze({ id: 'end', index: 2, kind: 'milestone', segment: { number: 1 }, anchors: [{ id: 'anchor' }] })
const distant = Object.freeze({ id: 'distant', index: 3, kind: 'milestone', segment: null, status: 'pinned' })
const ending = Object.freeze({ id: 'ending', index: 4, kind: 'ending', segment: null })
const nodes = Object.freeze([opening, endpoint, distant, ending])

test('第一段取真实段终点，远景只取终点之后、结局之前；不改输入顺序', () => {
  const input = Object.freeze([ending, endpoint, distant, opening])
  const volumes = Object.freeze([{ id: 'later-volume', index: 3, target_node_id: 'distant' }, { id: 'second', index: 2, target_node_id: 'end' }, { id: 'first', index: 1, target_node_id: 'end' }])
  const result = firstSegment(input, volumes)
  assert.equal(result.opening, opening)
  assert.equal(result.endpoint, endpoint)
  assert.equal(result.ending, ending)
  assert.deepEqual(result.castNodes, [opening, endpoint])
  assert.deepEqual(result.distant, [distant])
  assert.deepEqual(result.volumes.map(volume => volume.id), ['first', 'second'])
  assert.equal(input[0], ending)
  assert.equal(volumes[0].id, 'later-volume')
})

test('旧书不把第二节点当第一段，只有正在做或等待第一段时显示预备面板', () => {
  const oldNodes = [opening, { ...endpoint, segment: null }, ending]
  assert.equal(firstSegment(oldNodes).endpoint, null)
  assert.deepEqual(firstSegment(oldNodes).distant, [])
  assert.equal(showFirstSegment(oldNodes, null, null), false)
  assert.equal(showFirstSegment(oldNodes, 'segment', { kind: 'book_setup', status: 'running' }), true)
  assert.equal(showFirstSegment(oldNodes, null, { kind: 'book_setup', status: 'waiting_author', pending: { kind: 'setup_piece', piece: 'segment' } }), true)
  assert.equal(showFirstSegment(oldNodes, 'segment', { kind: 'book_setup', status: 'succeeded' }), false)
  assert.equal(showFirstSegment(oldNodes, 'segment', { kind: 'write_book', status: 'running' }), false)
  assert.equal(showFirstSegment(nodes, null, null), true)
})

test('终点后未规划区间只显示写到再定，旧书和已规划段不改', () => {
  assert.equal(isUnplannedSegment(opening, endpoint, nodes), false)
  assert.equal(isUnplannedSegment(endpoint, distant, nodes), true)
  assert.equal(isUnplannedSegment(distant, ending, nodes), true)
  assert.equal(isUnplannedSegment(ending, null, nodes), false)
  assert.equal(isUnplannedSegment(endpoint, { ...distant, segment: { number: 2 } }, nodes), false)
  assert.equal(isUnplannedSegment(opening, ending, [opening, ending]), false)
})

test('第一段和第一卷共用同一份开篇字段，不丢第 3 章钩子', () => {
  assert.deepEqual(OPENING_FIELDS, [
    ['scene', '第 1 章的切入场面'], ['pressure', '前 3 章被什么压着'], ['first_win', '第一个小爽点'],
    ['finger', '金手指露头'], ['hook', '第 3 章的钩子'],
  ])
})

test('开写后作者在终点前插节点，第一段仍以segment关联而非固定数组下标识别', () => {
  const nodes = [{ id: 'start', index: 1, kind: 'opening' }, { id: 'author', index: 2, kind: 'milestone' }, { id: 'endpoint', index: 3, kind: 'milestone', event: '真正的第一段终点', segment: { number: 1 } }, { id: 'ending', index: 4, kind: 'ending' }]
  assert.equal(firstSegment(nodes).endpoint.event, '真正的第一段终点')
})
