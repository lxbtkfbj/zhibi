/** 聊天的浏览器能力：存储不可用时仍能聊天，剪贴板失败时退回传统复制。 */
import type { ChatRole } from './chatModel'

export interface ChatDraft { text: string; to?: ChatRole }

const DRAFT_EVENT = 'zhibi:chat-draft'

function notifyDraft(bookId: string, draft: ChatDraft): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(DRAFT_EVENT, { detail: { bookId, draft } }))
}

/** 同一页换过聊天实例、或另一标签页改过草稿时，保持当前框与存储一致。 */
export function subscribeChatDraft(bookId: string | undefined, onChange: (draft: ChatDraft) => void): () => void {
  if (!bookId || typeof window === 'undefined') return () => {}
  const changed = (event: Event) => {
    const detail = (event as CustomEvent<{ bookId: string; draft: ChatDraft }>).detail
    if (detail.bookId === bookId) onChange(detail.draft)
  }
  const stored = (event: StorageEvent) => {
    if (event.key === `zhibi.chat-draft.${bookId}` || event.key === null) onChange(loadChatDraft(bookId))
  }
  window.addEventListener(DRAFT_EVENT, changed)
  window.addEventListener('storage', stored)
  return () => {
    window.removeEventListener(DRAFT_EVENT, changed)
    window.removeEventListener('storage', stored)
  }
}

export function loadChatDraft(bookId?: string): ChatDraft {
  if (!bookId) return { text: '' }
  try {
    const value = JSON.parse(localStorage.getItem(`zhibi.chat-draft.${bookId}`) ?? 'null')
    if (!value || typeof value.text !== 'string' || !value.text) return { text: '' }
    const to = ['主编', '设定师', '写手', '审稿'].includes(value.to) ? value.to as ChatRole : undefined
    return { text: value.text, ...(to ? { to } : {}) }
  } catch {
    return { text: '' }
  }
}

export function saveChatDraft(bookId: string | undefined, draft: ChatDraft): void {
  if (!bookId) return
  try {
    const key = `zhibi.chat-draft.${bookId}`
    if (!draft.text) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify({ text: draft.text, ...(draft.to ? { to: draft.to } : {}) }))
    notifyDraft(bookId, draft)
  } catch {
    // 隐私模式、配额或安全策略不应打断输入。
  }
}

/** 请求在途时可能换过浮窗实例；只清仍然是当次发送内容的草稿。 */
export function clearSentChatDraft(bookId: string | undefined, sent: ChatDraft): boolean {
  if (!bookId) return true
  try {
    const key = `zhibi.chat-draft.${bookId}`
    const raw = localStorage.getItem(key)
    if (raw) {
      const current = JSON.parse(raw)
      if (current.text !== sent.text || current.to !== sent.to) return false
    }
    localStorage.removeItem(key)
    notifyDraft(bookId, { text: '' })
  } catch {
    // 存储不可用也要清掉当前实例成功发出的字。
  }
  return true
}

export async function copyChatText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 不支持 Clipboard API 或未获授权时，仍在点击的上下文里尝试传统复制。
  }
  let field: HTMLTextAreaElement | undefined
  const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const selected = focused instanceof HTMLTextAreaElement || focused instanceof HTMLInputElement
    ? { start: focused.selectionStart, end: focused.selectionEnd, direction: focused.selectionDirection }
    : null
  try {
    field = document.createElement('textarea')
    field.value = text
    field.readOnly = true
    field.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;pointer-events:none'
    document.body.appendChild(field)
    field.select()
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    field?.remove()
    try {
      focused?.focus({ preventScroll: true })
      if (selected && (focused instanceof HTMLTextAreaElement || focused instanceof HTMLInputElement)) {
        focused.setSelectionRange(selected.start, selected.end, selected.direction ?? undefined)
      }
    } catch { /* 原输入框可能已经卸载，不影响复制结果。 */ }
  }
}
