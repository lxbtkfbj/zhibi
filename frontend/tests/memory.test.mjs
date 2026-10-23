import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { receiptCopy, memoryDate, isMemoryNote } from '../src/lib/memory.ts'

const receipt = { id: 12, version: 3, book_id: 'book', kind: 'writing', summary: '少用套话', label: '只管第 2 卷' }
test('记住行的种类、库、期限和正在写逐字一致', () => {
  assert.deepEqual(receiptCopy(receipt, receipt, false), { text: '记住了：少用套话', meta: '写书时照做 · 这本书 · 只管第 2 卷', disabled: false, title: '' })
  assert.equal(receiptCopy({ ...receipt, working: true }, receipt, false).meta, '写书时照做 · 这本书 · 只管第 2 卷 · 正在写的从下一步起照办')
  assert.equal(receiptCopy({ ...receipt, book_id: null, label: '一直有效' }, receipt, false).meta, '写书时照做 · 全局 · 一直有效')
  assert.equal(receiptCopy({ ...receipt, kind: 'chat', book_id: null, working: true }, receipt, false).meta, '聊天时记得 · 全局')
  assert.equal(receiptCopy({ ...receipt, kind: 'chat' }, receipt, false).meta, '聊天时记得 · 这本书')
})
test('撤销、后来又改过、后来删掉三种状态', () => {
  assert.equal(receiptCopy(receipt, undefined, true).text, '没记：少用套话')
  assert.equal(receiptCopy(receipt, { ...receipt, version: 4 }, false).title, '这条后来又改过，去「记忆」里改')
  assert.equal(receiptCopy(receipt, { ...receipt, version: 4 }, false).disabled, true)
  assert.equal(receiptCopy(receipt, undefined, false).title, '这条后来删掉了')
  assert.equal(receiptCopy(receipt, { ...receipt, deleted_at: '2026-10-22' }, false).title, '这条后来删掉了')
})
test('日期只在不是今年时带年份', () => {
  const now = new Date('2026-10-23T12:00:00+08:00')
  assert.equal(memoryDate('2026-10-22T12:00:00+08:00', now), '10月22日')
  assert.equal(memoryDate('2025-10-22T12:00:00+08:00', now), '2025年10月22日')
})
test('方案卡、修改数、互斥与跟着刷新接到记忆，不保留写作要求编辑入口', () => {
  const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
  assert.match(read('../src/pages/book/PlanCard.tsx'), /记忆 · 写书时照做 · \$\{item.scope\}/u)
  assert.match(read('../src/pages/book/ChatActions.tsx'), /<MemoryNotice receipt=\{outcome.memory\}/u)
  assert.doesNotMatch(read('../src/pages/book/ChatActions.tsx'), /RequirementDialog/u)
  const changed = read('../src/pages/workspace/LiveChat.tsx').match(/const CHANGED = new Set\(([^\n]+)/u)[1]
  assert.doesNotMatch(changed, /requirement|memory/u)
  assert.match(read('../src/pages/workspace/BookDesk.tsx'), /inbox.open \|\| memory.open/u)
  assert.match(read('../src/lib/useMeeting.ts'), /addEventListener\('memories'/u)
})

test('关联写作任务的聊天记忆仍是作者气泡，不被当成干活记录吞掉结果行', () => {
  assert.equal(isMemoryNote({ speaker: 'author', payload: { outcome: { kind: 'to_job', memory: receipt } } }), true)
  assert.equal(isMemoryNote({ speaker: 'author', payload: { outcome: { kind: 'agent' }, steps: [{ kind: 'to_job', memory: receipt }] } }), true)
  assert.equal(isMemoryNote({ speaker: 'author', payload: { outcome: { kind: 'chat' } } }), false)
  assert.equal(isMemoryNote({ speaker: 'chief', payload: { outcome: { memory: receipt } } }), false)
  assert.match(readFileSync(new URL('../src/pages/workspace/LiveChat.tsx', import.meta.url), 'utf8'), /m.job_id[^\n]+!isMemoryNote\(m\)/u)
})
