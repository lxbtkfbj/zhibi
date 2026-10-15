import { createContext, useContext } from 'react'
import type { BookDetail, Job, LiveDraft, MeetingMessage } from '../../api/types'

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
  teamOpen: boolean
  setTeamOpen: (open: boolean) => void
  celebrate: () => void
}

export const BookContext = createContext<BookContextValue | null>(null)

export function useBookContext() {
  const value = useContext(BookContext)
  if (!value) throw new Error('useBookContext 必须在 BookLayout 内使用')
  return value
}
