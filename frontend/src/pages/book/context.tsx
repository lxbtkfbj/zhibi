import { createContext, useContext } from 'react'
import type { BookDetail, Conversation, Job, LiveDraft, MeetingMessage, Outline } from '../../api/types'
import type { WorkspaceTarget } from '../../lib/workspace'

export interface BookContextValue {
  bookId: string
  book: BookDetail
  job: Job | null
  messages: MeetingMessage[]
  connected: boolean
  /** 写手正在写的正文（实时）；写完一段后 done 为 true */
  draft: LiveDraft | null
  working: boolean
  /** 等作者拍板：开书方案、卷纲、试读或卡住的章节 */
  waiting: boolean
  /** 主编动笔前的提问，等作者回答 */
  asking: boolean
  outline: Outline | undefined
  conversation: Conversation
  setConversation: (conversation: Conversation) => void
  unread: Record<Conversation, number>
  following: boolean
  followTarget: WorkspaceTarget | null
  manualNavigate: (path: string) => void
  focusComposer: number
  requestFeedback: () => void
  celebrate: () => void
}

export const BookContext = createContext<BookContextValue | null>(null)

export function useBookContext() {
  const value = useContext(BookContext)
  if (!value) throw new Error('useBookContext 必须在 BookLayout 内使用')
  return value
}
