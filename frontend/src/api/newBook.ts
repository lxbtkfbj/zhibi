import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { get, post } from './client'
import { keys } from './hooks'
import type { BookDetail } from './types'

export type Channel = '男频' | '女频'

export interface BookMeta {
  channels: { key: Channel; categories: string[]; tag_groups: { name: string; tags: string[] }[] }[]
  /** 篇幅换算章数用的每章字数 */
  chapter_words: number
  max_tags: number
}

/** 新建页上的几项，全部选填。 */
export interface NewBookFields {
  title: string
  blurb: string
  channel: Channel | ''
  genre: string
  tags: string[]
  /** 单位万字 */
  target_length: number | null
}

export interface BookDraft extends NewBookFields {
  /** 编辑部的一句话：这版的思路，或这次改了哪里 */
  reply: string
}

export const useBookMeta = () => useQuery({ queryKey: ['book-meta'], queryFn: () => get<BookMeta>('/book-meta'), staleTime: 60_000 })

/** 作者叫了编辑部才调用：按点子起草，或带着页面现状按意见改。不建书。 */
export const useDraftBook = () =>
  useMutation({ mutationFn: (body: { idea: string; current?: NewBookFields; feedback?: string }) => post<BookDraft>('/book-drafts', body) })

/** 只建书、存作者填的几项，编辑部不开工。 */
export function useCreateBlankBook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: NewBookFields) => post<{ book: BookDetail; job: null }>('/books', { ...body, start_setup: false }),
    onSuccess: (data) => {
      qc.setQueryData(keys.book(data.book.id), data.book)
      void qc.invalidateQueries({ queryKey: keys.books })
    },
  })
}
