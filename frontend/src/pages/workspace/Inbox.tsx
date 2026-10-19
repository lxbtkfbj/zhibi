/** 新书页「待处理」（第四步第二批）：在编辑部窗口里，顶上「待处理」点了整个窗口换成这一页，「回到聊天」换回来；
 *  收成小球时有待处理，小球旁边多一个「N 条待处理」。一条一条是编辑部「我建议这样改，你同不同意」。
 *  有具体改法的：同意 / 不用了；同意以后当场摆出改前改后和「换回原来的」（和聊天里改完一样）。
 *  只说了毛病的、群聊里说了当时没改的：让编辑部改（当成你在聊天里说的一句话）/ 知道了。
 *  挂在某一条设定、某一段大纲上的，那一页最上面提醒一行（PendingNote）。 */

import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, ChevronDown, Inbox } from 'lucide-react'
import { useContext, useEffect, useMemo, useState } from 'react'
import { get, post } from '../../api/client'
import { libraryKeys, type LibrarySuggestion, useAcceptedSuggestions, useLibrarySuggestions, useSuggestionChanges } from '../../api/library'
import type { ChangeDiff } from '../../api/types'
import { ErrorText } from '../../components/ui'
import { DiffBlock } from '../book/ChatActions'
import { useBookContext } from '../book/context'
import { handOver, PendingContext, pendingTarget, previewOf, sourceOf } from './pending'

interface SuggestionResult { change?: unknown[]; diff?: ChangeDiff[]; target_label?: string; undone?: boolean; to_chat?: number }
const resultOf = (s: LibrarySuggestion) => (s.payload.result ?? null) as SuggestionResult | null

/** 编辑部窗口顶上的「待处理」：点了窗口换成待处理那一页，再点回到聊天 */
export function PendingButton({ count, open, onClick }: { count: number; open: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={open} title={open ? '回到聊天' : '编辑部觉得该改、等你定的建议'}
      className={clsx('flex h-8 items-center gap-1 rounded-md px-1.5 text-[13px] transition-colors hover:bg-line/60 hover:text-ink', open ? 'bg-line/60 text-ink' : 'text-ink-3')}>
      <Inbox className="size-4" />待处理
      {count > 0 && <span className="flex min-w-5 items-center justify-center rounded-full bg-seal px-1.5 text-[11px] leading-5 text-on-role">{count}</span>}
    </button>
  )
}

/** 编辑部收成小球时，有待处理就在小球左边说一声；点了打开编辑部、直接到待处理 */
export function PendingBallTag({ count, onClick }: { count: number; onClick: () => void }) {
  if (!count) return null
  return (
    <button type="button" onClick={onClick} data-testid="pending-ball-tag"
      className="press flex h-8 items-center gap-1.5 rounded-full border border-seal/30 bg-card px-3 text-[13px] text-seal-dark shadow-[0_8px_20px_-12px_rgb(40_25_10/0.5)] transition-colors hover:border-seal/60">
      <span aria-hidden className="size-1.5 rounded-full bg-seal" />{count} 条待处理
    </button>
  )
}

/** 设定、大纲那一页最上面一行：编辑部对这一条有几个建议 */
export function PendingNote({ id }: { id: string }) {
  const notes = useContext(PendingContext)
  const n = notes?.count(id) ?? 0
  if (!notes || !n) return null
  return (
    <p data-testid="pending-note" className="mb-4 flex w-fit items-center gap-1.5 rounded-lg bg-seal-soft/60 px-3 py-1.5 text-[13px] text-seal-dark">
      <Inbox className="size-3.5" />编辑部对这一条有 {n} 个建议 ·
      <button type="button" onClick={() => notes.open(id)} className="font-medium hover:underline">看看</button>
    </p>
  )
}

const button = 'h-7 rounded-md px-2.5 text-[13px] transition-colors disabled:opacity-40'
const primary = clsx(button, 'bg-ink text-paper-2 hover:bg-ink-2')
const quiet = clsx(button, 'text-ink-3 hover:bg-line/50 hover:text-ink')

