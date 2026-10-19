/** 新书页的「存档」（左边一栏最下面那一行点开）：右边一栏，像 git 那样整本书一档一档往后存（设计说明 9.13「第二批：存档」）。
 *  最上面「存一档」；下面时间倒排、按天分组，手动存的带书签最显眼，自动存的连着几条折成一行；
 *  点开一档看和现在比改了哪些，能「回到这一档」（整本，连正文）。 */

import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bookmark, ChevronDown, ChevronLeft, ChevronRight, RotateCcw, Save, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../../api/client'
import type { BookSave, SaveCompare } from '../../api/types'
import { ErrorText } from '../../components/ui'
import { useBookContext } from '../book/context'

const savesKey = (bookId: string) => ['saves', bookId] as const

function day(iso: string) {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today.getTime() - 86_400_000)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, today)) return '今天'
  if (same(d, yesterday)) return '昨天'
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}
const clock = (iso: string) => new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
const stamp = (iso: string) => `${new Date(iso).getMonth() + 1}-${new Date(iso).getDate()} ${clock(iso)}`

type Row = { kind: 'one'; save: BookSave } | { kind: 'fold'; saves: BookSave[] }

/** 自动存的连着几条折成一行；手动存的、回到某一档的单独一行 */
function foldRows(saves: BookSave[]): Row[] {
  const rows: Row[] = []
  for (const save of saves) {
    const last = rows.at(-1)
    const auto = save.kind === 'auto'
    if (auto && last?.kind === 'fold') last.saves.push(save)
    else if (auto && last?.kind === 'one' && last.save.kind === 'auto') rows[rows.length - 1] = { kind: 'fold', saves: [last.save, save] }
    else rows.push({ kind: 'one', save })
  }
  return rows
}

function foldTitle(saves: BookSave[]) {
  const finished = saves.flatMap((s) => s.summary.finished ?? []).map((f) => f.index).sort((a, b) => a - b)
  const count = saves.reduce((sum, s) => sum + s.count, 0)
  const who = saves.every((s) => s.actor === 'author') ? '你自己' : saves.some((s) => s.actor === 'author') ? '你和编辑部' : '编辑部'
  if (finished.length && finished.length === saves.filter((s) => s.summary.finished?.length).length && saves.every((s) => s.summary.finished?.length)) {
    return finished.length === 1 ? `写完第 ${finished[0]} 章` : `写完第 ${finished[0]}–${finished.at(-1)} 章`
  }
  return `${who}改了 ${count} 处` + (finished.length ? `，写完 ${finished.length} 章` : '')
}

function SaveLine({ save, onOpen, nested }: { save: BookSave; onOpen: (id: number) => void; nested?: boolean }) {
  const manual = save.kind === 'manual'
  return (
    <button type="button" onClick={() => onOpen(save.id)}
      className={clsx('flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left transition-colors hover:bg-line/40', manual && 'bg-paper-2 ring-1 ring-line', nested && 'py-1.5 pl-8')}>
      <span className="mt-0.5 w-10 shrink-0 text-xs text-ink-3 tabular-nums">{clock(save.created_at)}</span>
      <span className="min-w-0 flex-1">
        <span className={clsx('flex items-center gap-1.5 text-[13px] leading-snug', manual ? 'font-medium text-ink' : 'text-ink-2')}>
          {manual && <Bookmark className="size-3.5 shrink-0 fill-seal text-seal" />}
          {save.kind === 'restore' && <RotateCcw className="size-3.5 shrink-0 text-chief" />}
          <span className="break-words">{save.title}</span>
        </span>
        <span className="mt-0.5 block text-[11px] text-ink-3">
          {save.actor_name}{save.chapters_final ? ` · 写到第 ${save.chapters_final} 章` : ''}
        </span>
      </span>
      <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-ink-3" />
    </button>
  )
}

