/** 群聊分成一段段对话：读对话列表、认消息属于哪一段、正在看哪一段、这一段还有几句没落实。 */

import { useQuery } from '@tanstack/react-query'
import { get } from '../../api/client'
import type { ChatConv, MeetingMessage } from '../../api/types'
import { useBookContext } from '../book/context'

export const convsKey = (bookId: string) => ['chat-convs', bookId]

export function useChatConvs(bookId: string) {
  return useQuery({ queryKey: convsKey(bookId), queryFn: () => get<ChatConv[]>(`/books/${bookId}/chat/conversations`) })
}

/** 群聊里的消息（私聊不算）属于哪一段：早先没记的算最近聊的那一段 */
export function convOf(m: MeetingMessage, latest: string | undefined): string | undefined {
  return m.payload?.conv ?? latest
}

/** 正在看的那一段：点过哪段就是哪段，没点过就是最近聊的那一段 */
export function useCurrentConv(): { conv: string | undefined; latest: string | undefined; convs: ChatConv[] | undefined } {
  const { bookId, chatConv, messages } = useBookContext()
  const { data: convs } = useChatConvs(bookId)
  const latest = convs?.[0]?.id ?? messages.findLast((m) => !m.payload?.thread && m.payload?.conv)?.payload?.conv
  return { conv: chatConv ?? latest, latest, convs }
}

/** 这一段里只是商量、没改书的话（问句不算）：上一张方案卡以后的 */
export function unsettled(messages: MeetingMessage[], conv: string | undefined, latest: string | undefined): number {
  const mine = messages.filter((m) => !m.payload?.thread && !m.payload?.dropped && convOf(m, latest) === conv)
  const since = mine.findLastIndex((m) => m.kind === 'plan')
  return mine.slice(since + 1).filter((m) => m.speaker === 'author' && m.kind === 'note'
    && m.payload?.outcome?.kind === 'chat' && !m.payload.ask_only && !m.payload.outcome.shortcut && !m.payload.steps?.length).length
}

/** 「今天 21:03」「昨天」「10-17」 */
export function dayLabel(iso: string): string {
  const at = new Date(iso)
  const today = new Date()
  const days = Math.round((new Date(today.toDateString()).getTime() - new Date(at.toDateString()).getTime()) / 86_400_000)
  if (days === 0) return `今天 ${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
  if (days === 1) return '昨天'
  return `${at.getFullYear() === today.getFullYear() ? '' : `${at.getFullYear()}-`}${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`
}