function Item({ suggestion, fresh, focused, onDone, seeChat }: { suggestion: LibrarySuggestion; fresh?: boolean; focused: boolean; onDone: (row: LibrarySuggestion) => void; seeChat: () => void }) {
  const { bookId, working, openTarget, chatConv } = useBookContext()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const result = resultOf(suggestion)
  const target = pendingTarget(suggestion)
  const run = async (request: () => Promise<LibrarySuggestion | void>) => {
    setBusy(true)
    setError(null)
    try {
      const row = await request()
      if (row) onDone(row)
      await qc.invalidateQueries({ queryKey: libraryKeys.suggestions(bookId) })
      await qc.invalidateQueries({ queryKey: ['workspace', bookId] })
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }
  const accept = () => run(() => post<LibrarySuggestion>(`/suggestions/${suggestion.id}/accept`))
  const ignore = () => run(() => post<LibrarySuggestion>(`/suggestions/${suggestion.id}/ignore`))
  const revert = () => run(() => post<LibrarySuggestion>(`/suggestions/${suggestion.id}/revert`))
  const toChat = () => run(async () => {
    const note = await post<{ id: number }>(`/suggestions/${suggestion.id}/to-chat`, chatConv ? { conv: chatConv } : {})
    seeChat()
    return { ...suggestion, status: 'accepted', payload: { ...suggestion.payload, result: { to_chat: note.id } } }
  })
  const go = target && openTarget ? () => openTarget(target.type, target.id) : undefined
  const why = String(suggestion.payload.why ?? '')
  const preview = suggestion.status === 'pending' ? previewOf(suggestion) : ''
  const pending = suggestion.status === 'pending'
  return (
    <li id={`pending-${suggestion.id}`} data-testid={`pending-${suggestion.id}`}
      className={clsx('rounded-xl border bg-card px-3.5 py-3 transition-shadow', focused ? 'border-seal/50 shadow-[0_0_0_3px_rgb(180_60_40/0.12)]' : 'border-line')}>
      <p className="text-xs text-ink-3">{sourceOf(suggestion)}</p>
      <p className="mt-1 text-[14px] leading-relaxed break-words text-ink">{suggestion.title.replaceAll('（已锁）', '')}</p>
      {why && !suggestion.title.includes(why) && <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{why}</p>}
      {preview && <p className="mt-1.5 line-clamp-3 rounded-lg bg-subtle px-2.5 py-1.5 text-[13px] leading-relaxed text-ink-2">{preview}</p>}
      {pending ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {handOver(suggestion) ? (
            <>
              <button type="button" disabled={busy || working} onClick={() => void toChat()} className={primary}
                title={working ? '编辑部正在干活，等这一轮做完再让它改' : '当成你在聊天里说「照这条意见改」：编辑部自己找要改哪、改完在聊天里给你看改前改后'}>让编辑部改</button>
              <button type="button" disabled={busy} onClick={() => void (suggestion.kind === 'chat' ? ignore() : accept())} className={quiet}>{suggestion.kind === 'chat' ? '不用了' : '知道了'}</button>
            </>
          ) : (
            <>
              <button type="button" disabled={busy} onClick={() => void accept()} className={primary}>同意</button>
              <button type="button" disabled={busy} onClick={() => void ignore()} className={quiet}>不用了</button>
            </>
          )}
          {go && <button type="button" onClick={go} className="ml-auto text-xs text-chief hover:underline">去看看</button>}
        </div>
      ) : (
        <div className="mt-2 space-y-1.5 text-xs text-ink-2">
          {result?.to_chat ? (
            <p>交给编辑部了 · <button type="button" onClick={seeChat} className="text-chief hover:underline">去聊天里看</button></p>
          ) : result?.undone ? (
            <p>已换回原来的</p>
          ) : result?.diff?.length ? (
            <>
              <p>同意了，改了：</p>
              {result.diff.map((d, i) => <DiffBlock key={i} diff={d} />)}
              <div className="flex flex-wrap items-center gap-3 pt-0.5">
                <button type="button" disabled={busy || fresh === false} onClick={() => void revert()}
                  title={fresh === false ? '这一处后来又改过；要退就去存档' : '这一处换回改之前的样子'}
                  className="underline underline-offset-4 hover:text-chief disabled:no-underline disabled:opacity-40">换回原来的</button>
                {go && <button type="button" onClick={go} className="underline underline-offset-4 hover:text-chief">去看看</button>}
                {fresh === false && <span className="text-ink-3">这一处后来又改过；要退就去存档</span>}
              </div>
            </>
          ) : (
            <p>{suggestion.status === 'ignored' ? '不用了' : '知道了'}</p>
          )}
        </div>
      )}
      <ErrorText error={error} />
    </li>
  )
}