function FoldLine({ saves, onOpen }: { saves: BookSave[]; onOpen: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const first = saves.at(-1)!, last = saves[0]
  return (
    <div>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left transition-colors hover:bg-line/40">
        <span className="mt-0.5 w-10 shrink-0 text-xs text-ink-3 tabular-nums">{clock(last.created_at)}</span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] leading-snug text-ink-2">{foldTitle(saves)}</span>
          <span className="mt-0.5 block text-[11px] text-ink-3">{clock(first.created_at)} 起 {saves.length} 档{last.chapters_final ? ` · 写到第 ${last.chapters_final} 章` : ''}</span>
        </span>
        <ChevronDown className={clsx('mt-0.5 size-3.5 shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && saves.map((save) => <SaveLine key={save.id} save={save} onOpen={onOpen} nested />)}
    </div>
  )
}

function SaveList({ onOpen }: { onOpen: (id: number) => void }) {
  const { bookId } = useBookContext()
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const list = useInfiniteQuery({
    queryKey: savesKey(bookId),
    queryFn: ({ pageParam }) => get<{ items: BookSave[]; more: boolean }>(`/books/${bookId}/saves${pageParam ? `?before=${pageParam}` : ''}`),
    initialPageParam: 0,
    getNextPageParam: (page) => (page.more ? page.items.at(-1)?.id : undefined),
  })
  const saves = useMemo(() => list.data?.pages.flatMap((page) => page.items) ?? [], [list.data])
  const days = useMemo(() => {
    const out: { day: string; rows: Row[] }[] = []
    for (const save of saves) {
      const name = day(save.created_at)
      if (out.at(-1)?.day !== name) out.push({ day: name, rows: [] })
      out.at(-1)!.rows.push({ kind: 'one', save })
    }
    return out.map((group) => ({ day: group.day, rows: foldRows(group.rows.map((row) => (row as { save: BookSave }).save)) }))
  }, [saves])
  const saveNow = async () => {
    setSaving(true); setError(null)
    try {
      await post(`/books/${bookId}/saves`, { label: label.trim() })
      setLabel('')
      await qc.invalidateQueries({ queryKey: savesKey(bookId) })
    } catch (cause) { setError(cause) } finally { setSaving(false) }
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-line px-4 py-3">
        <div className="flex gap-2">
          <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) void saveNow() }}
            placeholder="起个名字，比如「开局定稿」（可以不起）"
            className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-card px-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-ink-3" />
          <button type="button" disabled={saving} onClick={() => void saveNow()}
            className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-ink px-3 text-[13px] text-paper transition-opacity hover:opacity-90 disabled:opacity-50">
            <Bookmark className="size-3.5" />存一档
          </button>
        </div>
        <p className="mt-1.5 text-[11px] leading-relaxed text-ink-3">编辑部每次动完书、你自己改完停手 3 分钟，都会自动存一档。在聊天里说「存个档，叫……」也行。</p>
        <ErrorText error={error} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {list.isPending && <p className="px-3 py-6 text-center text-[13px] text-ink-3">正在读存档…</p>}
        <ErrorText error={list.error} />
        {!list.isPending && !saves.length && <p className="px-3 py-6 text-center text-[13px] leading-relaxed text-ink-3">还没有存档。点上面「存一档」，或者等编辑部动一次书，就有第一档了。</p>}
        {days.map((group) => (
          <section key={group.day} className="mb-2">
            <h3 className="sticky top-0 z-10 bg-paper px-3 py-1.5 text-[11px] font-medium text-ink-3">{group.day}</h3>
            <div className="space-y-0.5">
              {group.rows.map((row) => row.kind === 'one'
                ? <SaveLine key={row.save.id} save={row.save} onOpen={onOpen} />
                : <FoldLine key={row.saves[0].id} saves={row.saves} onOpen={onOpen} />)}
            </div>
          </section>
        ))}
        {list.hasNextPage && (
          <button type="button" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} className="mx-auto my-2 block text-xs text-ink-3 underline underline-offset-4 hover:text-ink">更早的</button>
        )}
      </div>
    </div>
  )
}

function Part({ saveId, table, row, part }: { saveId: number; table: string; row: string; part: SaveCompare['groups'][number]['items'][number]['parts'][number] }) {
  const { bookId } = useBookContext()
  const [full, setFull] = useState<{ then: string; now: string } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const then = full?.then ?? part.then, now = full?.now ?? part.now
  const more = async () => {
    try { setFull(await get(`/books/${bookId}/saves/${saveId}/text?table=${table}&row=${row}&label=${encodeURIComponent(part.label)}`)) } catch (cause) { setError(cause) }
  }
  const words = part.label === '正文'
  return (
    <div className="mt-1.5">
      <p className="text-[11px] text-ink-3">{part.label}{words ? `（那时 ${part.then_words} 字，现在 ${part.now_words} 字）` : ''}</p>
      <div className="mt-1 grid gap-1.5">
        <div className="rounded-md bg-paper-2 px-2.5 py-1.5">
          <span className="text-[11px] text-ink-3">那时</span>
          <p className="max-h-60 overflow-y-auto text-[13px] leading-relaxed whitespace-pre-line text-ink-2 select-text">{then || '（没有）'}</p>
        </div>
        <div className="rounded-md bg-card px-2.5 py-1.5 ring-1 ring-line">
          <span className="text-[11px] text-ink-3">现在</span>
          <p className="max-h-60 overflow-y-auto text-[13px] leading-relaxed whitespace-pre-line text-ink select-text">{now || '（没有）'}</p>
        </div>
      </div>
      {part.long && !full && <button type="button" onClick={() => void more()} className="mt-1 text-xs text-ink-3 underline underline-offset-4 hover:text-ink">看全文</button>}
      <ErrorText error={error} />
    </div>
  )
}

