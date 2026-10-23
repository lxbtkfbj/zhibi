import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, NotebookPen } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { del, patch, post } from '../../api/client'
import { memoryKeys, useMemories, type Memory } from '../../api/memories'
import { ErrorText, inputClass } from '../../components/ui'
import { kindLabel, memoryDate } from '../../lib/memory'
import { REQUIREMENT_SCOPES, type RequirementScope } from '../../lib/chat'
import { useBookContext } from '../book/context'
import { smallButton } from './styles'

const link = 'text-xs text-ink-3 underline underline-offset-4 hover:text-chief disabled:opacity-40'
const primary = 'h-8 rounded-lg bg-ink px-4 text-[13px] text-paper-2 transition-colors hover:bg-ink-2 disabled:opacity-40'
const descriptions = { writing: '编辑部写设定、排大纲、写正文时，每次都守着。', chat: '只在和你聊天时用，比如你的口味、你说话的意思。' }
const scopeOf = (row?: Memory): RequirementScope => row?.scope === 'chapter' ? 'next_chapter' : row?.scope === 'volume' ? 'this_volume' : 'always'

export function MemoryButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return <button type="button" onClick={onClick} aria-pressed={open} aria-label="记忆" title={open ? '回到聊天' : '记忆：编辑部记着的规矩和你的喜好'}
    className={clsx('flex h-8 shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-1.5 text-[13px] transition-colors hover:bg-line/60 hover:text-ink', open ? 'bg-line/60 text-ink' : 'text-ink-3')}>
    <NotebookPen className="size-4 shrink-0" /><span className="hidden @min-[500px]/editorial-header:inline">记忆</span>
  </button>
}

interface EditorValue { book_id: string | null; kind: Memory['kind']; summary: string; detail: string; scope?: RequirementScope }

