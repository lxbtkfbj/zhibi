import type { Memory, MemoryReceipt } from '../api/memories'
import type { MeetingMessage } from '../api/types'

/** A chat note stays a chat bubble even when the writing worker is linked to it. */
export function isMemoryNote(message: Pick<MeetingMessage, 'speaker' | 'payload'>) {
  return message.speaker === 'author' && (!!message.payload?.outcome?.memory || !!message.payload?.steps?.some(step => step.memory))
}

export const kindLabel = (kind: Memory['kind']) => kind === 'writing' ? '写书时照做' : '聊天时记得'

export function receiptCopy(receipt: MemoryReceipt, row: Memory | undefined, undone: boolean) {
  const action = receipt.action ?? 'create'
  const prior = undone && action === 'update' ? receipt.before : undefined
  const kind = prior?.kind ?? receipt.kind
  const library = prior && 'book_id' in prior ? prior.book_id : receipt.book_id
  const label = prior?.label ?? receipt.label
  const ownForget = action === 'forget' && row?.version === receipt.version && !!row.deleted_at
  const deleted = !row || (!!row.deleted_at && !ownForget)
  const changed = !!row && row.version !== receipt.version
  const title = { create: '记住了', update: '改了一条记忆', forget: '忘掉了' }[action]
  const cancelled = { create: '没记', update: '换回了原来的', forget: '找回来了' }[action]
  return {
    text: `${undone ? cancelled : title}：${undone && action === 'update' ? receipt.before?.summary ?? receipt.summary : receipt.summary}`,
    meta: `${kindLabel(kind)} · ${library ? '这本书' : '全局'}${kind === 'writing' ? ` · ${label}${receipt.working ? ' · 正在写的从下一步起照办' : ''}` : ''}`,
    disabled: deleted || changed,
    title: deleted ? '这条后来删掉了' : changed ? '这条后来又改过，去「记忆」里改' : '',
  }
}

export function memoryDate(value: string, now = new Date()) {
  const date = new Date(value)
  return `${date.getFullYear() !== now.getFullYear() ? `${date.getFullYear()}年` : ''}${date.getMonth() + 1}月${date.getDate()}日`
}
