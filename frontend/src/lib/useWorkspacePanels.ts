import { useCallback, useEffect, useRef, useState, type PointerEvent } from 'react'
import type { Conversation, MeetingMessage } from '../api/types'
import { conversationContains, unreadCount } from './workspace'

const CONVERSATIONS: Conversation[] = ['group', 'chief', 'lorekeeper', 'writer', 'reviewer']
const WIDTH_KEY = 'zhibi:conversation-ratio'
const DEFAULT_RATIO = 0.34
/** 聊天栏最窄、最宽（含左边的头像栏）：再宽一行字太长不好读，多出来的地方留给书稿。 */
export const MIN_CHAT = 380
export const MAX_CHAT = 760
function savedRatio() {
  try {
    const value = Number(localStorage.getItem(WIDTH_KEY))
    return value >= 0.1 && value <= 0.9 ? value : DEFAULT_RATIO
  } catch { return DEFAULT_RATIO }
}

/** Save a ratio, not a viewport-specific pixel width; preserve space for the manuscript. */
export function useWorkspaceResize() {
  const container = useRef<HTMLDivElement>(null)
  const [ratio, setRatio] = useState(savedRatio)
  const [available, setAvailable] = useState(1000)
  const [dragging, setDragging] = useState(false)
  const max = Math.max(MIN_CHAT, Math.min(MAX_CHAT, available - 321))
  const width = Math.round(Math.max(MIN_CHAT, Math.min(available * ratio, max)))
  useEffect(() => {
    const el = container.current
    if (!el) return
    const observer = new ResizeObserver(() => setAvailable(el.clientWidth))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  const save = (next: number) => {
    setRatio(next)
    try { localStorage.setItem(WIDTH_KEY, String(next)) } catch { /* Optional preference. */ }
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId) || !container.current) return
    const next = Math.max(MIN_CHAT, Math.min(event.clientX - container.current.getBoundingClientRect().left, max))
    save(next / available)
  }
  return {
    container, width, dragging, max,
    separatorProps: {
      onPointerDown: (event: PointerEvent<HTMLDivElement>) => {
        event.preventDefault()
        event.currentTarget.setPointerCapture(event.pointerId)
        setDragging(true)
      },
      onPointerMove,
      onPointerUp: (event: PointerEvent<HTMLDivElement>) => {
        event.currentTarget.releasePointerCapture(event.pointerId)
        setDragging(false)
      },
      onLostPointerCapture: () => setDragging(false),
      onDoubleClick: () => save(DEFAULT_RATIO),
    },
    step: (delta: number) => save(Math.max(MIN_CHAT, Math.min(width + delta, max)) / available),
    reset: () => save(DEFAULT_RATIO),
  }
}

export function useConversationReads(bookId: string, messages: MeetingMessage[], conversation: Conversation, visible: boolean) {
  const key = useCallback((name: Conversation) => `zhibi:read:${bookId}:${name}`, [bookId])
  const [markers, setMarkers] = useState<Record<Conversation, number>>(() => Object.fromEntries(CONVERSATIONS.map(name => {
    try { return [name, Number(localStorage.getItem(key(name))) || 0] } catch { return [name, 0] }
  })) as Record<Conversation, number>)
  const [foreground, setForeground] = useState(document.visibilityState === 'visible')
  useEffect(() => {
    const change = () => setForeground(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', change)
    const storage = (event: StorageEvent) => {
      const name = CONVERSATIONS.find(name => key(name) === event.key)
      if (name) setMarkers(old => ({ ...old, [name]: Math.max(old[name], Number(event.newValue) || 0) }))
    }
    window.addEventListener('storage', storage)
    return () => { document.removeEventListener('visibilitychange', change); window.removeEventListener('storage', storage) }
  }, [key])
  const latest = [...messages].reverse().find(m => conversationContains(m, conversation))?.id ?? 0
  useEffect(() => {
    if (!visible || !foreground || latest <= markers[conversation]) return
    // Synchronize the current SSE read position with the browser's persisted markers.
    // oxlint-disable-next-line react/set-state-in-effect
    setMarkers(old => ({ ...old, [conversation]: latest }))
    try { localStorage.setItem(key(conversation), String(latest)) } catch { /* Reading still works without storage. */ }
  }, [conversation, latest, visible, foreground, markers, key])
  return Object.fromEntries(CONVERSATIONS.map(name => [name,
    name === conversation && visible && foreground ? 0 : unreadCount(messages, name, markers[name]),
  ])) as Record<Conversation, number>
}
