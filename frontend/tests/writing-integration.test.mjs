import assert from 'node:assert/strict'
import test from 'node:test'
import { decisionCopy } from '../src/lib/decision.ts'

const pending = { kind: 'volume_review', volume: 2, title: '第二卷 寒原' }
const proposal = { node_id: 'node', index: 3, current: { title: '旧目标' }, proposed: { title: '新目标' }, reason: '沿用已经写出的证据' }

test('卷纲拍板同时保留节点冲突与调整提醒，不重复后端已给出的提议', () => {
  const copy = decisionCopy({ ...pending, issues: ['节点冲突：前提尚未成立'], node_update: proposal }, 'book')
  assert.equal(copy.issues.length, 2)
  assert.match(copy.issues[0], /节点冲突/)
  assert.match(copy.issues[1], /节点调整：.*旧目标.*新目标.*批准卷纲后应用/)
  assert.match(copy.hint, /没锁的节点提议会随批准应用/)
  assert.equal(decisionCopy({ ...pending, issues: ['节点调整：已经列出'], node_update: proposal }, 'book').issues.length, 1)
})

test('旧卷纲没有节点提议仍可拍板，五项审稿使用中文', () => {
  const copy = decisionCopy(pending, 'book')
  assert.deepEqual(copy.issues, [])
  assert.match(copy.hint, /期待感/)
  assert.equal(copy.approve, '批准开写')
})
