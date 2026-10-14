import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { keys } from '../api/hooks'
import type { BookDetail, Job, MeetingMessage } from '../api/types'

const SETTLED = new Set(['waiting_author', 'succeeded', 'failed', 'cancelled'])

/**
 * 会议室实时消息。连接时服务器先补发历史，再推送新消息；
 * 断线后浏览器会带上 Last-Event-ID 自动重连，服务器从断点补齐。
 */
export function useMeeting(bookId: string) {
  // 消息按书分开存放，切换到另一本书时不会短暂显示上一本的消息
  const [state, setState] = useState<{ bookId: string; messages: MeetingMessage[] }>({ bookId, messages: [] })
  const [connected, setConnected] = useState(false)
  const qc = useQueryClient()

  useEffect(() => {
    const source = new EventSource(`/api/books/${bookId}/events`)
    source.addEventListener('open', () => setConnected(true))
    source.addEventListener('error', () => setConnected(false))
    source.addEventListener('message', (event) => {
      const message = JSON.parse((event as MessageEvent).data) as MeetingMessage
      setState((prev) => {
        const base = prev.bookId === bookId ? prev.messages : []
        if (base.length && base[base.length - 1].id >= message.id) return prev
        return { bookId, messages: [...base, message] }
      })
    })
    source.addEventListener('job', (event) => {
      const job = JSON.parse((event as MessageEvent).data) as Job
      qc.setQueryData<BookDetail>(keys.book(bookId), (old) => (old ? { ...old, active_job: job } : old))
      if (SETTLED.has(job.status)) {
        for (const key of [keys.book(bookId), keys.outline(bookId), keys.bible(bookId), keys.usage(bookId), keys.books]) {
          qc.invalidateQueries({ queryKey: key })
        }
      }
    })
    return () => source.close()
  }, [bookId, qc])

  return { messages: state.bookId === bookId ? state.messages : [], connected }
}