export function MemoryEditor({ row, library, bookId, onSave, onCancel }: { row?: Memory; library: string | null; bookId: string; onSave: (value: EditorValue) => Promise<void>; onCancel: () => void }) {
  const [summary, setSummary] = useState(row?.summary ?? '')
  const [detail, setDetail] = useState(row?.detail ?? '')
  const [kind, setKind] = useState<Memory['kind']>(row?.kind ?? 'writing')
  const [where, setWhere] = useState(row ? row.book_id : library)
  const [scope, setScope] = useState<RequirementScope | undefined>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const save = async () => {
    if (busy || !summary.trim()) return
    setBusy(true); setError(null)
    try { await onSave({ book_id: where, kind, summary: summary.trim(), detail: detail.trim(), ...(where === null || kind === 'chat' ? { scope: 'always' } : scope ? { scope } : row ? {} : { scope: 'always' }) }) }
    catch (cause) { setError(cause); setBusy(false) }
  }
  return <form aria-label="编辑记忆" className="space-y-3 rounded-lg border border-line-2 bg-card p-3" onSubmit={event => { event.preventDefault(); void save() }} onKeyDown={event => { if (event.key === 'Escape' && !busy) { event.preventDefault(); event.stopPropagation(); onCancel() } }}>
    <label className="block space-y-1 text-[13px] text-ink-2"><span>简述</span><input autoFocus aria-label="简述" className={`${inputClass} w-full`} value={summary} onChange={event => setSummary(event.target.value)} /></label>
    <label className="block space-y-1 text-[13px] text-ink-2"><span>详细内容</span><textarea aria-label="详细内容" rows={4} className={`${inputClass} w-full resize-y`} value={detail} onChange={event => setDetail(event.target.value)} /></label>
    <div className="flex flex-wrap gap-3">
      <label className="space-y-1 text-[13px] text-ink-2"><span className="block">种类</span><select aria-label="种类" className={inputClass} value={kind} onChange={event => setKind(event.target.value as Memory['kind'])}><option value="writing">写书时照做</option><option value="chat">聊天时记得</option></select></label>
      <label className="space-y-1 text-[13px] text-ink-2"><span className="block">放在</span><select aria-label="放在" className={inputClass} value={where ?? 'global'} onChange={event => { setWhere(event.target.value === 'global' ? null : bookId); if (event.target.value === 'global') setScope('always') }}><option value={bookId}>这本书</option><option value="global">全局</option></select></label>
      {kind === 'writing' && <label className="space-y-1 text-[13px] text-ink-2"><span className="block">管多久</span><select aria-label="管多久" disabled={where === null} className={`${inputClass} disabled:opacity-40`} value={where === null ? 'always' : scope ?? scopeOf(row)} onChange={event => setScope(event.target.value as RequirementScope)}>{REQUIREMENT_SCOPES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>}
    </div>
    <div className="flex justify-end gap-2"><button type="button" disabled={busy} className={smallButton} onClick={onCancel}>取消</button><button type="submit" disabled={busy || !summary.trim()} className={primary}>保存</button></div><ErrorText error={error} />
  </form>
}

interface TidyItem { id: number; text: string; action: string; reason: string; rewrite: string }
function MemoryTidy({ bookId, onDone }: { bookId: string; onDone: () => void }) {
  const qc = useQueryClient()
  const [picked, setPicked] = useState<number[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [run] = useState(() => Date.now())
  const query = useQuery({ queryKey: ['memory-tidy', bookId, run], queryFn: () => post<{ items: TidyItem[] }>(`/books/${bookId}/memories/tidy`), staleTime: Infinity, retry: false })
  const items = query.data?.items.filter(item => item.action !== '保留')
  const selected = picked ?? items?.map(item => item.id) ?? []
  const apply = async () => {
    setBusy(true); setError(null)
    try {
      await post(`/books/${bookId}/memories/apply`, { delete: items?.filter(item => selected.includes(item.id) && item.action === '删掉').map(item => item.id), rewrite: items?.filter(item => selected.includes(item.id) && item.action === '改写').map(item => ({ id: item.id, text: item.rewrite })) })
      await qc.invalidateQueries({ queryKey: memoryKeys.all }); onDone()
    } catch (cause) { setError(cause) } finally { setBusy(false) }
  }
  return <div className="space-y-2 rounded-xl border border-line bg-card p-3 text-[13px]">
    <p className="text-ink">{items ? '主编的整理建议' : '主编正在看……'}</p>
    {items?.length === 0 && <p className="text-ink-2">看过了，没有要整理的。</p>}
    {items?.map(item => <label key={item.id} className="flex cursor-pointer gap-3 rounded-lg border border-line bg-paper/60 p-3"><input type="checkbox" className="mt-1 size-4 shrink-0 accent-[var(--color-ink)]" checked={selected.includes(item.id)} onChange={event => setPicked(event.target.checked ? [...selected, item.id] : selected.filter(id => id !== item.id))} /><span className="leading-relaxed"><span className="block text-ink">{item.text}</span><span className="block text-seal-dark">{item.action === '删掉' ? '删掉' : `改成「${item.rewrite}」`}</span><span className="text-ink-3">{item.reason}</span></span></label>)}
    <ErrorText error={error ?? query.error} /><div className="flex justify-end gap-2"><button type="button" className={smallButton} disabled={busy} onClick={onDone}>{items?.length ? '算了' : '好'}</button>{!!items?.length && <button type="button" className={primary} disabled={busy || !selected.length} onClick={() => void apply()}>照勾的改</button>}</div>
  </div>
}

export function MemoryPage({ focus, onBack }: { focus: number | null; onBack: () => void }) {
  const { bookId } = useBookContext()
  const query = useMemories(bookId)
  const qc = useQueryClient()
  const [chosenLibrary, setLibrary] = useState<string | null | undefined>()
  const [expanded, setExpanded] = useState<number | null>(focus)
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [removed, setRemoved] = useState<Memory[]>([])
  const [tidy, setTidy] = useState(false)
  const [target, setTarget] = useState(focus)
  const [highlight, setHighlight] = useState<number | null>(focus)
  const [navigation, setNavigation] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const rows = query.data ?? []
  const refs = useRef(new Map<number, HTMLLIElement>())
  const targetRow = rows.find(row => row.id === target)
  const library = chosenLibrary === undefined ? targetRow ? targetRow.book_id : bookId : chosenLibrary
  const missing = target !== null && query.isSuccess && !targetRow
  const targetId = targetRow?.id
  useEffect(() => {
    if (targetId === undefined) return
    const frame = requestAnimationFrame(() => refs.current.get(targetId)?.scrollIntoView({ block: 'center', behavior: 'smooth' }))
    const timer = setTimeout(() => setHighlight(null), 2000)
    return () => { cancelAnimationFrame(frame); clearTimeout(timer) }
  }, [targetId, navigation])
  const refresh = () => qc.invalidateQueries({ queryKey: memoryKeys.all })
  const save = async (value: EditorValue) => {
    const row = editing === 'new' ? await post<Memory>(`/books/${bookId}/memories`, value) : await patch<Memory>(`/books/${bookId}/memories/${editing}`, value)
    setEditing(null); setLibrary(row.book_id); setExpanded(row.id); setHighlight(row.id); await refresh(); setTarget(row.id); setNavigation(value => value + 1)
  }
  const remove = async (row: Memory) => {
    setBusy(true); setError(null)
    try { await del(`/books/${bookId}/memories/${row.id}`); setRemoved(previous => [...previous, row]); await refresh() }
    catch (cause) { setError(cause) } finally { setBusy(false) }
  }
  const restore = async (row: Memory) => {
    setBusy(true); setError(null)
    try { await post(`/books/${bookId}/memories/${row.id}/restore`); setRemoved(previous => previous.filter(item => item.id !== row.id)); await refresh() }
    catch (cause) { setError(cause) } finally { setBusy(false) }
  }
  const visible = rows.filter(row => row.book_id === library)
  const deleted = removed.filter(row => row.book_id === library && !rows.some(item => item.id === row.id))
  return <section aria-label="记忆" className="flex min-h-0 flex-1 flex-col">
    <div className="flex shrink-0 items-center gap-2 border-b border-line bg-subtle/60 px-3 py-1.5"><button type="button" onClick={onBack} className="flex h-7 items-center gap-1 rounded-md px-1.5 text-[13px] text-ink-2 hover:bg-line/60 hover:text-ink"><ArrowLeft className="size-3.5" />回到聊天</button><h2 className="ml-auto text-[13px] text-ink-3">记忆</h2></div>
    <div className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-2"><div className="flex gap-1" role="tablist" aria-label="记忆库">{[bookId, null].map(where => <button key={where ?? 'global'} type="button" role="tab" aria-selected={library === where} onClick={() => { setLibrary(where); setEditing(null); setTidy(false) }} className={clsx('rounded-md px-3 py-1.5 text-[13px]', library === where ? 'bg-line/60 text-ink' : 'text-ink-3 hover:text-ink')}>{where ? '这本书' : '全局'}</button>)}</div><button type="button" className={`${smallButton} ml-auto`} onClick={() => { setEditing('new'); setTidy(false) }}>加一条</button></div>
    <div className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-3">
      {missing && <p className="text-[13px] text-ink-3">这条已经删了。</p>}<ErrorText error={error ?? query.error} />
      {editing === 'new' && <MemoryEditor library={library} bookId={bookId} onCancel={() => setEditing(null)} onSave={save} />}
      {query.isPending ? <p className="text-[13px] text-ink-3">正在读…</p> : visible.length + deleted.length === 0 ? <p className="text-[13px] leading-relaxed text-ink-3">还没有记忆。在聊天里说「记住……」，编辑部就会记下来。</p> : (['writing', 'chat'] as const).map(kind => {
        const items = visible.filter(row => row.kind === kind).sort((a, b) => Number(!a.active) - Number(!b.active) || a.id - b.id)
        const gone = deleted.filter(row => row.kind === kind)
        return <section key={kind} aria-label={kindLabel(kind)}>
          <div className="flex items-center gap-2"><h3 className="font-serif text-[15px] font-bold text-ink">{kindLabel(kind)}</h3>{library === bookId && kind === 'writing' && items.filter(row => row.active).length >= 5 && <button type="button" className={`${link} ml-auto`} onClick={() => { setTidy(true); setEditing(null) }}>整理一下</button>}</div>
          <p className="mt-1 text-xs leading-relaxed text-ink-3">{descriptions[kind]}</p>
          {tidy && kind === 'writing' && library === bookId && <div className="mt-3"><MemoryTidy bookId={bookId} onDone={() => setTidy(false)} /></div>}
          {!items.length && !gone.length ? <p className="mt-3 text-[13px] text-ink-3">还没有。</p> : <ul className="mt-2 divide-y divide-line/70">
            {items.map(row => <li key={row.id} ref={element => { if (element) refs.current.set(row.id, element); else refs.current.delete(row.id) }} data-testid={`memory-${row.id}`} className={clsx('rounded-md py-2.5 transition-colors duration-500', !row.active && 'opacity-50', highlight === row.id && 'bg-chief-soft')}>
              {editing === row.id ? <MemoryEditor row={row} library={library} bookId={bookId} onCancel={() => setEditing(null)} onSave={save} /> : <>
                <button type="button" className="w-full rounded-md px-1 text-left hover:bg-line/30" aria-expanded={expanded === row.id} onClick={() => setExpanded(expanded === row.id ? null : row.id)}><p className="text-[14px] leading-relaxed break-words text-ink">{row.summary}<span className="ml-2 text-[11px] text-ink-3">记{row.id}</span></p><p className="mt-1 text-xs leading-relaxed text-ink-3">{!row.active && '已过期 · '}{row.kind === 'writing' && `${row.label} · `}{memoryDate(row.created_at)} · {row.source}</p></button>
                {expanded === row.id && <div className="mt-2 space-y-2 px-1"><p className="text-[13px] leading-relaxed break-words whitespace-pre-wrap text-ink-2">{row.detail}</p><div className="flex gap-3"><button type="button" className={link} onClick={() => setEditing(row.id)}>改</button><button type="button" disabled={busy} className={link} onClick={() => void remove(row)}>删</button></div></div>}
              </>}
            </li>)}
            {gone.map(row => <li key={row.id} className="py-3 text-[13px] text-ink-3">删掉了：{row.summary}<button type="button" disabled={busy} className={`${link} ml-2`} onClick={() => void restore(row)}>撤销</button></li>)}
          </ul>}
        </section>
      })}
    </div>
  </section>
}
