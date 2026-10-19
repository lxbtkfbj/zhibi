/** 群聊分成一段段对话：浮窗顶上「新对话」，旁边展开以前的对话（按第一句话起名、带日期）。
 *  每段只带自己的记录和摘要；书本身（设定、大纲、要求）就是长期记忆。开新对话前，这一段聊出的想法还没落实，先提醒「总结一下」。 */

import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { History, MessageSquarePlus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { post } from '../../api/client'
import { useBookContext } from '../book/context'
import { convsKey, dayLabel, unsettled, useCurrentConv } from './convs'

const headerButton = 'flex h-8 items-center gap-1 rounded-md px-1.5 text-[13px] text-ink-3 transition-colors hover:bg-line/60 hover:text-ink'

/** 浮窗顶上：新对话、以前的对话 */
export function ChatConvs() {
  const { bookId, messages, setChatConv } = useBookContext()
  const { conv, latest, convs } = useCurrentConv()
  const qc = useQueryClient()
  const [open, setOpen] = useState<'list' | 'remind' | null>(null)
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(null) }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [open])
  const pending = unsettled(messages, conv, latest)
  const start = async () => {
    setBusy(true)
    try {
      const row = await post<{ id: string }>(`/books/${bookId}/chat/conversations`)
      setChatConv?.(row.id)
      await qc.invalidateQueries({ queryKey: convsKey(bookId) })
      setOpen(null)
    } finally {
      setBusy(false)
    }
  }
  const summarize = async () => {
    setOpen(null)
    await post(`/books/${bookId}/notes`, { content: '总结一下前面聊的', ...(conv ? { conv } : {}) })
  }
  const shown = (convs ?? []).filter((c) => c.notes > 0 || c.id === conv)
  return (
    <div ref={box} className="relative flex items-center gap-0.5">
      <button type="button" disabled={busy} onClick={() => (pending ? setOpen(open === 'remind' ? null : 'remind') : void start())}
        title="开一段新对话：前面的对话不再带给编辑部，书里的设定、大纲、要求照样都在" className={headerButton}>
        <MessageSquarePlus className="size-4" />新对话
      </button>
      <button type="button" onClick={() => setOpen(open === 'list' ? null : 'list')} aria-expanded={open === 'list'}
        title="以前的对话：点一段接着聊" aria-label="以前的对话" className={clsx(headerButton, open === 'list' && 'bg-line/60 text-ink')}>
        <History className="size-4" />
      </button>
      {open === 'remind' && (
        <div role="dialog" aria-label="开新对话前" className="absolute top-[calc(100%+6px)] right-0 z-20 w-72 rounded-xl border border-line bg-card p-3.5 text-[13px] leading-relaxed text-ink shadow-[var(--shadow-lift)]">
          <p>这一段还有 {pending} 句只是商量、还没改进书里。开新对话以后，编辑部就看不到这些话了。</p>
          <p className="mt-1 text-ink-3">要不要先「总结一下」，出一张方案卡看看要不要照办？</p>
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" disabled={busy} onClick={() => void start()} className="h-8 rounded-lg px-3 text-ink-2 hover:bg-line/50">直接开新的</button>
            <button type="button" onClick={() => void summarize()} className="h-8 rounded-lg bg-ink px-3 text-paper-2 hover:bg-ink-2">先总结一下</button>
          </div>
        </div>
      )}
      {open === 'list' && (
        <div role="listbox" aria-label="以前的对话" className="absolute top-[calc(100%+6px)] right-0 z-20 w-72 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]">
          <p className="px-2.5 pt-1 pb-1.5 text-xs text-ink-3">以前的对话 · 点一段接着聊</p>
          <div className="scroll-thin max-h-72 overflow-y-auto">
            {shown.map((c) => (
              <button key={c.id} type="button" role="option" aria-selected={c.id === conv}
                onClick={() => { setChatConv?.(c.id === latest ? null : c.id); setOpen(null) }}
                className={clsx('flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-subtle', c.id === conv && 'bg-subtle')}>
                <span className={clsx('min-w-0 flex-1 truncate text-[14px]', c.title ? 'text-ink' : 'text-ink-3')}>{c.title || '新对话（还没说话）'}</span>
                <span className="shrink-0 text-xs text-ink-3 tabular-nums">{c.id === conv ? '正在看' : dayLabel(c.last_at)}</span>
              </button>
            ))}
            {!shown.length && <p className="px-2.5 py-2 text-[13px] text-ink-3">还没有对话</p>}
          </div>
        </div>
      )}
    </div>
  )
}
