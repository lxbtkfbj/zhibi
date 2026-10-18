import test from 'node:test'
import assert from 'node:assert/strict'
import { isFeedbackConflict, libraryQuoteWhere, outcomeCopy, sendChatFirst, typingVisible } from '../src/lib/chat.ts'

test('群聊一律先 notes，仅 409 use_feedback 再给修改意见；502 和私聊绝不转写', async () => {
  const events = []
  const feedback = async () => { events.push('feedback') }
  const send = async error => { events.push('notes'); if (error) throw error; return 'ok' }
  assert.equal(await sendChatFirst(() => send(), feedback, false), 'ok')
  await sendChatFirst(() => send({ status: 409, code: 'use_feedback' }), feedback, false)
  assert.deepEqual(events, ['notes', 'notes', 'feedback'])
  for (const [error, direct] of [[{ status: 502 }, false], [{ status: 409 }, false], [{ status: 409, code: 'use_feedback' }, true]]) await assert.rejects(sendChatFirst(() => send(error), feedback, direct))
  assert.equal(isFeedbackConflict(null, false), false)
  assert.equal(events.filter(x => x === 'feedback').length, 1)
})
test('处理结果采用当前要求文字和范围，删除后不会显示旧文字', () => {
  const row = { text: '快一点', label: '只管第 3 章' }
  assert.deepEqual(outcomeCopy({ kind: 'requirement' }, row), { text: '已记成要求：「快一点」（只管第 3 章）', actions: ['撤销', '改一下'] })
  assert.deepEqual(outcomeCopy({ kind: 'requirement' }), { text: '已撤销', actions: [] })
  assert.equal(outcomeCopy({ kind: 'chat' }).text, '只是聊天，没有记')
  assert.deepEqual(outcomeCopy({ kind: 'chat' }).actions, ['其实要记下'])
  assert.deepEqual(outcomeCopy({ kind: 'created', target_label: '角色列表 · 封不觉' }), { text: '写好了，放进了角色列表 · 封不觉', actions: ['去看看', '撤销'] })
  assert.equal(outcomeCopy({ kind: 'to_job' }, row).text, '已交给编辑部：做完手头这一步就照办')
  // 2026-10-18：三种写法就在消息下面挑，不再跳去设定库
  assert.deepEqual(outcomeCopy({ kind: 'edit', mode: 'options', target_label: '境界' }).actions, [])
  assert.deepEqual(outcomeCopy({ kind: 'fill', target_label: '封不觉', filled: ['外貌', '身世'] }), { text: '补好了「封不觉」空着的 2 栏：外貌、身世', actions: ['去看看', '撤销'] })
  assert.equal(outcomeCopy({ kind: 'working', text: '设定师在补「封不觉」空着的栏目' }).text, '设定师在补「封不觉」空着的栏目…')
  assert.deepEqual(outcomeCopy({ kind: 'edit', mode: 'instruction', target_label: '境界' }).actions, ['去看看', '撤销'])
  assert.equal(outcomeCopy({ kind: 'later' }).text, '编辑部写完再改：在待处理的建议里')
  assert.deepEqual(outcomeCopy({ kind: 'not_found' }).actions, [])
})
test('正在想按会话显示，关闭或两分钟后消失', () => {
  const typing = { thread: 'chief', speaker: 'chief', on: true, at: 100 }
  assert.equal(typingVisible(typing, 'chief', 119999), true)
  assert.equal(typingVisible(typing, 'group', 119999), false)
  assert.equal(typingVisible(typing, 'chief', 120100), false)
  assert.equal(typingVisible({ ...typing, on: false }, 'chief', 100), false)
})

test('引用位置不用内部字段路径，角色字段用服务端中文名', () => {
  const config = { character_category: { fields: [{ column: 'abilities', name: '能力' }] } }
  const item = { name: '楚风', style: 'ladder', levels: [{ name: '凝气' }] }
  assert.equal(libraryQuoteWhere(item, 'levels.0.text', config), '设定库 · 楚风 · 第 1 级「凝气」的介绍')
  assert.equal(libraryQuoteWhere(item, 'abilities', config), '设定库 · 楚风 · 能力')
  assert.equal(libraryQuoteWhere(item, 'fields.代价', config), '设定库 · 楚风 · 代价')
  assert.equal(libraryQuoteWhere(item, 'one_line', config), '设定库 · 楚风 · 一句话')
  assert.equal(libraryQuoteWhere(item, 'fields.代价@2:5', config), '设定库 · 楚风 · 代价里选中的一句')
})
