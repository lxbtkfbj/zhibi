import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { keys } from '../api/hooks'
import { settingsKeys } from '../api/settings'
import type { ChatTyping } from './chat'
import { libraryKeys } from '../api/library'
import type { BookDetail, Job, LiveDraft, MeetingMessage } from '../api/types'
import { get } from '../api/client'
import type { ApiParts } from '../pages/workspace/fromApi'
import { teardownRefreshGate } from './teardownRefresh'

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
  const [typing, setTyping] = useState<Record<string, ChatTyping>>({})
  const qc = useQueryClient()

  useEffect(() => {
    const source = new EventSource(`/api/books/${bookId}/events`)
    const isTeardown = () => qc.getQueryData<BookDetail>(keys.book(bookId))?.source === 'teardown'
    const teardownGate = teardownRefreshGate()
    let disposed = false
    let partsTimer: ReturnType<typeof setTimeout> | undefined
    let partsRunning = false
    let partsAgain = false
    let partsGeneration = 0
    const readTeardownParts = async () => {
      partsTimer = undefined
      if (disposed) return
      if (partsRunning) { partsAgain = true; return }
      partsRunning = true
      const generation = partsGeneration
      try {
        const [outline, chapters] = await Promise.all([
          get<ApiParts['outline']>(`/books/${bookId}/outline-tree`),
          get<ApiParts['chapters']>(`/books/${bookId}/chapters?with_outline=true`),
        ])
        if (!disposed && generation === partsGeneration) {
          qc.setQueryData<ApiParts>(['workspace', bookId], old => old ? { ...old, outline, chapters } : old)
          qc.setQueryData(['outline-tree', bookId], outline)
          // 正文详情惰性读取；下次点开时重新取，不拉全书正文。
          void qc.invalidateQueries({ queryKey: keys.chapters(bookId), refetchType: 'none' })
          void qc.invalidateQueries({ queryKey: ['desk-v2-chapter', bookId], refetchType: 'none' })
        }
      } catch {
        // 暂时断网保留已有大纲；重连或下一次保存事件会再拉，不清空作者正在看的内容。
      } finally {
        partsRunning = false
        if (partsAgain && !disposed) { partsAgain = false; partsTimer = setTimeout(() => { void readTeardownParts() }, 150) }
      }
    }
    const refreshTeardownParts = () => { partsTimer ??= setTimeout(() => { void readTeardownParts() }, 150) }
    // 连上时服务器一口气补发全部历史消息：一阵子里要刷新的攒在一起，只刷新一次，不然几百条消息就是几千次请求
    const pending = new Map<string, readonly unknown[]>()
    let timer: ReturnType<typeof setTimeout> | undefined
    const refresh = (queryKeys: readonly (readonly unknown[])[]) => {
      for (const key of queryKeys) {
        pending.set(JSON.stringify(key), key)
        if (key[0] === 'workspace') {
          const chapterKey = ['desk-v2-chapter', bookId]
          pending.set(JSON.stringify(chapterKey), chapterKey)
        }
      }
      timer ??= setTimeout(() => {
        timer = undefined
        const all = [...pending.values()]
        pending.clear()
        for (const queryKey of all) void qc.invalidateQueries({ queryKey })
      }, 150)
    }
    source.addEventListener('open', () => {
      setConnected(true)
      // 连上之前推送的任务状态收不到（例如演示模式几秒就跑完一步），连上时重新拉一次
      qc.invalidateQueries({ queryKey: keys.book(bookId) })
      if (isTeardown()) refreshTeardownParts()
    })
    source.addEventListener('error', () => setConnected(false))
    source.addEventListener('book', () => {
      for (const key of [keys.book(bookId), keys.books, keys.nodes(bookId), keys.bible(bookId), keys.outline(bookId), keys.threads(bookId), keys.secrets(bookId), keys.chapters(bookId), libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId), libraryKeys.versions(bookId), ['outline-tree', bookId], ['workspace', bookId], ['desk-v2-chapter', bookId], ['saves', bookId], settingsKeys.book(bookId), settingsKeys.requirements(bookId)]) {
        void qc.invalidateQueries({ queryKey: key })
      }
    })
    // 存了一档、回到了某一档：存档那一栏重新读
    source.addEventListener('saves', () => { void qc.invalidateQueries({ queryKey: ['saves', bookId] }) })
    source.addEventListener('teardown_saved', () => {
      if (isTeardown() && teardownGate('saved') === 'parts') refreshTeardownParts()
    })
    source.addEventListener('library', () => {
      for (const key of [libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId), libraryKeys.versions(bookId), ['outline-tree', bookId], ['workspace', bookId], ['desk-v2-chapter', bookId], keys.bible(bookId)]) void qc.invalidateQueries({ queryKey: key })
    })
    source.addEventListener('message', (event) => {
      const message = JSON.parse((event as MessageEvent).data) as MeetingMessage
      setState((prev) => {
        const base = prev.bookId === bookId ? prev.messages : []
        if (base.length && base[base.length - 1].id >= message.id) return prev
        return { bookId, messages: [...base, message] }
      })
      if (isTeardown()) { refresh([['chat-convs', bookId]]); return }
      refresh([settingsKeys.requirements(bookId), keys.book(bookId), keys.outline(bookId), libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), ['outline-tree', bookId], ['workspace', bookId], ['saves', bookId], ['chat-convs', bookId]])
      if (message.kind === 'artifact' && REFRESH_ON.has(message.payload?.type ?? '')) {
        refresh([libraryKeys.candidates(bookId), libraryKeys.versions(bookId), keys.chapters(bookId)])
        if (['spine', 'segment', 'segment_volumes'].includes(message.payload?.type ?? '')) refresh([keys.nodes(bookId)])
        if (message.payload?.type === 'chapter_final' || ['lore', 'world', 'segment', 'segment_volumes'].includes(message.payload?.type ?? '')) {
          refresh([keys.bible(bookId), keys.secrets(bookId), keys.nodes(bookId)])
        }
        if (['threads', 'segment_volumes'].includes(message.payload?.type ?? '')) refresh([keys.threads(bookId)])
      }
    })
    source.addEventListener('message_update', event => {
      const message = JSON.parse((event as MessageEvent).data) as MeetingMessage
      setState(prev => prev.bookId === bookId ? { bookId, messages: prev.messages.map(m => m.id === message.id ? message : m) } : prev)
      if (isTeardown()) { refresh([['chat-convs', bookId]]); return }
      // 聊天里改完、换回、再改一版：整本书和存档跟着刷新
      refresh([settingsKeys.requirements(bookId), ['workspace', bookId], ['saves', bookId], ['chat-convs', bookId]])
    })
    // 群聊的一段对话归档、删除了：删掉的那一段，聊天记录从列表里去掉
    source.addEventListener('conversations', event => {
      const { conv, action } = JSON.parse((event as MessageEvent).data) as { conv: string; action: string }
      if (action === 'delete') setState(prev => prev.bookId === bookId ? { bookId, messages: prev.messages.filter(m => m.payload?.conv !== conv) } : prev)
      refresh([['chat-convs', bookId]])
    })
    // 聊天回答边写边推：每次带着到目前为止的全文
    source.addEventListener('chat_delta', event => {
      const { id, text } = JSON.parse((event as MessageEvent).data) as { id: number; text: string }
      setState(prev => prev.bookId === bookId ? {
        bookId,
        messages: prev.messages.map(m => m.id === id && (m.payload?.state === 'thinking' || m.payload?.state === 'streaming')
          ? { ...m, content: text, payload: { ...m.payload, state: 'streaming' } } : m),
      } : prev)
    })
    source.addEventListener('chat_typing', event => {
      const value = JSON.parse((event as MessageEvent).data) as ChatTyping
      setTyping(prev => ({ ...prev, [value.thread]: { ...value, at: Date.now() } }))
    })
    source.addEventListener('draft', (event) => {
      setDraft({ bookId, draft: JSON.parse((event as MessageEvent).data) as LiveDraft })
    })
    source.addEventListener('job', (event) => {
      const job = JSON.parse((event as MessageEvent).data) as Job
      // 留下最新事件，即便终态刷新把 active_job 清掉，也不能让晚到的开始回包倒退到排队。
      if (job.kind === 'teardown') qc.setQueryData(['teardown-job-event', bookId], job)
      qc.setQueryData<BookDetail>(keys.book(bookId), (old) => (old ? { ...old, active_job: job } : old))
      if (isTeardown()) {
        if (job.kind === 'teardown' && teardownGate('job', job) === 'book') {
          partsGeneration += 1
          clearTimeout(partsTimer)
          partsTimer = undefined
          partsAgain = false
          for (const queryKey of [keys.book(bookId), ['workspace', bookId], ['desk-v2-chapter', bookId], keys.books, keys.usage(bookId)]) void qc.invalidateQueries({ queryKey })
        }
        return
      }
      if (SETTLED.has(job.status)) {
        setDraft({ bookId, draft: null })
        const all = [keys.book(bookId), keys.outline(bookId), keys.bible(bookId), keys.threads(bookId), keys.nodes(bookId), keys.secrets(bookId), keys.chapters(bookId), keys.usage(bookId), keys.books, libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId), libraryKeys.versions(bookId), ['outline-tree', bookId], ['workspace', bookId], ['desk-v2-chapter', bookId]]
        for (const key of all) {
          qc.invalidateQueries({ queryKey: key })
        }
      }
    })
    return () => {
      source.close()
      disposed = true
      clearTimeout(partsTimer)
      clearTimeout(timer)
    }
  }, [bookId, qc])

  return {
    messages: state.bookId === bookId ? state.messages : [],
    connected,
    typing,
    draft: draft.bookId === bookId ? draft.draft : null,
  }
}