const OP = { add: '现在有，那时没有', del: '那时有，现在没有', mod: '改过' } as const

function ChangeItem({ saveId, item }: { saveId: number; item: SaveCompare['groups'][number]['items'][number] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-line bg-card">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{item.name}</span>
        <span className={clsx('shrink-0 rounded px-1.5 text-[11px]', item.op === 'mod' ? 'bg-line/70 text-ink-2' : item.op === 'add' ? 'bg-seal-soft text-seal-dark' : 'bg-lore/15 text-lore')}>{OP[item.op]}</span>
        <ChevronDown className={clsx('size-3.5 shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="border-t border-line px-3 pb-2.5">{item.parts.length ? item.parts.map((part) => <Part key={part.label} saveId={saveId} table={item.table} row={item.id} part={part} />) : <p className="pt-2 text-xs text-ink-3">只是小地方不一样（顺序、来源这类）。</p>}</div>}
    </div>
  )
}

/** 回到这一档之前说清楚：哪几类会换回去几处，正文退到第几章 */
function restoreText(detail: SaveCompare) {
  const counts = detail.groups.filter((g) => g.name !== '正文' && g.name !== '编辑部记的').map((g) => `${g.name} ${g.items.length} 处`)
  const then = detail.save.chapters_final, now = detail.now_final
  const text = detail.groups.find((g) => g.name === '正文')
  let body = ''
  if (then < now) body = `正文会退到第 ${then} 章，第 ${then + 1}${now > then + 1 ? `–${now}` : ''} 章退掉`
  else if (then > now) body = `正文会回到写到第 ${then} 章的样子`
  else if (text) body = `正文有 ${text.items.length} 章换回那时的样子`
  const parts = [counts.length ? `${counts.join('、')}会换回去` : '', body].filter(Boolean)
  return `${parts.join('；') || '和现在几乎一样'}；现在的样子会先存一档，随时能回来。`
}

function SaveDetail({ saveId, onBack }: { saveId: number; onBack: () => void }) {
  const { bookId, job } = useBookContext()
  const qc = useQueryClient()
  const detail = useQuery({ queryKey: [...savesKey(bookId), saveId], queryFn: () => get<SaveCompare>(`/books/${bookId}/saves/${saveId}`), staleTime: 0 })
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState(false)
  const blocked = !!job && ['queued', 'running', 'waiting_author'].includes(job.status)
  const restore = async () => {
    setBusy(true); setError(null)
    try {
      await post(`/books/${bookId}/saves/${saveId}/restore`)
      setConfirm(false)
      setDone(true)
      // 整本书换过了：书、设定、大纲、正文、本书设置、写作要求都重新读
      for (const key of [['workspace', bookId], ['book', bookId], ['books'], savesKey(bookId), ['chapters', bookId], ['outline-tree', bookId], ['book-settings', bookId], ['author-requirements', bookId]]) void qc.invalidateQueries({ queryKey: key })
    } catch (cause) { setError(cause) } finally { setBusy(false) }
  }
  const data = detail.data
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-line px-4 py-3">
        <button type="button" onClick={onBack} className="-ml-1 flex items-center gap-0.5 rounded-md px-1 py-0.5 text-xs text-ink-3 hover:bg-line/50 hover:text-ink"><ChevronLeft className="size-3.5" />所有存档</button>
        {data && <>
          <p className="mt-1.5 flex items-center gap-1.5 text-[15px] font-medium leading-snug text-ink">
            {data.save.kind === 'manual' && <Bookmark className="size-4 shrink-0 fill-seal text-seal" />}{data.save.title}
          </p>
          <p className="mt-0.5 text-xs text-ink-3">{stamp(data.save.created_at)} · {data.save.actor_name}{data.save.chapters_final ? ` · 写到第 ${data.save.chapters_final} 章` : ''}</p>
        </>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {detail.isPending && <p className="py-6 text-center text-[13px] text-ink-3">正在比…</p>}
        <ErrorText error={detail.error} />
        {done && <p className="mb-3 rounded-lg bg-lore/10 px-3 py-2 text-[13px] leading-relaxed text-ink">书已经换回这一档了。刚才的样子存成了「回到…之前的样子」那一档，想回来就点开它。</p>}
        {data && (data.same
          ? <p className="py-6 text-center text-[13px] text-ink-3">这一档和现在一模一样。</p>
          : <>
            <p className="mb-2 text-xs text-ink-3">这一档和现在比，改了这些（点开看「那时」「现在」；字能选中复制）：</p>
            {data.groups.map((group) => (
              <section key={group.name} className="mb-3">
                <h3 className="mb-1.5 text-xs font-medium text-ink-2">{group.name} · {group.items.length} 处</h3>
                <div className="space-y-1.5">{group.items.map((item) => <ChangeItem key={`${item.table}:${item.id}`} saveId={saveId} item={item} />)}</div>
              </section>
            ))}
          </>)}
      </div>
      {data && !data.same && (
        <div className="shrink-0 border-t border-line px-4 py-3">
          <button type="button" disabled={blocked || busy} onClick={() => setConfirm(true)}
            className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-ink text-[13px] text-paper transition-opacity hover:opacity-90 disabled:opacity-40">
            <RotateCcw className="size-3.5" />回到这一档
          </button>
          {blocked && <p className="mt-1.5 text-xs text-ink-3">编辑部{job?.status === 'waiting_author' ? '在等你拍板' : '正在干活'}：先{job?.status === 'waiting_author' ? '拍板' : '停下'}再回去。</p>}
        </div>
      )}
      {confirm && data && (
        <div className="absolute inset-0 z-20 flex items-end bg-ink/20 p-3">
          <div className="w-full rounded-xl border border-line bg-card p-4 shadow-[var(--shadow-lift)]">
            <p className="text-[15px] font-medium text-ink">整本书回到「{data.save.title}」？</p>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{restoreText(data)}</p>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-3">聊天记录不动；聊天里会插一行，说明书换回去了。</p>
            <ErrorText error={error} />
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" onClick={() => setConfirm(false)} className="h-8 rounded-lg px-3 text-[13px] text-ink-2 hover:bg-line/50">先不了</button>
              <button type="button" disabled={busy} onClick={() => void restore()} className="h-8 rounded-lg bg-ink px-3 text-[13px] text-paper hover:opacity-90 disabled:opacity-50">{busy ? '正在换回…' : '回到这一档'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** 存档：右边那一栏 */
export function SavesPanel({ open, saveId, onClose, onOpenSave }: { open: boolean; saveId: number | null; onClose: () => void; onOpenSave: (id: number | null) => void }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <aside aria-label="存档" className="fixed top-14 right-0 bottom-0 z-40 flex w-[min(420px,100vw)] flex-col border-l border-line bg-paper shadow-[var(--shadow-lift)] 2xl:top-16">
      <div className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-2.5">
        <Save className="size-4 text-ink-3" />
        <h2 className="flex-1 text-[15px] font-medium text-ink">存档</h2>
        <button type="button" onClick={onClose} aria-label="关上存档" className="rounded-md p-1 text-ink-3 hover:bg-line/50 hover:text-ink"><X className="size-4" /></button>
      </div>
      {saveId === null ? <SaveList onOpen={onOpenSave} /> : <SaveDetail key={saveId} saveId={saveId} onBack={() => onOpenSave(null)} />}
    </aside>
  )
}

/** 最近一档是多久以前存的：一分钟以内「刚存过」，一小时以内按分钟，一天以内按小时，再早写日子 */
function savedAgo(iso: string, now: number) {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return '刚存过'
  if (minutes < 60) return `${minutes} 分钟前存过`
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} 小时前存过`
  return `${day(iso)}存过`
}

/** 左边一栏最下面那一行「存档 · 几分钟前存过」：点了打开右边那一栏 */
export function SavesRow({ open, onClick, className }: { open: boolean; onClick: () => void; className: string }) {
  const { bookId } = useBookContext()
  const latest = useQuery({ queryKey: [...savesKey(bookId), 'latest'], queryFn: () => get<{ items: BookSave[] }>(`/books/${bookId}/saves?limit=1`) })
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  const last = latest.data?.items[0]
  return (
    <button type="button" onClick={onClick} aria-pressed={open} title="整本书的存档：看改了什么、回到以前的哪一档"
      className={clsx(className, open && 'bg-line/50 text-ink')}>
      <Save className="size-4 shrink-0" />存档
      <span className="ml-auto truncate text-xs text-ink-3">{last ? savedAgo(last.created_at, now) : latest.isPending ? '' : '还没存过'}</span>
    </button>
  )
}
