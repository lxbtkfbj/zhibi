import { useMutation, useQueryClient } from '@tanstack/react-query'
import { post } from './client'
import { keys } from './hooks'
import type { BookDetail, Job } from './types'

/** 手动规划只生成下一段，不偷偷把它变成写章请求。 */
export function usePlanSegment(bookId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => post<Job>(`/books/${bookId}/plan-segment`),
    onSuccess: job => {
      client.setQueryData<BookDetail>(keys.book(bookId), book => book ? { ...book, active_job: job } : book)
      void client.invalidateQueries({ queryKey: keys.books })
    },
  })
}
