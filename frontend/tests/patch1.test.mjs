import test from 'node:test'
import assert from 'node:assert/strict'
import { outcomeCopy, pendingOutcome } from '../src/lib/chat.ts'
import { ROLE_KEYS, ROLE_KEY_LABEL } from '../src/lib/roles.ts'

test('分流角色在最后，独立于主编', () => {
  assert.equal(ROLE_KEYS.at(-1), 'router')
  assert.equal(ROLE_KEY_LABEL.router, '群聊分流')
})

test('异步判断两分钟后显示超时，不覆盖已完成结果', () => {
  const start = '2026-10-17T00:00:00Z'
  const at = Date.parse(start)
  assert.equal(pendingOutcome({ kind: 'pending' }, start, at + 119999).kind, 'pending')
  assert.deepEqual(pendingOutcome({ kind: 'pending' }, start, at + 120001), { kind: 'failed', reason: '判断超时' })
  assert.equal(pendingOutcome({ kind: 'chat' }, start, at + 500000).kind, 'chat')
})

test('分流失败、过时与方案结果说清是否生效', () => {
  assert.deepEqual(outcomeCopy({ kind: 'failed', reason: '判断超时' }), { text: '没判断出这句话要做什么（判断超时），书没改。换个说法再说一次试试。', actions: [] })
  assert.deepEqual(outcomeCopy({ kind: 'too_late' }), { text: '编辑部在等你拍板，这句话没改书。要改，就在拍板的地方提意见，或者说「总结一下」整理成方案。', actions: [] })
  assert.equal(outcomeCopy({ kind: 'plan_apply', label: '开篇和老怪' }).text, '照方案办：开篇和老怪')
  assert.equal(outcomeCopy({ kind: 'plan_made' }).text, '刚才聊了不少，我先整理成方案，你看看再照办')
  assert.deepEqual(outcomeCopy({ kind: 'suggestion' }).actions, ['去看看'])
})
