import { createContext, useContext } from 'react'
import type { BookDetail, Job, MeetingMessage } from '../../api/types'

export interface BookContextValue {
  bookId: string
  book: BookDetail
  job: Job | null
  messages: MeetingMessage[]
  connected: boolean
  working: boolean
  waiting: boolean
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
