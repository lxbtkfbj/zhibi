import assert from 'node:assert/strict'
import test from 'node:test'
import { latestReply, mentionAt, takeMention } from '../src/pages/workspace/chatModel.ts'

test('话里直接写了 @谁：认出来、从话里拿掉，只认第一个', () => {
  assert.deepEqual(takeMention('@设定师 主角现在什么境界？'), { text: '主角现在什么境界？', to: '设定师' })
  assert.deepEqual(takeMention('这段节奏 @审稿 看看'), { text: '这段节奏 看看', to: '审稿' })
  assert.deepEqual(takeMention('@写手 @审稿 都来'), { text: '@审稿 都来', to: '写手' })
  assert.deepEqual(takeMention('邮箱 a@b.com 不算点名'), { text: '邮箱 a@b.com 不算点名' })
})

test('光标前在打「@设…」才弹出名单，对不上的人不列', () => {
  assert.deepEqual(mentionAt('@', 1), { start: 0, query: '', roles: ['主编', '设定师', '写手', '审稿'] })
  assert.deepEqual(mentionAt('帮我看看 @设', 7), { start: 5, query: '设', roles: ['设定师'] })
  assert.equal(mentionAt('帮我看看 @设 定', 9), null)
  assert.equal(mentionAt('@张三', 3), null)
  assert.equal(mentionAt('没有艾特', 4), null)
})

test('只有最后一条是回答时，它下面才有「重新回答」', () => {
  const q = { id: 'q', who: '作者', text: '问' }
  const a = { id: 'a', who: '主编', text: '答', state: 'done', replyTo: 'q' }
  assert.equal(latestReply([q, a]), a)
  assert.equal(latestReply([a, q]), undefined)
  assert.equal(latestReply([]), undefined)
})
