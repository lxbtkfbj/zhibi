import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { keys } from '../api/hooks'
import { libraryKeys } from '../api/library'
import type { BookDetail, Job, LiveDraft, MeetingMessage } from '../api/types'

const SETTLED = new Set(['waiting_author', 'succeeded', 'failed', 'cancelled'])
// 写作过程中这些产出一到，就刷新大纲、目录和进度，不必等整轮写完
const REFRESH_ON = new Set(['concept', 'settings_focus', 'settings_rest', 'protagonist', 'world', 'segment', 'segment_plan', 'segment_volumes', 'lore', 'spine', 'threads', 'outline', 'volume_plan', 'chapter_plan', 'chapter_draft', 'chapter_polish', 'chapter_materials', 'chapter_final', 'unit_recap', 'volume_recap'])

/**
 * 会议室实时消息。连接时服务器先补发历史，再推送新消息；
 * 断线后浏览器会带上 Last-Event-ID 自动重连，服务器从断点补齐。
 */
export function useMeeting(bookId: string) {
  // 消息按书分开存放，切换到另一本书时不会短暂显示上一本的消息
  const [state, setState] = useState<{ bookId: string; messages: MeetingMessage[] }>({ bookId, messages: [] })
  const [connected, setConnected] = useState(false)
  // 写手正在写的正文：每条推送都带着这一章到目前为止的全文，中途打开页面也能接上
  const [draft, setDraft] = useState<{ bookId: string; draft: LiveDraft | null }>({ bookId, draft: null })
  const qc = useQueryClient()

  useEffect(() => {
    const source = new EventSource(`/api/books/${bookId}/events`)
    source.addEventListener('open', () => {
      setConnected(true)
      // 连上之前推送的任务状态收不到（例如演示模式几秒就跑完一步），连上时重新拉一次
      qc.invalidateQueries({ queryKey: keys.book(bookId) })
    })
    source.addEventListener('error', () => setConnected(false))
    source.addEventListener('book', () => {
      for (const key of [keys.book(bookId), keys.books, keys.nodes(bookId), keys.bible(bookId), keys.outline(bookId), keys.threads(bookId), keys.secrets(bookId), libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId)]) {
        void qc.invalidateQueries({ queryKey: key })
      }
    })
    source.addEventListener('library', () => {
      for (const key of [libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId), keys.bible(bookId)]) void qc.invalidateQueries({ queryKey: key })
    })
    source.addEventListener('message', (event) => {
      const message = JSON.parse((event as MessageEvent).data) as MeetingMessage
      setState((prev) => {
        const base = prev.bookId === bookId ? prev.messages : []
        if (base.length && base[base.length - 1].id >= message.id) return prev
        return { bookId, messages: [...base, message] }
      })
      if (message.kind === 'artifact' && REFRESH_ON.has(message.payload?.type ?? '')) {
        for (const key of [libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId)]) void qc.invalidateQueries({ queryKey: key })
        for (const key of [keys.chapters(bookId), keys.outline(bookId), keys.book(bookId)]) qc.invalidateQueries({ queryKey: key })
        if (['spine', 'segment', 'segment_volumes'].includes(message.payload?.type ?? '')) qc.invalidateQueries({ queryKey: keys.nodes(bookId) })
        if (message.payload?.type === 'chapter_final' || ['lore', 'world', 'segment', 'segment_volumes'].includes(message.payload?.type ?? '')) {
          for (const key of [keys.bible(bookId), keys.secrets(bookId), keys.nodes(bookId)]) qc.invalidateQueries({ queryKey: key })
        }
        if (['threads', 'segment_volumes'].includes(message.payload?.type ?? '')) qc.invalidateQueries({ queryKey: keys.threads(bookId) })
      }
    })
    source.addEventListener('draft', (event) => {
      setDraft({ bookId, draft: JSON.parse((event as MessageEvent).data) as LiveDraft })
    })
    source.addEventListener('job', (event) => {
      const job = JSON.parse((event as MessageEvent).data) as Job
      qc.setQueryData<BookDetail>(keys.book(bookId), (old) => (old ? { ...old, active_job: job } : old))
      if (SETTLED.has(job.status)) {
        setDraft({ bookId, draft: null })
        const all = [keys.book(bookId), keys.outline(bookId), keys.bible(bookId), keys.threads(bookId), keys.nodes(bookId), keys.secrets(bookId), keys.chapters(bookId), keys.usage(bookId), keys.books, libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId)]
        for (const key of all) {
          qc.invalidateQueries({ queryKey: key })
        }
      }
    })
    return () => source.close()
  }, [bookId, qc])

  return {
    messages: state.bookId === bookId ? state.messages : [],
    connected,
    draft: draft.bookId === bookId ? draft.draft : null,
  }
}
