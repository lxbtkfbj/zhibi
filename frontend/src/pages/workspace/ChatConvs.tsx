/** 群聊分成一段段对话：浮窗顶上「新对话」，旁边展开以前的对话（按第一句话起名、带日期）。
 *  每段只带自己的记录和摘要；书本身（设定、大纲、要求）就是长期记忆。
 *  每段后面「⋯」能归档（收到最下面「已归档」里，能找回）、删除（连聊天记录一起删，书不动）。 */

import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, History, MessageSquarePlus, MoreHorizontal } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { del, post } from '../../api/client'
import type { ChatConv } from '../../api/types'
import { ErrorText } from '../../components/ui'
import { useBookContext } from '../book/context'
import { convsKey, dayLabel, useCurrentConv } from './convs'

const headerButton = 'flex h-8 shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-1.5 text-[13px] text-ink-3 transition-colors hover:bg-line/60 hover:text-ink'

/** 一段对话后面的「⋯」：点了这一行右边换成「归档」「删除」（删除点两次）；列表会滚动，不另弹小菜单免得被切掉 */
function ConvActions({ c, onArchive, onDelete, busy, open, setOpen }: {
  c: ChatConv; onArchive: () => void; onDelete: () => void; busy: boolean; open: boolean; setOpen: (open: boolean) => void
}) {
  const [sure, setSure] = useState(false)
  const small = 'h-6 shrink-0 rounded-md px-1.5 text-xs transition-colors disabled:opacity-40'
  if (!open) {
    return (
      <button type="button" onClick={(e) => { e.stopPropagation(); setOpen(true); setSure(false) }} aria-label="这段对话的更多操作"
        className="shrink-0 rounded-md p-1 text-ink-3 opacity-0 transition-opacity group-hover/conv:opacity-100 hover:bg-line/60 hover:text-ink focus-visible:opacity-100">
        <MoreHorizontal className="size-4" />
      </button>
    )
  }
  return (
    <span className="flex shrink-0 items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
      <button type="button" disabled={busy} onClick={onArchive} className={clsx(small, 'text-ink-2 hover:bg-line/60 hover:text-ink')}>{c.archived ? '取消归档' : '归档'}</button>
      <button type="button" disabled={busy} onClick={() => (sure ? onDelete() : setSure(true))}
        title="连这一段的聊天记录一起删；书里的设定、大纲、正文不动。存档里不存聊天，删了找不回"
        className={clsx(small, sure ? 'bg-seal-soft text-seal-dark' : 'text-ink-2 hover:bg-line/60 hover:text-seal')}>{sure ? '再点一次，真删了' : '删除'}</button>
      <button type="button" onClick={() => setOpen(false)} className={clsx(small, 'text-ink-3 hover:text-ink')}>算了</button>
    </span>
  )
}

/** 浮窗顶上：新对话、以前的对话 */
export function ChatConvs() {
  const { bookId, setChatConv } = useBookContext()
  const { conv, latest, convs } = useCurrentConv()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  // 哪一段的「⋯」点开了
  const [acting, setActing] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) { setOpen(false); setActing(null) } }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [open])
  const run = async (request: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await qc.invalidateQueries({ queryKey: convsKey(bookId) })
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }
  const start = () => run(async () => {
    const row = await post<{ id: string }>(`/books/${bookId}/chat/conversations`)
    setChatConv?.(row.id)
    setOpen(false)
  })
  // 归档、删除正在看的那一段：回到最近聊的那一段
  const archive = (c: ChatConv) => run(async () => {
    await post(`/books/${bookId}/chat/conversations/${c.id}/${c.archived ? 'unarchive' : 'archive'}`)
    if (!c.archived && c.id === conv) setChatConv?.(null)
  })
  const remove = (c: ChatConv) => run(async () => {
    await del(`/books/${bookId}/chat/conversations/${c.id}`)
    if (c.id === conv) setChatConv?.(null)
  })
  const shown = (convs ?? []).filter((c) => c.notes > 0 || c.id === conv || c.current)
  const active = shown.filter((c) => !c.archived)
  const archived = shown.filter((c) => c.archived)
  const row = (c: ChatConv) => (
    <div key={c.id} role="option" aria-selected={c.id === conv} tabIndex={0}
      onClick={() => { setChatConv?.(c.id === latest ? null : c.id); setOpen(false) }}
      onKeyDown={(e) => { if (e.key === 'Enter') { setChatConv?.(c.id === latest ? null : c.id); setOpen(false) } }}
      className={clsx('group/conv flex min-h-9 w-full cursor-pointer items-center gap-2 rounded-lg py-1 pr-1 pl-2.5 text-left transition-colors hover:bg-subtle', c.id === conv && 'bg-subtle')}>
      <span className={clsx('min-w-0 flex-1 truncate text-[14px]', c.title ? (c.archived ? 'text-ink-2' : 'text-ink') : 'text-ink-3')}>{c.title || '新对话（还没说话）'}</span>
      {acting !== c.id && <span className="shrink-0 text-xs text-ink-3 tabular-nums">{c.id === conv ? '正在看' : dayLabel(c.last_at)}</span>}
      {c.notes > 0 && (
        <ConvActions c={c} busy={busy} open={acting === c.id} setOpen={(on) => setActing(on ? c.id : null)}
          onArchive={() => void archive(c).then(() => setActing(null))} onDelete={() => void remove(c).then(() => setActing(null))} />
      )}
    </div>
  )
  return (
    <div ref={box} className="flex shrink-0 items-center gap-0.5">
      <button type="button" disabled={busy} onClick={() => void start()}
        aria-label="新对话" title="新对话：前面的对话不再带给编辑部，书里的设定、大纲、要求照样都在" className={headerButton}>
        <MessageSquarePlus className="size-4 shrink-0" /><span className="hidden @min-[500px]/editorial-header:inline">新对话</span>
      </button>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        title="以前的对话：点一段接着聊" aria-label="以前的对话" className={clsx(headerButton, open && 'bg-line/60 text-ink')}>
        <History className="size-4" />
      </button>
      {open && (
        <div role="listbox" aria-label="以前的对话" className="absolute top-[calc(100%+6px)] right-3 z-20 w-[calc(100%-1.5rem)] max-w-80 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]">
          <p className="px-2.5 pt-1 pb-1.5 text-xs text-ink-3">以前的对话 · 点一段接着聊</p>
          <div className="scroll-thin max-h-80 overflow-y-auto">
            {active.map(row)}
            {!shown.length && <p className="px-2.5 py-2 text-[13px] text-ink-3">还没有对话</p>}
            {archived.length > 0 && (
              <div className="mt-1 border-t border-line pt-1">
                <button type="button" onClick={() => setShowArchived(!showArchived)} aria-expanded={showArchived}
                  className="flex w-full items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-ink-3 hover:text-ink">
                  <ChevronDown className={clsx('size-3.5 transition-transform', showArchived && 'rotate-180')} />已归档 {archived.length} 段
                </button>
                {showArchived && archived.map(row)}
              </div>
            )}
          </div>
          <ErrorText error={error} />
        </div>
      )}
    </div>
  )
}
