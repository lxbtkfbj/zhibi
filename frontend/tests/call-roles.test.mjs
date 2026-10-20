import assert from 'node:assert/strict'
import test from 'node:test'
import { CALL_ROLE_KEYS, normalizeCallRole, roleName } from '../src/lib/callRoles.ts'
import { ROLE_KEYS } from '../src/lib/roles.ts'

test('调用角色筛选包含全部实际调用角色，不把默认模型配置当作角色', () => {
  assert.deepEqual(CALL_ROLE_KEYS, ROLE_KEYS.filter(role => role !== 'default'))
  assert.deepEqual(CALL_ROLE_KEYS, ['chief', 'lorekeeper', 'writer', 'reviewer', 'teardown', 'router'])
  for (const role of CALL_ROLE_KEYS) assert.equal(normalizeCallRole(role), role, `${role} must survive URL validation`)
})

test('旧书与拆书、群聊分流调用在列表、详情与筛选中使用一致的中文名称', () => {
  assert.deepEqual(CALL_ROLE_KEYS.map(roleName), ['主编', '设定师', '写手', '审稿', '拆书', '群聊分流'])
  assert.equal(roleName('all'), '全体成员')
  assert.equal(roleName('chief,lorekeeper'), '主编、设定师')
  assert.equal(roleName('teardown, router'), '拆书、群聊分流')
  assert.equal(roleName('author'), '作者')
  assert.equal(roleName('system'), '系统')
  for (const role of ['future_role', 'constructor', '__proto__']) assert.equal(roleName(role), role, '未知历史角色仍保留原始标识')
})

test('无效角色 URL 筛选安全回退到全部角色，不发出无法命中的条件', () => {
  for (const role of [undefined, null, '', 'default', 'author', 'system', 'chief,writer', 'TEARDOWN', '拆书', 'unknown', {}, 1]) {
    assert.equal(normalizeCallRole(role), '', String(role))
  }
})
