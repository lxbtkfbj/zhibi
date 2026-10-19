/** 新书页的「存档」：居中弹窗，整本书一档一档往后存（设计说明 9.13「第二批：存档」）。
 *  最上面「存一档」；下面时间倒排、按天分组，手动存的带书签最显眼，自动存的连着几条折成一行；
 *  点开一档看和现在比改了哪些，能「回到这一档」（整本，连正文）。 */

import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Archive, Bookmark, Check, ChevronDown, ChevronLeft, ChevronRight, History, LoaderCircle, RotateCcw, Save, ShieldCheck, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { get, post } from '../../api/client'
import type { BookSave, SaveCompare } from '../../api/types'
import { ErrorText } from '../../components/ui'
import { useBookContext } from '../book/context'
import './saves.css'

const savesKey = (bookId: string) => ['saves', bookId] as const

function day(iso: string) {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, today)) return '今天'
  if (same(d, yesterday)) return '昨天'
  return `${d.getFullYear() !== today.getFullYear() ? `${d.getFullYear()} 年 ` : ''}${d.getMonth() + 1} 月 ${d.getDate()} 日`
}
const clock = (iso: string) => new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
const stamp = (iso: string) => `${new Date(iso).toLocaleDateString('zh-CN')} ${clock(iso)}`
const progress = (chapter: number) => chapter ? `定稿至第 ${chapter} 章` : '尚无定稿章节'
const KINDS = { manual: '手动存档', auto: '自动存档', restore: '恢复记录' } as const

function KindBadge({ kind }: { kind: BookSave['kind'] }) {
  return <span className={clsx('shrink-0 rounded-md px-2 py-0.5 text-[11px] font-normal whitespace-nowrap', kind === 'manual' ? 'bg-seal-soft text-seal-dark' : kind === 'restore' ? 'bg-chief-soft text-chief' : 'bg-paper-2 text-ink-2')}>{KINDS[kind]}</span>
}

/** 列表摘要相对上一档，不冒充与当前书稿的比较。 */
function summaryText(save: BookSave) {
  if (save.summary.first) return '起始版本 · 从这里开始保留这本书'
  if (!save.count) return '较上一档 · 内容未变，保留一个标记'
  const groups = [...new Set((save.summary.items ?? []).map(item => item.group))]
  return `较上一档 · ${save.count} 处变化${groups.length ? ` · ${groups.slice(0, 3).join('、')}${groups.length > 3 ? '等' : ''}` : ''}`
}

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
  const finished = [...new Set(saves.flatMap((s) => s.summary.finished ?? []).map((f) => f.index))].sort((a, b) => a - b)
  const count = saves.reduce((sum, s) => sum + s.count, 0)
  const who = saves.every((s) => s.actor === 'author') ? '你自己' : saves.some((s) => s.actor === 'author') ? '你和编辑部' : '编辑部'
  if (finished.length && saves.every((s) => s.summary.finished?.length)) {
    const consecutive = finished.every((chapter, index) => index === 0 || chapter === finished[index - 1] + 1)
    return finished.length === 1 ? `写完第 ${finished[0]} 章` : consecutive ? `写完第 ${finished[0]}–${finished.at(-1)} 章` : `写完 ${finished.length} 章`
  }
  return `${who}改了 ${count} 处` + (finished.length ? `，写完 ${finished.length} 章` : '')
}

