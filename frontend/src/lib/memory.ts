import type { Memory, MemoryReceipt } from '../api/memories'
import type { MeetingMessage } from '../api/types'

/** A chat note stays a chat bubble even when the writing worker is linked to it. */
export function isMemoryNote(message: Pick<MeetingMessage, 'speaker' | 'payload'>) {
  return message.speaker === 'author' && (!!message.payload?.outcome?.memory || !!message.payload?.steps?.some(step => step.memory))
}

export const kindLabel = (kind: Memory['kind']) => kind === 'writing' ? '写书时照做' : '聊天时记得'

export function receiptCopy(receipt: MemoryReceipt, row: Memory | undefined, undone: boolean) {
  const deleted = !row || !!row.deleted_at
  const changed = !!row && row.version !== receipt.version
  return {
    text: `${undone ? '没记' : '记住了'}：${receipt.summary}`,
    meta: `${kindLabel(receipt.kind)} · ${receipt.book_id ? '这本书' : '全局'}${receipt.kind === 'writing' ? ` · ${receipt.label}${receipt.working ? ' · 正在写的从下一步起照办' : ''}` : ''}`,
    disabled: deleted || changed,
    title: deleted ? '这条后来删掉了' : changed ? '这条后来又改过，去「记忆」里改' : '',
  }
}

export function memoryDate(value: string, now = new Date()) {
  const date = new Date(value)
  return `${date.getFullYear() !== now.getFullYear() ? `${date.getFullYear()}年` : ''}${date.getMonth() + 1}月${date.getDate()}日`
}
