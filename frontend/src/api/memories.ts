import { useQuery } from '@tanstack/react-query'
import { get } from './client'

export interface Memory {
  id: number
  book_id: string | null
  kind: 'writing' | 'chat'
  summary: string
  detail: string
  source: string
  scope: 'always' | 'chapter' | 'volume'
  chapter_index: number | null
  volume_index: number | null
  active: boolean
  label: string
  version: number
  deleted_at: string | null
  created_at: string
  updated_at: string
}
export type MemoryReceipt = Pick<Memory, 'id' | 'book_id' | 'kind' | 'summary' | 'label' | 'version'> & { working?: boolean; action?: 'create' | 'update' | 'forget'; before?: Pick<Memory, 'summary'> & Partial<Pick<Memory, 'kind' | 'book_id' | 'label'>> }
export const memoryKeys = { all: ['memories'], book: (id: string) => ['memories', id] }
export const useMemories = (bookId: string, enabled = true) => useQuery({ queryKey: memoryKeys.book(bookId), queryFn: () => get<Memory[]>(`/books/${bookId}/memories`), enabled, refetchInterval: 5000 })
