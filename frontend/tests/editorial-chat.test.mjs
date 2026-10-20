import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { chatRecipient, clearSentQuote, latestReply, mentionAt, takeMention } from '../src/pages/workspace/chatModel.ts'

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

test('拆书引用默认问主编，显式点名优先；无引用的普通书行为不变', () => {
  const quote = { text: '原文一句', where: '第 12 章' }
  assert.equal(chatRecipient(undefined, undefined, quote), '主编')
  assert.equal(chatRecipient('设定师', undefined, quote), '设定师')
  assert.equal(chatRecipient(undefined, '审稿', quote), '审稿')
  assert.equal(chatRecipient('写手', '审稿', quote), '写手')
  assert.equal(chatRecipient(), undefined)
  assert.equal(chatRecipient(undefined, '设定师'), '设定师')
})

test('成功发送只清当次引用，不清掉新选的一句或其他对话的引用', () => {
  const sent = { text: '第一次选择', where: '第 12 章' }
  const next = { text: '第二次选择', where: '第 13 章' }
  const other = { text: '其他对话', where: '设定' }
  const quotes = { chief: sent, writer: other }
  assert.deepEqual(clearSentQuote(quotes, sent), { chief: null, writer: other })
  assert.equal(quotes.chief, sent)
  const replaced = { chief: next, writer: other }
  assert.equal(clearSentQuote(replaced, sent), replaced)
  assert.equal(clearSentQuote(quotes, undefined), quotes)
})

test('引用桥仅接拆书，发送原文和问主编字段，失败不清引用且不触发额外effect', () => {
  const live = readFileSync(new URL('../src/pages/workspace/LiveChat.tsx', import.meta.url), 'utf8')
  const chat = readFileSync(new URL('../src/pages/workspace/Chat.tsx', import.meta.url), 'utf8')
  assert.match(live, /const quote = book\.source === 'teardown' \? chatQuotes\.chief \?\? undefined : undefined/)
  assert.match(live, /ask: CODE\[recipient\]/)
  assert.match(live, /\.\.\.\(quote \? \{ quote \} : \{\}\)/)
  assert.match(live, /if \(sent && quote\) clearQuote\(\)/)
  assert.match(live, /clearSentQuote\(current, quote\)/)
  assert.match(chat, /aria-label="引用原文"/)
  assert.match(chat, /onClick=\{chat\.clearQuote\} aria-label="取消引用"/)
  assert.match(chat, /chatRecipient\(to, undefined, chat\.quote\)/)
  assert.match(chat, /chatRecipient\(to, taken\.to, chat\.quote\)/)
  assert.doesNotMatch(chat, /useEffect/)
})