/** 让编辑部再看一遍设定：看还缺什么（补漏）、把设定从头查一遍（找对不上的）。看出来的放进待处理。旧版书页的「补漏」「检查」搬到这里。 */
function AskEditorial() {
  const { bookId, working } = useBookContext()
  const qc = useQueryClient()
  const [doing, setDoing] = useState<'gaps' | 'review' | null>(null)
  const [said, setSaid] = useState('')
  const [error, setError] = useState<unknown>(null)
  const run = async (kind: 'gaps' | 'review') => {
    setDoing(kind)
    setSaid('')
    setError(null)
    try {
      const res = await post<{ suggestions?: LibrarySuggestion[] }>(`/books/${bookId}/library/${kind === 'gaps' ? 'fill-gaps' : 'review'}`)
      const n = res.suggestions?.length ?? 0
      setSaid(n ? `看完了，多了 ${n} 条，在下面` : kind === 'gaps' ? '看完了，没发现缺什么' : '查完了，没发现对不上的')
      await qc.invalidateQueries({ queryKey: libraryKeys.suggestions(bookId) })
    } catch (cause) {
      setError(cause)
    } finally {
      setDoing(null)
    }
  }
  const ask = 'h-8 flex-1 rounded-lg border border-line-2 bg-card px-2 text-[13px] text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink disabled:opacity-50'
  return (
    <div>
      <div className="flex gap-2">
        <button type="button" disabled={!!doing || working} onClick={() => void run('gaps')} className={ask}
          title={working ? '编辑部正在干活，等这一轮做完' : '设定师照简介和大纲看看设定还缺哪几条，看出来的放进待处理'}>{doing === 'gaps' ? '设定师在看…' : '看看设定还缺什么'}</button>
        <button type="button" disabled={!!doing || working} onClick={() => void run('review')} className={ask}
          title={working ? '编辑部正在干活，等这一轮做完' : '审稿把设定从头查一遍，前后对不上、不好看的放进待处理'}>{doing === 'review' ? '审稿在查…' : '把设定查一遍'}</button>
      </div>
      {said && <p className="mt-1.5 text-xs text-ink-3">{said}</p>}
      <ErrorText error={error} />
    </div>
  )
}