function SaveLine({ save, onOpen, nested }: { save: BookSave; onOpen: (id: number) => void; nested?: boolean }) {
  const manual = save.kind === 'manual'
  return (
    <button type="button" onClick={() => onOpen(save.id)}
      className={clsx('save-record group flex w-full items-start gap-3 rounded-xl border p-3.5 text-left transition-colors hover:border-line-2 hover:bg-paper-2', manual ? 'border-line-2 bg-card/70' : 'border-line bg-card/30', nested && 'save-record-nested')}>
      <span className={clsx('save-record-icon flex size-9 shrink-0 items-center justify-center rounded-lg', manual ? 'bg-seal-soft text-seal-dark' : 'bg-paper-2 text-ink-3')}>
        {manual ? <Bookmark className="size-4" /> : save.kind === 'restore' ? <RotateCcw className="size-4" /> : <History className="size-4" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="min-w-0 text-[14px] leading-relaxed font-medium break-words text-ink [overflow-wrap:anywhere]">{save.title}</span>
          <KindBadge kind={save.kind} />
        </span>
        <span className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs leading-relaxed text-ink-3">
          <time dateTime={save.created_at} title={stamp(save.created_at)} className="tabular-nums">{clock(save.created_at)}</time>
          <span>{save.actor_name}</span><span>{progress(save.chapters_final)}</span>
        </span>
        <span className="mt-1.5 block text-xs leading-relaxed text-ink-2">{summaryText(save)}</span>
      </span>
      <ChevronRight className="mt-2 size-4 shrink-0 text-ink-3" />
    </button>
  )
}

function FoldLine({ saves, onOpen }: { saves: BookSave[]; onOpen: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const first = saves.at(-1)!, last = saves[0]
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 rounded-xl border border-line bg-card/30 p-3.5 text-left transition-colors hover:bg-paper-2">
        <span className="save-record-icon flex size-9 shrink-0 items-center justify-center rounded-lg bg-paper-2 text-ink-3"><History className="size-4" /></span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2 text-[14px] leading-relaxed text-ink"><span>{foldTitle(saves)}</span><KindBadge kind="auto" /></span>
          <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-3"><span className="tabular-nums">{clock(first.created_at)}–{clock(last.created_at)}</span><span>连续 {saves.length} 档</span><span>{progress(last.chapters_final)}</span></span>
        </span>
        <ChevronDown className={clsx('mt-0.5 size-3.5 shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="mt-2 space-y-2 border-l-2 border-line pl-3">{saves.map((save) => <SaveLine key={save.id} save={save} onOpen={onOpen} nested />)}</div>}
    </div>
  )
}

function SaveList({ onOpen }: { onOpen: (id: number) => void }) {
  const { bookId } = useBookContext()
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const [error, setError] = useState<unknown>(null)
  const [success, setSuccess] = useState('')
  const [filter, setFilter] = useState<'all' | 'manual'>('all')
  const list = useInfiniteQuery({
    queryKey: savesKey(bookId),
    queryFn: ({ pageParam }) => get<{ items: BookSave[]; more: boolean }>(`/books/${bookId}/saves${pageParam ? `?before=${pageParam}` : ''}`),
    initialPageParam: 0,
    getNextPageParam: (page) => (page.more ? page.items.at(-1)?.id : undefined),
  })
  const saves = useMemo(() => list.data?.pages.flatMap((page) => page.items) ?? [], [list.data])
  const days = useMemo(() => {
    const out: { key: string; day: string; rows: Row[] }[] = []
    for (const save of saves.filter(save => filter === 'all' || save.kind === 'manual')) {
      const name = day(save.created_at)
      const date = new Date(save.created_at)
      const key = `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
      if (out.at(-1)?.key !== key) out.push({ key, day: name, rows: [] })
      out.at(-1)!.rows.push({ kind: 'one', save })
    }
    return out.map((group) => ({ ...group, rows: foldRows(group.rows.map((row) => (row as { save: BookSave }).save)) }))
  }, [saves, filter])
  const saveNow = async () => {
    if (savingRef.current) return
    savingRef.current = true
    setSaving(true); setError(null); setSuccess('')
    try {
      const result = await post<{ save: BookSave }>(`/books/${bookId}/saves`, { label: label.trim() })
      setLabel('')
      setSuccess(`已存好「${result.save.title}」`)
      await qc.invalidateQueries({ queryKey: savesKey(bookId) })
    } catch (cause) { setError(cause) } finally { setSaving(false); savingRef.current = false }
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="saves-padding shrink-0 border-b border-line bg-card/25 py-5">
        <label htmlFor="save-name" className="mb-2 block text-[13px] font-medium text-ink">保存当前版本 <span className="ml-1 font-normal text-ink-3">名称选填，不填按时间命名</span></label>
        <div className="save-create-row flex gap-2.5">
          <input id="save-name" aria-label="存档名称（选填）" value={label} disabled={saving} onChange={(e) => { setLabel(e.target.value); setSuccess('') }} maxLength={60}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void saveNow() } }}
            placeholder="起个名字，比如「开局定稿」"
            className="h-10 min-w-0 flex-1 rounded-lg border border-line-2 bg-card px-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-ink-3 disabled:opacity-60" />
          <button type="button" disabled={saving} onClick={() => void saveNow()}
            className="flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-ink px-5 text-[13px] whitespace-nowrap text-paper transition-opacity hover:opacity-90 disabled:opacity-50">
            {saving ? <LoaderCircle className="size-4 animate-spin" /> : <Bookmark className="size-4" />}{saving ? '正在保存…' : '存一档'}
          </button>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">编辑部改完书、你手动修改后停手 3 分钟，都会自动存档。</p>
        {success && <p role="status" className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed break-all text-lore"><Check className="size-4 shrink-0" />{success}</p>}
        <ErrorText error={error} />
      </div>
      <div className="saves-padding flex shrink-0 flex-wrap items-center justify-between gap-2 pt-4 pb-2">
        <h3 className="text-[13px] font-medium text-ink">历史存档 <span className="ml-1 text-xs font-normal text-ink-3">由近到远</span></h3>
        <div aria-label="筛选存档" className="flex gap-1 rounded-lg bg-paper-2 p-1">
          {(['all', 'manual'] as const).map(value => <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)} className={clsx('rounded-md px-2.5 py-1 text-xs whitespace-nowrap transition-colors', filter === value ? 'bg-card text-ink shadow-sm' : 'text-ink-3 hover:text-ink')}>{value === 'all' ? '全部存档' : '手动存档'}</button>)}
        </div>
      </div>
      <div className="saves-padding scroll-thin min-h-0 flex-1 overflow-y-auto overscroll-contain pb-5 [scrollbar-gutter:stable]">
        {list.isPending && <div role="status" className="flex items-center justify-center gap-2 py-14 text-[13px] text-ink-3"><LoaderCircle className="size-4 animate-spin" />正在读存档…</div>}
        {list.isError && <div className="py-6"><p className="text-sm text-ink">存档暂时没读出来</p><ErrorText error={list.error} /><button type="button" onClick={() => void (list.isFetchNextPageError ? list.fetchNextPage() : list.refetch())} className="mt-2 text-xs text-chief underline underline-offset-4">重新读取</button></div>}
        {!list.isPending && !list.isError && !days.length && <div className="flex flex-col items-center px-4 py-10 text-center">
          <span className="mb-4 flex size-14 items-center justify-center rounded-2xl border border-line bg-paper-2 text-ink-3"><Archive className="size-6" strokeWidth={1.5} /></span>
          <p className="font-serif text-lg font-medium text-ink">{filter === 'manual' && saves.length ? list.hasNextPage ? '已加载记录中没有手动存档' : '还没有手动存档' : '还没有存档'}</p>
          <p className="mt-2 max-w-80 text-[13px] leading-relaxed text-ink-3">{filter === 'manual' && saves.length ? '手动存下的重要节点会显示在这里。' : '用上方的「存一档」留住现在的版本，以后可以随时查看改动、回到这里。'}</p>
        </div>}
        {days.map((group) => (
          <section key={group.key} className="mb-3">
            <h4 className="sticky top-0 z-10 bg-paper py-2.5 text-xs font-medium text-ink-3">{group.day}</h4>
            <div className="space-y-2">
              {group.rows.map((row) => row.kind === 'one'
                ? <SaveLine key={row.save.id} save={row.save} onOpen={onOpen} />
                : <FoldLine key={row.saves[0].id} saves={row.saves} onOpen={onOpen} />)}
            </div>
          </section>
        ))}
        {list.hasNextPage && (
          <div className="py-2 text-center">
            {filter === 'manual' && <p className="mb-2 text-xs text-ink-3">仅筛选已加载记录，较早的手动存档可继续加载。</p>}
            <button type="button" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} className="rounded-lg border border-line px-4 py-2 text-xs text-ink-2 hover:bg-paper-2 disabled:opacity-50">{list.isFetchingNextPage ? '正在加载…' : '加载更早的存档'}</button>
          </div>
        )}
      </div>
    </div>
  )
}

function Part({ saveId, table, row, part }: { saveId: number; table: string; row: string; part: SaveCompare['groups'][number]['items'][number]['parts'][number] }) {
  const { bookId } = useBookContext()
  const [full, setFull] = useState<{ then: string; now: string } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(false)
  const then = full?.then ?? part.then, now = full?.now ?? part.now
  const more = async () => {
    if (loading) return
    setLoading(true); setError(null)
    try { setFull(await get(`/books/${bookId}/saves/${saveId}/text?${new URLSearchParams({ table, row, label: part.label })}`)) } catch (cause) { setError(cause) } finally { setLoading(false) }
  }
  const words = part.label === '正文'
  return (
    <div className="mt-3">
      <p className="text-xs font-medium text-ink-2">{part.label}{words ? <span className="ml-2 font-normal text-ink-3">存档时 {part.then_words} 字 · 现在 {part.now_words} 字</span> : ''}</p>
      <div className="save-comparison mt-2 grid gap-2">
        <div className="min-w-0 rounded-lg border border-line bg-paper-2 p-3">
          <span className="mb-1.5 block text-[11px] font-medium text-ink-3">存档时</span>
          <p className="max-h-60 overflow-y-auto text-[13px] leading-7 whitespace-pre-wrap text-ink-2 select-text [overflow-wrap:anywhere]">{then || '（没有）'}</p>
        </div>
        <div className="min-w-0 rounded-lg border border-line bg-card p-3">
          <span className="mb-1.5 block text-[11px] font-medium text-chief">现在</span>
          <p className="max-h-60 overflow-y-auto text-[13px] leading-7 whitespace-pre-wrap text-ink select-text [overflow-wrap:anywhere]">{now || '（没有）'}</p>
        </div>
      </div>
      {part.long && !full && <button type="button" disabled={loading} onClick={() => void more()} className="mt-2 text-xs text-chief underline underline-offset-4 disabled:opacity-50">{loading ? '正在读取…' : '看全文'}</button>}
      <ErrorText error={error} />
    </div>
  )
}

const OP = { add: '现在有，那时没有', del: '那时有，现在没有', mod: '改过' } as const

function ChangeItem({ saveId, item }: { saveId: number; item: SaveCompare['groups'][number]['items'][number] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-line bg-card">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-start gap-2 px-3 py-3 text-left">
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <span className="min-w-0 text-[13px] leading-relaxed break-words text-ink [overflow-wrap:anywhere]">{item.name}</span>
          <span className={clsx('rounded px-1.5 py-0.5 text-[11px]', item.op === 'mod' ? 'bg-line/70 text-ink-2' : item.op === 'add' ? 'bg-seal-soft text-seal-dark' : 'bg-lore/15 text-lore')}>{OP[item.op]}</span>
        </span>
        <ChevronDown className={clsx('size-3.5 shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="border-t border-line px-3 pb-3">{item.parts.length ? item.parts.map((part) => <Part key={part.label} saveId={saveId} table={item.table} row={item.id} part={part} />) : <p className="pt-3 text-xs text-ink-3">只是小地方不一样（顺序、来源这类）。</p>}</div>}
    </div>
  )
}

/** 回到这一档之前说清楚：哪几类会换回去几处，正文退到第几章 */
function restoreText(detail: SaveCompare) {
  const counts = detail.groups.filter((g) => g.name !== '正文' && g.name !== '编辑部记的').map((g) => `${g.name} ${g.items.length} 处`)
  const then = detail.save.chapters_final, now = detail.now_final
  const text = detail.groups.find((g) => g.name === '正文')
  let body = ''
  if (then < now) body = `${then ? `正文会退到第 ${then} 章` : '正文会回到尚无定稿章节的状态'}，第 ${then + 1}${now > then + 1 ? `–${now}` : ''} 章退掉`
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
  const busyRef = useRef(false)
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState(false)
  const blocked = !!job && ['queued', 'running', 'waiting_author'].includes(job.status)
  const restore = async () => {
    if (busyRef.current || blocked) return
    busyRef.current = true
    setBusy(true); setError(null)
    try {
      await post(`/books/${bookId}/saves/${saveId}/restore`)
      setConfirm(false)
      setDone(true)
      // 整本书换过了：书、设定、大纲、正文、本书设置、写作要求都重新读
      for (const key of [['workspace', bookId], ['book', bookId], ['books'], savesKey(bookId), ['chapters', bookId], ['outline-tree', bookId], ['book-settings', bookId], ['author-requirements', bookId]]) void qc.invalidateQueries({ queryKey: key })
    } catch (cause) { setError(cause) } finally { setBusy(false); busyRef.current = false }
  }
  const data = detail.data
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="saves-padding shrink-0 border-b border-line bg-card/25 py-4">
        <button type="button" onClick={onBack} className="-ml-1 flex items-center gap-1 rounded-md px-1 py-1 text-xs text-ink-2 hover:bg-line/50 hover:text-ink"><ChevronLeft className="size-3.5" />所有存档</button>
        {data && <>
          <div className="mt-2 flex flex-wrap items-center gap-2"><h3 className="max-h-20 min-w-0 overflow-y-auto text-[17px] leading-relaxed font-medium break-words text-ink [overflow-wrap:anywhere]">{data.save.title}</h3><KindBadge kind={data.save.kind} /></div>
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3"><time dateTime={data.save.created_at}>{stamp(data.save.created_at)}</time><span>{data.save.actor_name}</span><span>{progress(data.save.chapters_final)}</span></div>
        </>}
      </div>
      <div className="saves-padding scroll-thin min-h-0 flex-1 overflow-y-auto overscroll-contain py-5 [scrollbar-gutter:stable]">
        {detail.isPending && <p role="status" className="py-10 text-center text-[13px] text-ink-3">正在对比存档与现在的书稿…</p>}
        <ErrorText error={detail.error} />
        {detail.isError && <button type="button" onClick={() => void detail.refetch()} className="mt-2 text-xs text-chief underline underline-offset-4">重新读取</button>}
        {done && <p role="status" className="mb-4 rounded-lg bg-lore/10 px-4 py-3 text-[13px] leading-relaxed text-ink">书已经换回这一档了。刚才的样子存成了「回到…之前的样子」那一档，想回来就点开它。</p>}
        {data && (data.same
          ? <div className="py-12 text-center"><Check className="mx-auto mb-3 size-7 text-lore" /><p className="text-sm text-ink">这一档和现在一模一样。</p><p className="mt-2 text-xs text-ink-3">不用恢复，可以继续安心写作。</p></div>
          : <>
            <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-medium text-ink">与现在相比</h3><span className="text-xs text-ink-3">{data.groups.length ? `${data.groups.length} 类内容 · ${data.groups.reduce((count, group) => count + group.items.length, 0)} 处不同` : '内部记录有变化'}</span></div>
            <p className="mb-4 text-xs leading-relaxed text-ink-3">展开一项，对照「存档时」和「现在」。需要旧写法时，可以直接选中文字复制。</p>
            {!data.groups.length && <p className="rounded-lg border border-line bg-paper-2 p-4 text-[13px] leading-relaxed text-ink-2">可展示的内容没有变化，但顺序、来源等内部记录不同；恢复时也会一并换回。</p>}
            {data.groups.map((group) => (
              <section key={group.name} className="mb-5">
                <h4 className="mb-2 text-xs font-medium text-ink-2">{group.name} <span className="ml-1 font-normal text-ink-3">{group.items.length} 处</span></h4>
                <div className="space-y-2">{group.items.map((item) => <ChangeItem key={`${item.table}:${item.id}`} saveId={saveId} item={item} />)}</div>
              </section>
            ))}
          </>)}
      </div>
      {data && !data.same && (
        <div className="saves-padding save-restore-bar flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-line bg-card/25 py-4">
          <div className="min-w-0 flex-1 text-xs leading-relaxed text-ink-3"><p>恢复整本书，包含设定、大纲和正文。</p><p>当前版本会先存一档，聊天记录不变。</p>{blocked && <p role="status" className="mt-1 text-seal-dark">编辑部{job?.status === 'waiting_author' ? '在等你拍板' : '正在干活'}：先{job?.status === 'waiting_author' ? '拍板' : '停下'}再回去。</p>}</div>
          <button type="button" disabled={blocked || busy || done || detail.isError} onClick={() => { setError(null); setConfirm(true) }}
            className="flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-ink px-5 text-[13px] whitespace-nowrap text-paper transition-opacity hover:opacity-90 disabled:opacity-40">
            <RotateCcw className="size-3.5" />回到这一档
          </button>
        </div>
      )}
      {confirm && data && (
        <SaveDialogFrame onClose={() => { if (!busyRef.current) setConfirm(false) }} confirm>
          <div className="overflow-y-auto p-6">
            <RotateCcw className="mb-4 size-6 text-seal-dark" />
            <h2 id="save-restore-title" className="max-h-32 overflow-y-auto font-serif text-xl leading-relaxed font-bold break-words [overflow-wrap:anywhere]">整本书回到「{data.save.title}」？</h2>
            <p id="save-restore-description" className="mt-3 text-[13px] leading-7 text-ink-2">{restoreText(data)}</p>
            <p className="mt-3 rounded-lg bg-paper-2 p-3 text-xs leading-relaxed text-ink-3">聊天记录不动；聊天里会插一行，说明书换回去了。已有的存档也都会保留。</p>
            <ErrorText error={error} />
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button type="button" autoFocus disabled={busy} onClick={() => setConfirm(false)} className="h-10 rounded-lg border border-line px-4 text-[13px] text-ink-2 hover:bg-line/50 disabled:opacity-50">先不了</button>
              <button type="button" disabled={busy || blocked} onClick={() => void restore()} className="h-10 rounded-lg bg-ink px-4 text-[13px] text-paper hover:opacity-90 disabled:opacity-50">{busy ? '正在换回…' : '回到这一档'}</button>
            </div>
          </div>
        </SaveDialogFrame>
      )}
    </div>
  )
}

/** 原生模态层负责背景 inert、焦点约束和嵌套确认框；退出时回到打开它的控件。 */
function SaveDialogFrame({ onClose, confirm = false, children }: { onClose: () => void; confirm?: boolean; children: ReactNode }) {
  const panel = useRef<HTMLDialogElement>(null)
  const downOnBackdrop = useRef(false)
  useEffect(() => {
    const dialog = panel.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    if (!confirm) document.body.style.overflow = 'hidden'
    dialog.showModal()
    return () => {
      dialog.close()
      if (!confirm) document.body.style.overflow = overflow
      if (previous?.isConnected) previous.focus()
    }
  }, [confirm])
  return createPortal(
    <dialog ref={panel} role={confirm ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby={confirm ? 'save-restore-title' : 'saves-title'} aria-describedby={confirm ? 'save-restore-description' : 'saves-description'}
      className={clsx('saves-dialog', confirm && 'saves-confirm')}
      onKeyDown={event => {
        // React 的 portal 事件仍会向父组件冒泡；只约束当前最上层弹窗。
        if (!(event.target instanceof HTMLElement) || event.target.closest('dialog') !== event.currentTarget) return
        if (event.key === 'Escape') event.stopPropagation()
        if (event.key !== 'Tab') return
        const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href], select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')).filter(item => item.getClientRects().length > 0)
        const first = items[0], last = items.at(-1)
        if (!first) { event.preventDefault(); return }
        if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
          event.preventDefault(); last?.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first.focus()
        }
      }}
      onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose() }}
      onPointerDown={event => { downOnBackdrop.current = event.target === event.currentTarget }}
      onClick={event => { if (downOnBackdrop.current && event.target === event.currentTarget) { event.stopPropagation(); onClose() } downOnBackdrop.current = false }}>
      <div className="saves-content flex h-full min-h-0 flex-col overflow-hidden">{children}</div>
    </dialog>, document.body,
  )
}

/** 从侧栏或聊天打开同一份居中存档弹窗，聊天可以直达某一档。 */
export function SavesPanel({ open, saveId, onClose, onOpenSave }: { open: boolean; saveId: number | null; onClose: () => void; onOpenSave: (id: number | null) => void }) {
  if (!open) return null
  return (
    <SaveDialogFrame onClose={onClose}>
      <header className="saves-padding flex shrink-0 items-start gap-3 border-b border-line py-5">
        <span className="save-header-icon mt-0.5 flex size-11 shrink-0 items-center justify-center rounded-xl border border-line bg-paper-2 text-ink-2"><Save className="size-5" strokeWidth={1.5} /></span>
        <div className="min-w-0 flex-1"><h2 id="saves-title" className="font-serif text-[24px] leading-tight font-bold text-ink">存档</h2><p id="saves-description" className="mt-2 text-xs leading-relaxed text-ink-3">留住每个重要版本，查看改动，也能回到从前。</p></div>
        <button type="button" onClick={onClose} aria-label="关上存档" title="关闭（Esc）" className="-mr-2 shrink-0 rounded-lg p-2 text-ink-3 hover:bg-line/50 hover:text-ink"><X className="size-5" /></button>
      </header>
      {saveId === null ? <SaveList onOpen={onOpenSave} /> : <SaveDetail key={saveId} saveId={saveId} onBack={() => onOpenSave(null)} />}
      {saveId === null && <footer className="saves-padding flex shrink-0 items-start gap-2 border-t border-line py-3 text-[11px] leading-relaxed text-ink-3"><ShieldCheck className="mt-0.5 size-3.5 shrink-0" /><span>设定、大纲、正文和本书设置一起保存；聊天记录不在存档内。</span></footer>}
    </SaveDialogFrame>
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

/** 左边一栏最下面那一行「存档 · 几分钟前存过」：点了打开居中弹窗 */
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
      <span className="ml-auto truncate text-xs text-ink-3">{last ? savedAgo(last.created_at, now) : latest.isPending ? '' : latest.isError ? '暂未读到' : '还没存过'}</span>
    </button>
  )
}