/** 编辑部窗口里的待处理那一页：左上「回到聊天」 */
export function PendingList({ focus, onBack }: { focus: string | null; onBack: () => void }) {
  const { bookId, showChat } = useBookContext()
  const qc = useQueryClient()
  const pending = useLibrarySuggestions(bookId)
  const accepted = useAcceptedSuggestions(bookId, true)
  const changes = useSuggestionChanges(bookId, true)
  // 交给编辑部改了：回到聊天看它改
  const seeChat = () => { onBack(); showChat?.() }
  // 这一回点过的：留在原处，摆出结果（改前改后、交给编辑部了……）
  const [kept, setKept] = useState<Record<string, LibrarySuggestion>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [showOld, setShowOld] = useState(false)
  const items = useMemo(() => {
    const rows = new Map((pending.data ?? []).map((s) => [s.id, s]))
    for (const [id, row] of Object.entries(kept)) rows.set(id, row)
    return [...rows.values()].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '') || a.id.localeCompare(b.id))
  }, [pending.data, kept])
  const focused = focus ? items.find((s) => s.status === 'pending' && pendingTarget(s)?.id === focus)?.id : undefined
  useEffect(() => {
    if (focused) document.getElementById(`pending-${focused}`)?.scrollIntoView({ block: 'center' })
  }, [focused])
  const waiting = items.filter((s) => s.status === 'pending')
  const concrete = waiting.filter((s) => !handOver(s))
  const old = (accepted.data ?? []).filter((s) => !kept[s.id] && resultOf(s)?.diff?.length).slice(0, 20)
  const acceptAll = async () => {
    setBusy(true)
    setError(null)
    try {
      const done = await post<{ accepted: string[] }>(`/books/${bookId}/suggestions/accept-all?only_changes=true`)
      const rows = await qc.fetchQuery({ queryKey: [...libraryKeys.suggestions(bookId), 'accepted'], queryFn: () => get<LibrarySuggestion[]>(`/books/${bookId}/suggestions?status=accepted`) })
      setKept((now) => ({ ...now, ...Object.fromEntries(rows.filter((s) => done.accepted.includes(s.id)).map((s) => [s.id, s])) }))
      await qc.invalidateQueries({ queryKey: libraryKeys.suggestions(bookId) })
      await qc.invalidateQueries({ queryKey: ['workspace', bookId] })
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-label="待处理" className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-line bg-subtle/60 px-3 py-1.5">
        <button type="button" onClick={onBack} className="flex h-7 items-center gap-1 rounded-md px-1.5 text-[13px] text-ink-2 hover:bg-line/60 hover:text-ink">
          <ArrowLeft className="size-3.5" />回到聊天
        </button>
        <h2 className="ml-auto text-[13px] text-ink-3">待处理{waiting.length > 0 && ` · ${waiting.length} 条等你看`}</h2>
      </div>
      <div className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        <p className="text-[13px] leading-relaxed text-ink-3">编辑部觉得该改、又没直接动手的，放在这里等你定。有具体改法的点「同意」就照着改，改完当场给你看改前改后；只说了毛病的，可以「让编辑部改」。</p>
        <AskEditorial />
        {concrete.length > 1 && (
          <button type="button" disabled={busy} onClick={() => void acceptAll()} className="h-8 w-full rounded-lg border border-line-2 bg-card text-[13px] text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink disabled:opacity-50">
            {busy ? '正在照着改…' : `有具体改法的 ${concrete.length} 条全部同意`}
          </button>
        )}
        <ErrorText error={error} />
        {pending.isPending ? <p className="text-[13px] text-ink-3">正在读…</p>
          : items.length === 0 ? <p className="py-6 text-center text-[13px] text-ink-3">没有等你看的</p>
            : (
              <ul className="space-y-2.5">
                {items.map((s) => (
                  <Item key={s.id} suggestion={s} fresh={changes.data?.[s.id]} focused={s.id === focused} seeChat={seeChat}
                    onDone={(row) => setKept((now) => ({ ...now, [row.id]: row }))} />
                ))}
              </ul>
            )}
        {old.length > 0 && (
          <div className="border-t border-line pt-3">
            <button type="button" onClick={() => setShowOld(!showOld)} aria-expanded={showOld} className="flex items-center gap-1 text-xs text-ink-3 hover:text-ink">
              <ChevronDown className={clsx('size-3.5 transition-transform', showOld && 'rotate-180')} />以前同意的 {old.length} 条
            </button>
            {showOld && (
              <ul className="mt-2 space-y-2.5">
                {old.map((s) => <Item key={s.id} suggestion={s} fresh={changes.data?.[s.id]} focused={false} seeChat={seeChat} onDone={(row) => setKept((now) => ({ ...now, [row.id]: row }))} />)}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
