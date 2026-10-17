import clsx from 'clsx'
import { ArrowLeft, BookMarked, Check, ChevronDown, ChevronRight, EyeOff, Flag, Gem, Globe2, Layers, Link2, LockKeyhole, MoreHorizontal, Plus, ScrollText, Search, Sparkles, Tags, Trash2, UnlockKeyhole, Users, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { post } from '../../../api/client'
import { useBible, useBibleMutations, useSecretMutations, useSecrets } from '../../../api/hooks'
import type { Secret } from '../../../api/types'
import { useLibrary, useLibraryConfig, useLibraryItemActions, useLibrarySuggestionActions, useLibrarySuggestions, useRewrite } from '../../../api/library'
import type { LibraryCategory, LibraryConfig, LibraryItem, LibraryItemPatch, LibrarySnapshot, LibrarySuggestion } from '../../../api/library'
import { InlineText } from '../../../components/InlineText'
import { TargetHistory } from '../../../components/RewriteField'
import { Button, ErrorText, Skeleton, Spinner } from '../../../components/ui'
import { filterLibraryRows, libraryRows, parentChoices, suggestionAction, suggestionTargetId } from '../../../lib/libraryView'
import type { LibraryRow } from '../../../lib/libraryView'
import { useBookContext } from '../context'
import { SetupGate } from '../SetupGate'
import { PageHeader } from './common'
import { CategoryModal } from './LibraryCategoryModal'

const CATEGORY_ICON: Record<string, typeof Users> = { 角色卡片: Users, 等级体系: Layers, 世界与地图: Globe2, 势力划分: Flag, 物品与功法: Gem, 往事与秘密: EyeOff, 特殊规则: ScrollText }
const ROLE_TONE: Record<string, string> = { 主角: 'bg-seal-soft text-seal-dark', 女主: 'bg-lore-soft text-lore', 男主: 'bg-lore-soft text-lore', 对手: 'bg-reviewer-soft text-reviewer' }
/** 角色卡上方一行的小项，其余长的一项一行。 */
const CHARACTER_SHORT = ['name', 'aliases', 'role_type', 'gender', 'age']
const FILL_INSTRUCTION = (label: string) => `按定调、设定库和这一类该写清的事，写「${label}」这一项：具体、能直接用在正文里`

type Target = { path: string; label: string }
const isCreate = (suggestion: LibrarySuggestion) => suggestion.payload.op === 'create_entry' || suggestion.payload.op === 'create_character'
const createData = (suggestion: LibrarySuggestion) => ((suggestion.payload.op === 'create_character' ? suggestion.payload.character : suggestion.payload.entry) ?? {}) as Record<string, string>
const createCategory = (suggestion: LibrarySuggestion) => suggestion.payload.op === 'create_character' ? '角色卡片' : createData(suggestion).category ?? ''
const reasonOf = (suggestion: LibrarySuggestion) => suggestion.title.includes('——') ? suggestion.title.split('——').slice(1).join('——') : String(suggestion.payload.why ?? '')

// ---------------------------------------------------------------- 小部件

function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-4 border-t border-line/70 py-3.5 first:border-t-0 @2xl/manuscript:grid-cols-[7.5rem_minmax(0,1fr)]">
    <dt className="pt-1 text-[13px] text-ink-3">{label}</dt>
    <dd className="min-w-0 text-[15px] leading-[1.8]">{children}</dd>
  </div>
}

/** 空着的字段不列一排「（空）」，而是收成一行，点一下就在原处写。 */
function MoreFields({ items, onPick }: { items: Target[]; onPick: (path: string) => void }) {
  if (!items.length) return null
  return <div className="mt-4 flex flex-wrap items-center gap-2 text-[13px]">
    <span className="text-ink-3">还可以写：</span>
    {items.map(item => <button key={item.path} type="button" onClick={() => onPick(item.path)} className="rounded-full border border-dashed border-line-2 px-3 py-1 text-ink-2 transition-colors hover:border-ink-3 hover:text-ink">＋ {item.label}</button>)}
  </div>
}

function useFillEmpty(bookId: string) {
  const rewrite = useRewrite(bookId)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const stop = useRef(false)
  const run = async (row: LibraryRow, targets: Target[]) => {
    setError(null); stop.current = false; setProgress({ done: 0, total: targets.length })
    for (const [index, target] of targets.entries()) {
      if (stop.current) break
      try { await rewrite.mutateAsync({ target_type: row.targetType, target_id: row.id, path: target.path, mode: 'instruction', instruction: FILL_INSTRUCTION(target.label) }) } catch (cause) { setError(cause); break }
      setProgress({ done: index + 1, total: targets.length })
    }
    setProgress(null)
  }
  return { run, progress, error, stop: () => { stop.current = true } }
}

function Menu({ children, label = '更多' }: { children: ReactNode; label?: string }) {
  const ref = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const close = (event: PointerEvent) => { if (ref.current?.open && !ref.current.contains(event.target as Node)) ref.current.open = false }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [])
  return <details ref={ref} className="relative shrink-0">
    <summary aria-label={label} title={label} className="flex size-9 cursor-pointer list-none items-center justify-center rounded-lg text-ink-2 hover:bg-line/60 hover:text-ink [&::-webkit-details-marker]:hidden"><MoreHorizontal className="size-5" /></summary>
    <div className="absolute top-10 right-0 z-30 w-60 space-y-0.5 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)] [&_button]:w-full [&_button]:justify-start">{children}</div>
  </details>
}
const menuItem = 'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-ink hover:bg-subtle disabled:opacity-50'

// ---------------------------------------------------------------- 卡片头

function EntryHeader({ bookId, row, library, config, fillTargets, onDeleted }: { bookId: string; row: LibraryRow; library: LibrarySnapshot; config: LibraryConfig; fillTargets: Target[]; onDeleted: () => void }) {
  const { update, remove } = useLibraryItemActions(bookId)
  const { inspect } = useLibrarySuggestionActions(bookId)
  const fill = useFillEmpty(bookId)
  const save = (body: LibraryItemPatch) => update.mutateAsync({ type: row.targetType, id: row.id, body })
  const category = library.categories.find(item => item.key === row.categoryKey)
  const Icon = CATEGORY_ICON[row.categoryKey] ?? Tags
  const style = row.targetType === 'character' ? 'card' : row.style ?? category?.style
  const moveTo = library.categories.filter(item => item.key !== config.character_category.key && item.key !== row.categoryKey && item.style === style)
  const toggleTag = (tag: string) => void save({ tags: row.tags.includes(tag) ? row.tags.filter(value => value !== tag) : [...row.tags, tag] }).catch(() => undefined)
  const deleteItem = async () => {
    if (!window.confirm(`删除「${row.name}」？这条设定会从设定里拿掉。`)) return
    try { await remove.mutateAsync({ type: row.targetType, id: row.id }); onDeleted() } catch { /* 显示错误 */ }
  }
  return <header className="mb-5">
    <p className="mb-2 flex items-center gap-1.5 text-[13px] text-ink-3"><Icon className="size-3.5" />{category?.name ?? row.categoryKey}{row.status === 'later' && <span className="rounded bg-subtle px-1.5 text-xs leading-5 ring-1 ring-line">写到再说</span>}</p>
    <div className="flex items-start gap-2">
      <InlineText multiline={false} value={row.name} placeholder="名字" onSave={name => { if (!name) throw new Error('名字不能空着'); return save({ name }) }} className="min-w-0 flex-1 font-serif text-[28px] leading-tight font-bold" />
      {fillTargets.length > 0 && !row.locked && (fill.progress
        ? <Button variant="outline" size="sm" onClick={fill.stop}><Spinner className="size-3.5" />正在写 {fill.progress.done}/{fill.progress.total} · 停</Button>
        : <Button variant="outline" size="sm" title="让 AI 把这张卡上空着的几项都写上" onClick={() => void fill.run(row, fillTargets)}><Sparkles className="size-3.5" />把空着的都写上</Button>)}
      <Button variant="ghost" size="sm" title={row.locked ? '已锁住：AI 不会改它，你自己照样能改' : '锁住以后 AI 不会改它'} disabled={update.isPending} onClick={() => void save({ locked: !row.locked }).catch(() => undefined)}>
        {row.locked ? <LockKeyhole className="size-4 text-seal" /> : <UnlockKeyhole className="size-4" />}{row.locked ? '已锁住' : '锁住'}
      </Button>
      <Menu>
        <TargetHistory bookId={bookId} targetType={row.targetType} targetId={row.id} />
        <button type="button" className={menuItem} onClick={() => void save({ status: row.status === 'later' ? 'must' : 'later' }).catch(() => undefined)}>{row.status === 'later' ? '现在就要写' : '先不急，写到再说'}</button>
        {config.focus_tags.map(tag => <button key={tag} type="button" className={menuItem} onClick={() => toggleTag(tag)}>{row.tags.includes(tag) ? <Check className="size-4 text-lore" /> : <span className="size-4" />}标成「{tag}」</button>)}
        {row.targetType === 'entry' && moveTo.length > 0 && <label className="flex items-center gap-2 px-3 py-2 text-sm">移到<select aria-label="移到别的类别" value="" onChange={event => event.target.value && void save({ category: event.target.value }).catch(() => undefined)} className="min-w-0 flex-1 rounded-md border border-line-2 bg-card px-1.5 py-1"><option value="">别的类别…</option>{moveTo.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>}
        <button type="button" className={menuItem} disabled={inspect.isPending} onClick={() => inspect.mutate({ mode: 'check', target_type: row.targetType, target_id: row.id })}>让审稿看看这一条</button>
        <button type="button" className={clsx(menuItem, 'text-seal hover:bg-seal-soft')} onClick={() => void deleteItem()}><Trash2 className="size-4" />删除这一条</button>
      </Menu>
    </div>
    {row.tags.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{row.tags.map(tag => <span key={tag} className="rounded-md bg-writer-soft px-2 text-xs leading-6 text-writer">{tag}</span>)}</div>}
    {inspect.isPending && <p role="status" className="mt-2 text-[13px] text-chief">审稿正在看这一条，有意见会挂在卡上，也会在群聊里说。</p>}
    <ErrorText error={update.error ?? remove.error ?? inspect.error ?? fill.error} />
  </header>
}

// ---------------------------------------------------------------- 卡片上的意见

function EntryNotes({ bookId, row, suggestions }: { bookId: string; row: LibraryRow; suggestions: LibrarySuggestion[] }) {
  const { resolve } = useLibrarySuggestionActions(bookId)
  const [open, setOpen] = useState<string | null>(null)
  if (!suggestions.length) return null
  return <section aria-label="这一条的意见" className="mb-5 space-y-2">
    {suggestions.map(suggestion => {
      const written = suggestion.kind === 'written'
      const why = String(suggestion.payload.why ?? '')
      return <div key={suggestion.id} className="rounded-xl border border-[#efdcc0] bg-[#fbf1e3] px-4 py-3 text-sm">
        <p className="leading-relaxed text-ink">{suggestion.title.replaceAll('（已锁）', '')}</p>
        {why && why !== suggestion.title && <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{why}</p>}
        {written && open === suggestion.id && Array.isArray(suggestion.payload.matches) && <div className="mt-2 space-y-2 text-[13px] text-ink-2">{(suggestion.payload.matches as { chapter: number; count: number; contexts: string[] }[]).map(match => <div key={match.chapter}><p className="font-medium">第 {match.chapter} 章 · {match.count} 处</p>{match.contexts.map((context, index) => <p key={index} className="mt-1 rounded bg-card p-2 leading-relaxed">…{context}…</p>)}</div>)}</div>}
        <div className="mt-2 flex flex-wrap gap-2">
          {written && open !== suggestion.id
            ? <Button size="sm" variant="outline" onClick={() => setOpen(suggestion.id)}>看看前文哪里要换</Button>
            : <Button size="sm" variant="primary" disabled={row.locked || resolve.isPending} title={row.locked ? '锁住了，先解锁' : undefined} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' })}>{written ? '确认，前文也一起换' : suggestionAction(suggestion) === '改' ? '照这个改' : suggestionAction(suggestion)}</Button>}
          <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' })}>{written ? '只管以后' : '不用'}</Button>
        </div>
      </div>
    })}
    <ErrorText error={resolve.error} />
  </section>
}

/** 没挂在哪一条上的意见：审稿的提醒、写作中群聊里说的改动。 */
function GeneralNotes({ bookId, suggestions }: { bookId: string; suggestions: LibrarySuggestion[] }) {
  const { working, waiting, asking } = useBookContext()
  const { resolve } = useLibrarySuggestionActions(bookId)
  const qc = useQueryClient()
  const runChat = useMutation({ mutationFn: (id: string) => post(`/suggestions/${id}/run-chat`), onSuccess: () => qc.invalidateQueries() })
  const [open, setOpen] = useState(false)
  if (!suggestions.length) return null
  return <section aria-label="编辑部的意见" className="mx-auto mb-5 max-w-[860px] rounded-xl border border-line bg-paper-2">
    <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm">
      <span className="size-1.5 rounded-full bg-writer" /><span className="font-medium">编辑部还有 {suggestions.length} 条意见</span><span className="text-[13px] text-ink-3">没挂在哪一条上的</span>
      <ChevronDown className={clsx('ml-auto size-4 text-ink-3 transition-transform', open && 'rotate-180')} />
    </button>
    {open && <div className="space-y-2 border-t border-line px-4 py-3">{suggestions.map(suggestion => <div key={suggestion.id} className="rounded-lg bg-card px-3.5 py-2.5 text-sm">
      <p className="leading-relaxed">{suggestion.title}</p>
      {!!suggestion.payload.why && <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{String(suggestion.payload.why)}</p>}
      <div className="mt-2 flex gap-2">
        {suggestion.kind === 'chat'
          ? <Button size="sm" variant="primary" disabled={runChat.isPending || working || waiting || asking} loading={runChat.isPending && runChat.variables === suggestion.id} onClick={() => runChat.mutate(suggestion.id)}>现在改</Button>
          : <Button size="sm" variant="outline" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' })}>{suggestionAction(suggestion) === '改' ? '知道了' : suggestionAction(suggestion)}</Button>}
        <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' })}>不用</Button>
      </div>
    </div>)}<ErrorText error={resolve.error ?? runChat.error} /></div>}
  </section>
}

// ---------------------------------------------------------------- 各种卡片的正文

function useRowSave(bookId: string, row: LibraryRow) {
  const { update } = useLibraryItemActions(bookId)
  return (body: LibraryItemPatch) => update.mutateAsync({ type: row.targetType, id: row.id, body })
}
function aiFor(bookId: string, row: LibraryRow, path: string, label: string) {
  return { bookId, targetType: row.targetType, targetId: row.id, path, label, locked: row.locked }
}

function CharacterBody({ bookId, row, config, adding, setAdding }: { bookId: string; row: LibraryRow; config: LibraryConfig; adding: string | null; setAdding: (path: string | null) => void }) {
  const save = useRowSave(bookId, row)
  const long = config.character_category.fields.filter(field => !CHARACTER_SHORT.includes(field.column))
  const value = (column: keyof LibraryItem) => String(row[column] ?? '')
  const all = [{ column: 'one_line' as keyof LibraryItem, name: '一句话' }, ...long]
  const shown = all.filter(field => value(field.column).trim() || adding === field.column)
  const missing = all.filter(field => !value(field.column).trim() && adding !== field.column)
  const roles = [...new Set([row.role_type ?? '', ...config.role_types])].filter(Boolean)
  return <>
    <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
      <label className="flex items-center gap-2 text-ink-3">定位<select aria-label="定位" value={row.role_type ?? ''} onChange={event => void save({ role_type: event.target.value }).catch(() => undefined)} className={clsx('rounded-md border-0 px-2 py-1 text-[13px] font-medium', ROLE_TONE[row.role_type ?? ''] ?? 'bg-subtle text-ink-2 ring-1 ring-line')}>{roles.map(role => <option key={role}>{role}</option>)}</select></label>
      <span className="flex items-center gap-2 text-ink-3">性别<InlineText multiline={false} value={row.gender ?? ''} placeholder="—" onSave={gender => save({ gender })} className="w-20 text-ink" /></span>
      <span className="flex items-center gap-2 text-ink-3">年龄<InlineText multiline={false} value={row.age ?? ''} placeholder="—" onSave={age => save({ age })} className="w-24 text-ink" /></span>
      <span className="flex min-w-48 flex-1 items-center gap-2 text-ink-3">也叫<InlineText multiline={false} value={(row.aliases ?? []).join('、')} placeholder="别名，用顿号隔开" onSave={text => save({ aliases: text.split(/[、,，]/).map(item => item.trim()).filter(Boolean) })} className="min-w-0 flex-1 text-ink" /></span>
    </div>
    <dl className="rounded-2xl border border-line bg-card px-5 py-1.5 shadow-[var(--shadow-paper)] @2xl/manuscript:px-7">
      {shown.map(field => <FieldRow key={field.column} label={field.name}>
        <InlineText value={value(field.column)} autoEdit={adding === field.column} onDone={() => setAdding(null)} onSave={text => save({ [field.column]: text } as LibraryItemPatch)} ai={aiFor(bookId, row, field.column, field.name)} />
      </FieldRow>)}
      {!shown.length && <p className="py-5 text-sm text-ink-3">这张卡还是空的。点下面任意一项开始写，或者点上面「把空着的都写上」。</p>}
    </dl>
    <MoreFields items={missing.map(field => ({ path: field.column, label: field.name }))} onPick={setAdding} />
  </>
}

function ParagraphBody({ bookId, row, library, adding, setAdding }: { bookId: string; row: LibraryRow; library: LibrarySnapshot; adding: string | null; setAdding: (path: string | null) => void }) {
  const save = useRowSave(bookId, row)
  const items: { path: 'one_line' | 'content'; label: string }[] = [{ path: 'one_line', label: '一句话' }, { path: 'content', label: '详细' }]
  const shown = items.filter(item => String(row[item.path] ?? '').trim() || adding === item.path)
  const missing = items.filter(item => !String(row[item.path] ?? '').trim() && adding !== item.path)
  return <>
    <div className="rounded-2xl border border-line bg-card px-5 py-5 shadow-[var(--shadow-paper)] @2xl/manuscript:px-7">
      {shown.map(item => <div key={item.path} className={clsx(item.path === 'one_line' && shown.length > 1 && 'mb-4 border-b border-line/70 pb-4')}>
        <p className="mb-1.5 text-[13px] text-ink-3">{item.label}</p>
        <InlineText value={String(row[item.path] ?? '')} autoEdit={adding === item.path} onDone={() => setAdding(null)} onSave={text => save({ [item.path]: text })} ai={aiFor(bookId, row, item.path, item.label)} className={item.path === 'content' ? 'text-[15px] leading-[1.9]' : 'text-[16px] font-medium'} />
      </div>)}
      {!shown.length && <p className="text-sm text-ink-3">还是空的。点下面开始写，或者点上面「把空着的都写上」。</p>}
    </div>
    <MoreFields items={missing} onPick={setAdding} />
    {row.categoryKey === '世界与地图' && <label className="mt-4 flex items-center gap-2.5 text-sm text-ink-3">属于哪里<select aria-label="属于哪里" value={row.parent_id ?? ''} onChange={event => void save({ parent_id: event.target.value || null }).catch(() => undefined)} className="rounded-lg border border-line-2 bg-card px-2.5 py-1.5 text-ink"><option value="">不属于别的地方</option>{parentChoices(library.entries, row).map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}
  </>
}

function CardBody({ bookId, row, library, adding, setAdding }: { bookId: string; row: LibraryRow; library: LibrarySnapshot; adding: string | null; setAdding: (path: string | null) => void }) {
  const save = useRowSave(bookId, row)
  const category = library.categories.find(item => item.key === row.categoryKey)
  const names = [...new Set([...(category?.fields ?? []), ...(row.fields ?? []).map(field => field.name)])]
  const valueOf = (name: string) => row.fields?.find(field => field.name === name)?.value ?? ''
  const saveField = (name: string, value: string) => save({ fields: names.map(item => ({ name: item, value: item === name ? value : valueOf(item) })) })
  const shown = names.filter(name => valueOf(name).trim() || adding === `fields.${name}`)
  const missing = names.filter(name => !valueOf(name).trim() && adding !== `fields.${name}`)
  return <>
    <div className="mb-4"><InlineText value={row.one_line} placeholder="一句话说清这是什么" onSave={one_line => save({ one_line })} ai={aiFor(bookId, row, 'one_line', '一句话')} className="text-[16px] font-medium" /></div>
    <dl className="rounded-2xl border border-line bg-card px-5 py-1.5 shadow-[var(--shadow-paper)] @2xl/manuscript:px-7">
      {shown.map(name => <FieldRow key={name} label={name}><InlineText value={valueOf(name)} autoEdit={adding === `fields.${name}`} onDone={() => setAdding(null)} onSave={text => saveField(name, text)} ai={aiFor(bookId, row, `fields.${name}`, name)} /></FieldRow>)}
      {!shown.length && <p className="py-5 text-sm text-ink-3">还是空的。点下面任意一项开始写。</p>}
    </dl>
    <MoreFields items={missing.map(name => ({ path: `fields.${name}`, label: name }))} onPick={setAdding} />
  </>
}

function LadderBody({ bookId, row }: { bookId: string; row: LibraryRow }) {
  const save = useRowSave(bookId, row)
  const levels = row.levels ?? []
  const saveLevels = (next: typeof levels) => save({ levels: next })
  const move = (index: number, offset: number) => { const next = [...levels]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; void saveLevels(next).catch(() => undefined) }
  return <>
    <div className="mb-5 rounded-2xl border border-line bg-card px-5 py-4 shadow-[var(--shadow-paper)] @2xl/manuscript:px-7"><p className="mb-1.5 text-[13px] text-ink-3">总说明：怎么往上升、越级多难、有什么代价</p><InlineText value={row.content ?? ''} placeholder="点这里写总说明" onSave={content => save({ content })} ai={aiFor(bookId, row, 'content', '总说明')} className="text-[15px] leading-[1.9]" /></div>
    <ol className="space-y-3">{levels.map((level, index) => <li key={index} className="group/level flex gap-4 rounded-2xl border border-line bg-card px-5 py-4 shadow-[var(--shadow-paper)]">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink font-serif text-sm text-paper-2" style={{ opacity: 0.45 + Math.min(index, 8) * 0.07 }}>{index + 1}</span>
      <div className="min-w-0 flex-1">
        <InlineText multiline={false} value={level.name} placeholder="这一级叫什么" onSave={name => saveLevels(levels.map((item, at) => at === index ? { ...item, name } : item))} className="font-serif text-lg font-bold" />
        <InlineText value={level.text} placeholder="这一级是什么样：能做到什么、凭什么升上来" onSave={text => saveLevels(levels.map((item, at) => at === index ? { ...item, text } : item))} ai={aiFor(bookId, row, `levels.${index}.text`, level.name || `第 ${index + 1} 级`)} className="mt-1 text-[15px] leading-[1.8]" />
      </div>
      <div className="flex shrink-0 flex-col gap-0.5 opacity-0 transition-opacity group-hover/level:opacity-100 focus-within:opacity-100">
        <button type="button" aria-label="上移" disabled={index === 0} onClick={() => move(index, -1)} className="rounded p-1 text-ink-3 hover:text-ink disabled:opacity-30"><ChevronDown className="size-4 rotate-180" /></button>
        <button type="button" aria-label="下移" disabled={index === levels.length - 1} onClick={() => move(index, 1)} className="rounded p-1 text-ink-3 hover:text-ink disabled:opacity-30"><ChevronDown className="size-4" /></button>
        <button type="button" aria-label="删掉这一级" onClick={() => { if (window.confirm(`删掉「${level.name || `第 ${index + 1} 级`}」？`)) void saveLevels(levels.filter((_, at) => at !== index)).catch(() => undefined) }} className="rounded p-1 text-ink-3 hover:text-seal"><X className="size-4" /></button>
      </div>
    </li>)}</ol>
    <button type="button" onClick={() => void saveLevels([...levels, { name: '', text: '' }]).catch(() => undefined)} className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-2xl border-[1.5px] border-dashed border-line-2 py-3 text-sm text-ink-3 hover:border-ink-3 hover:text-ink-2"><Plus className="size-4" />加一级</button>
  </>
}

function Relations({ bookId, characterId }: { bookId: string; characterId: string }) {
  const { working } = useBookContext()
  const { data: bible } = useBible(bookId)
  const { create, update, remove } = useBibleMutations(bookId, 'relationships')
  const [target, setTarget] = useState('')
  const [kind, setKind] = useState('')
  const characters = bible?.characters ?? []
  const names = Object.fromEntries(characters.map(row => [row.id, row.name]))
  const rows = (bible?.relationships ?? []).filter(row => row.source_id === characterId || row.target_id === characterId)
  const others = characters.filter(row => row.id !== characterId)
  return <section aria-label="人物关系" className="mt-8">
    <h3 className="mb-3 flex items-center gap-2 text-[15px] font-semibold"><Link2 className="size-4" />人物关系</h3>
    <div className="space-y-2">{rows.map(row => {
      const other = row.source_id === characterId ? row.target_id : row.source_id
      return <div key={row.id} className="group flex items-start gap-3 rounded-xl border border-line bg-card px-4 py-3 text-sm">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-ink-2 font-serif text-sm text-on-role">{(names[other] ?? '？').slice(0, 1)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><b className="font-semibold">{names[other] ?? '（已删除）'}</b><InlineText multiline={false} value={row.kind} placeholder="什么关系" disabled={working} onSave={value => update.mutateAsync({ id: row.id, kind: value })} className="min-w-24 text-ink-2" /></div>
          <InlineText value={row.description} placeholder="补一句：之间有什么张力、以后会怎样" disabled={working} onSave={value => update.mutateAsync({ id: row.id, description: value })} className="mt-0.5 text-[13px] text-ink-2" />
        </div>
        {!working && <button type="button" aria-label={`删除和${names[other]}的关系`} onClick={() => remove.mutate(row.id)} className="rounded p-1 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:text-seal focus-visible:opacity-100"><Trash2 className="size-4" /></button>}
      </div>
    })}</div>
    {!rows.length && <p className="text-[13px] text-ink-3">还没记下和其他人的关系。</p>}
    {!working && others.length > 0 && <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={async event => { event.preventDefault(); if (!target || !kind.trim()) return; await create.mutateAsync({ source_id: characterId, target_id: target, kind: kind.trim(), description: '' }); setKind(''); setTarget('') }}>
      <select aria-label="和谁" value={target} onChange={event => setTarget(event.target.value)} className="h-9 rounded-lg border border-line-2 bg-card px-2.5 text-sm"><option value="">和谁…</option>{others.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
      <input aria-label="什么关系" value={kind} onChange={event => setKind(event.target.value)} placeholder="什么关系，比如 师徒、死敌、青梅竹马" className="h-9 min-w-0 flex-1 rounded-lg border border-line-2 bg-card px-3 text-sm placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
      <Button type="submit" size="sm" variant="outline" disabled={!target || !kind.trim()} loading={create.isPending}><Plus className="size-3.5" />加一条</Button>
    </form>}
    <ErrorText error={create.error ?? update.error ?? remove.error} />
  </section>
}

function SecretSection({ bookId, row }: { bookId: string; row: LibraryRow }) {
  const secrets = useSecrets(bookId)
  const { data: bible } = useBible(bookId)
  const { create, update } = useSecretMutations(bookId)
  const { update: updateItem } = useLibraryItemActions(bookId)
  const [adding, setAdding] = useState('')
  const secret: Secret | undefined = secrets.data?.find(item => item.id === row.secret_id)
  const link = async () => { try { const created = await create.mutateAsync({ title: row.name, truth: row.content || row.one_line }); await updateItem.mutateAsync({ type: row.targetType, id: row.id, body: { secret_id: created.id } }) } catch { /* 显示错误 */ } }
  const save = (body: Partial<Secret>) => secret ? update.mutateAsync({ id: secret.id, ...body }) : Promise.resolve()
  const others = (bible?.characters ?? []).filter(character => !secret?.knowers.some(knower => knower.name === character.name))
  return <section aria-label="谁知道这件事" className="mt-8">
    <h3 className="mb-3 flex items-center gap-2 text-[15px] font-semibold"><EyeOff className="size-4" />谁知道这件事</h3>
    {!secret ? <p className="rounded-xl border border-dashed border-line-2 px-4 py-3 text-sm text-ink-2">还没记谁知道、读者知不知道、打算怎么揭开。<button type="button" disabled={create.isPending} onClick={() => void link()} className="ml-1 font-medium text-chief hover:underline">记一笔</button></p>
      : <dl className="rounded-2xl border border-line bg-card px-5 py-1.5 shadow-[var(--shadow-paper)] @2xl/manuscript:px-7">
        <FieldRow label="谁知道"><div className="flex flex-wrap items-center gap-1.5">
          {secret.knowers.map((knower, index) => <span key={`${knower.name}-${index}`} className="inline-flex items-center gap-1 rounded-full bg-subtle py-0.5 pr-1 pl-3 text-[13px] ring-1 ring-line" title={knower.how || undefined}>{knower.name}{knower.since_chapter !== null && <span className="text-ink-3">· 第 {knower.since_chapter} 章起</span>}<button type="button" aria-label={`${knower.name}不知道`} onClick={() => void save({ knowers: secret.knowers.filter((_, at) => at !== index) }).catch(() => undefined)} className="rounded-full p-0.5 text-ink-3 hover:text-seal"><X className="size-3" /></button></span>)}
          {!secret.knowers.length && <span className="text-ink-3">还没人知道</span>}
          {others.length > 0 && <select aria-label="加一个知道的人" value={adding} onChange={event => { const name = event.target.value; setAdding(''); if (name) void save({ knowers: [...secret.knowers, { name, since_chapter: null, how: '' }] }).catch(() => undefined) }} className="rounded-full border border-dashed border-line-2 bg-card px-2.5 py-0.5 text-[13px] text-ink-2"><option value="">＋ 谁知道</option>{others.map(character => <option key={character.id}>{character.name}</option>)}</select>}
        </div></FieldRow>
        <FieldRow label="读者知道吗"><div className="flex flex-wrap gap-1.5">{(['不知道', '部分', '知道'] as const).map(choice => <button key={choice} type="button" aria-pressed={secret.reader_knows === choice} onClick={() => void save({ reader_knows: secret.reader_knows === choice ? null : choice }).catch(() => undefined)} className={clsx('rounded-full px-3 py-0.5 text-[13px] ring-1', secret.reader_knows === choice ? 'bg-ink text-paper-2 ring-ink' : 'bg-card text-ink-2 ring-line-2 hover:text-ink')}>{choice === '部分' ? '知道一部分' : choice}</button>)}</div></FieldRow>
        <FieldRow label="打算怎么揭开"><InlineText value={secret.reveal_plan} placeholder="在什么情境下、怎么揭开" onSave={reveal_plan => save({ reveal_plan })} /></FieldRow>
      </dl>}
    <ErrorText error={create.error ?? update.error ?? updateItem.error ?? secrets.error} />
  </section>
}

function EntryView({ bookId, row, library, config, suggestions, onDeleted }: { bookId: string; row: LibraryRow; library: LibrarySnapshot; config: LibraryConfig; suggestions: LibrarySuggestion[]; onDeleted: () => void }) {
  const { book } = useBookContext()
  const [adding, setAdding] = useState<string | null>(null)
  const category = library.categories.find(item => item.key === row.categoryKey)
  const style = row.targetType === 'character' ? 'card' : row.style ?? category?.style ?? 'paragraph'
  const empty = (value: unknown) => !String(value ?? '').trim()
  const fillTargets: Target[] = row.targetType === 'character'
    ? [{ column: 'one_line', name: '一句话' }, ...config.character_category.fields.filter(field => !CHARACTER_SHORT.includes(field.column))].filter(field => empty(row[field.column as keyof LibraryItem])).map(field => ({ path: field.column, label: field.name }))
    : style === 'ladder' ? (empty(row.content) ? [{ path: 'content', label: '总说明' }] : [])
      : style === 'card' ? [...(empty(row.one_line) ? [{ path: 'one_line', label: '一句话' }] : []), ...(category?.fields ?? []).filter(name => empty(row.fields?.find(field => field.name === name)?.value)).map(name => ({ path: `fields.${name}`, label: name }))]
        : [{ path: 'one_line', label: '一句话' }, { path: 'content', label: '详细' }].filter(item => empty(row[item.path as 'one_line' | 'content']))
  const writing = book.chapters_final > 0 || config.character_category.state_fields.some(field => field.column !== 'is_alive' && !empty(row[field.column]))
  return <article aria-label={row.name} className="mx-auto max-w-[860px]">
    <EntryHeader bookId={bookId} row={row} library={library} config={config} fillTargets={fillTargets} onDeleted={onDeleted} />
    <EntryNotes bookId={bookId} row={row} suggestions={suggestions} />
    {row.targetType === 'character' ? <CharacterBody bookId={bookId} row={row} config={config} adding={adding} setAdding={setAdding} />
      : style === 'ladder' ? <LadderBody bookId={bookId} row={row} />
        : style === 'card' ? <CardBody bookId={bookId} row={row} library={library} adding={adding} setAdding={setAdding} />
          : <ParagraphBody bookId={bookId} row={row} library={library} adding={adding} setAdding={setAdding} />}
    {row.targetType === 'character' && <Relations bookId={bookId} characterId={row.id} />}
    {row.categoryKey === '往事与秘密' && <SecretSection bookId={bookId} row={row} />}
    {row.targetType === 'character' && writing && <section className="mt-8 rounded-2xl bg-subtle px-5 py-4 ring-1 ring-line"><h3 className="mb-2.5 text-[15px] font-semibold">写到现在<span className="ml-2 text-[13px] font-normal text-ink-3">设定师每章更新</span></h3><dl className="grid gap-x-6 gap-y-2 text-sm @2xl/manuscript:grid-cols-2">{config.character_category.state_fields.map(field => <div key={field.column} className="flex gap-3"><dt className="w-16 shrink-0 text-ink-3">{field.name}</dt><dd>{typeof row[field.column] === 'boolean' ? (row[field.column] ? '活着' : '已故') : String(row[field.column] || '—')}</dd></div>)}</dl></section>}
  </article>
}

/** AI 补漏想新建的一条：先看全文，留下才进设定。 */
function GhostView({ bookId, suggestion, onKept, onDropped }: { bookId: string; suggestion: LibrarySuggestion; onKept: (name: string, category: string) => void; onDropped: () => void }) {
  const { resolve } = useLibrarySuggestionActions(bookId)
  const config = useLibraryConfig()
  const data = createData(suggestion)
  const character = suggestion.payload.op === 'create_character'
  const rows: [string, string][] = character
    ? [['一句话', data.one_line], ...(config.data?.character_category.fields ?? []).filter(field => !['name', 'aliases'].includes(field.column)).map(field => [field.name, data[field.column as string]] as [string, string])]
    : [['一句话', data.one_line], ['详细', data.content]]
  return <article aria-label={`AI 建议新建：${data.name}`} className="mx-auto max-w-[860px]">
    <p className="mb-2 flex items-center gap-1.5 text-[13px] text-writer"><Sparkles className="size-3.5" />AI 建议新建 · {createCategory(suggestion)}</p>
    <h2 className="font-serif text-[28px] leading-tight font-bold text-ink">{data.name}</h2>
    {reasonOf(suggestion) && <p className="mt-2 text-sm leading-relaxed text-ink-2">为什么：{reasonOf(suggestion)}</p>}
    <dl className="mt-5 rounded-2xl border-[1.5px] border-dashed border-line-2 bg-card/60 px-5 py-1.5 @2xl/manuscript:px-7">{rows.filter(([, value]) => String(value ?? '').trim()).map(([label, value]) => <FieldRow key={label} label={label}><p className="whitespace-pre-wrap text-ink-2">{value}</p></FieldRow>)}</dl>
    <div className="mt-5 flex flex-wrap gap-2.5">
      <Button variant="primary" loading={resolve.isPending && resolve.variables?.action === 'accept'} disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' }, { onSuccess: () => onKept(data.name, createCategory(suggestion)) })}><Check className="size-4" />留下这一条</Button>
      <Button variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' }, { onSuccess: onDropped })}>不要</Button>
      <span className="self-center text-[13px] text-ink-3">留下以后跟别的设定一样，随时能改。</span>
    </div>
    <ErrorText error={resolve.error} />
  </article>
}

// ---------------------------------------------------------------- 左边的目录

function NewEntryRow({ bookId, category, config, onCreated, onCancel }: { bookId: string; category: LibraryCategory; config: LibraryConfig; onCreated: (id: string) => void; onCancel: () => void }) {
  const { create } = useLibraryItemActions(bookId)
  const [name, setName] = useState('')
  const submit = async () => {
    if (!name.trim()) { onCancel(); return }
    const type = category.key === config.character_category.key ? 'character' : 'entry'
    try {
      const item = await create.mutateAsync({ type, body: { name: name.trim(), status: 'must', ...(type === 'entry' ? { category: category.key, style: category.style, fields: (category.fields ?? []).map(field => ({ name: field, value: '' })) } : { role_type: '配角' }) } })
      onCreated(item.id)
    } catch { /* 显示错误 */ }
  }
  return <li className="px-1 py-1">
    <input autoFocus aria-label={`新的${category.name}叫什么`} value={name} onChange={event => setName(event.target.value)} disabled={create.isPending}
      onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); void submit() } else if (event.key === 'Escape') onCancel() }} onBlur={() => { if (!name.trim()) onCancel() }}
      placeholder="叫什么？回车建好" className="h-9 w-full rounded-lg border border-ink-3/50 bg-card px-3 text-sm outline-none placeholder:text-ink-3" />
    <ErrorText error={create.error} />
  </li>
}

function LibraryList({ bookId, data, config, rows, ghosts, suggested, selectedId, ghostId, search, setSearch, onSelect, onGhost, onCreated, onEditCategory }: {
  bookId: string; data: LibrarySnapshot; config: LibraryConfig; rows: Map<string, LibraryRow[]>; ghosts: LibrarySuggestion[]; suggested: Set<string | null>; selectedId?: string; ghostId?: string
  search: string; setSearch: (value: string) => void; onSelect: (id: string) => void; onGhost: (id: string) => void; onCreated: (id: string) => void; onEditCategory: (category: LibraryCategory | 'new') => void
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [creating, setCreating] = useState<string | null>(null)
  const { resolve } = useLibrarySuggestionActions(bookId)
  const [keeping, setKeeping] = useState(false)
  const keepAll = async () => { setKeeping(true); try { for (const ghost of ghosts) await resolve.mutateAsync({ id: ghost.id, action: 'accept' }) } catch { /* 显示错误 */ } finally { setKeeping(false) } }
  return <aside aria-label="设定目录" className="flex max-h-[calc(100vh-14rem)] min-h-80 flex-col rounded-2xl border border-line bg-card shadow-[var(--shadow-paper)] @4xl/manuscript:sticky @4xl/manuscript:top-0">
    <div className="shrink-0 p-2.5">
      <label className="relative block"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" /><input aria-label="搜索设定" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜人名、地名、设定…" className="h-9 w-full rounded-lg bg-subtle pr-3 pl-9 text-sm ring-1 ring-line placeholder:text-ink-3 focus:bg-card focus:ring-ink-3/60 focus:outline-none" /></label>
    </div>
    {ghosts.length > 0 && <div className="mx-2.5 mb-1.5 shrink-0 rounded-xl bg-writer-soft/70 px-3 py-2.5 text-[13px] leading-relaxed text-writer">
      <p><Sparkles className="mr-1 inline size-3.5" />AI 想新建 {ghosts.length} 条，下面虚线的就是。点开看全文，要的留下。</p>
      <button type="button" disabled={keeping} onClick={() => void keepAll()} className="mt-1 font-medium underline-offset-4 hover:underline disabled:opacity-50">{keeping ? '正在留下…' : '全部留下'}</button>
    </div>}
    <nav className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 pb-2">
      {data.categories.map(category => {
        const Icon = CATEGORY_ICON[category.key] ?? Tags
        const items = rows.get(category.key) ?? []
        const ghostItems = ghosts.filter(ghost => createCategory(ghost) === category.key)
        const open = !collapsed[category.key] || search.trim() !== ''
        return <div key={category.key} className="mt-1">
          <div className="group flex items-center rounded-lg hover:bg-subtle">
            <button type="button" aria-expanded={open} onClick={() => setCollapsed(previous => ({ ...previous, [category.key]: open }))} className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2 text-left text-sm font-semibold text-ink">
              <ChevronRight className={clsx('size-3.5 shrink-0 text-ink-3 transition-transform', open && 'rotate-90')} /><Icon className="size-4 shrink-0 text-ink-2" /><span className="truncate">{category.name}</span><span className="text-xs font-normal text-ink-3 tabular-nums">{items.length || ''}</span>
            </button>
            {!category.builtin && <button type="button" aria-label={`改「${category.name}」这个类别`} onClick={() => onEditCategory(category)} className="rounded p-1.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:text-ink focus-visible:opacity-100"><MoreHorizontal className="size-4" /></button>}
            <button type="button" aria-label={`新建一条${category.name}`} title={`新建一条${category.name}`} onClick={() => { setCollapsed(previous => ({ ...previous, [category.key]: false })); setCreating(category.key) }} className="mr-1 rounded p-1.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:bg-card hover:text-ink focus-visible:opacity-100"><Plus className="size-4" /></button>
          </div>
          {open && <ul className="ml-3 space-y-0.5 border-l border-line pl-2">
            {creating === category.key && <NewEntryRow bookId={bookId} category={category} config={config} onCancel={() => setCreating(null)} onCreated={id => { setCreating(null); onCreated(id) }} />}
            {items.map(row => <li key={row.id}><button type="button" data-testid={`library-item-${row.id}`} aria-current={selectedId === row.id ? 'true' : undefined} onClick={() => onSelect(row.id)}
              className={clsx('block w-full rounded-lg py-1.5 pr-2 text-left transition-colors', selectedId === row.id ? 'bg-chief-soft' : 'hover:bg-subtle', row.status === 'later' && 'opacity-70')} style={{ paddingLeft: `${8 + Math.min(row.depth, 4) * 12}px` }}>
              <span className="flex items-center gap-1.5"><span className={clsx('min-w-0 truncate text-sm', selectedId === row.id ? 'font-semibold text-chief' : 'text-ink')}>{row.name}</span>
                {row.targetType === 'character' && row.role_type && ['主角', '女主', '男主'].includes(row.role_type) && <span className={clsx('shrink-0 rounded px-1 text-[11px] leading-4', ROLE_TONE[row.role_type])}>{row.role_type}</span>}
                {row.locked && <LockKeyhole aria-label="已锁住" className="size-3 shrink-0 text-ink-3" />}
                {suggested.has(row.id) && <span aria-label="有意见" className="ml-auto size-1.5 shrink-0 rounded-full bg-writer" />}</span>
              {row.one_line && <span className="mt-0.5 block truncate text-xs text-ink-3">{row.one_line}</span>}
            </button></li>)}
            {ghostItems.map(ghost => <li key={ghost.id}><button type="button" aria-current={ghostId === ghost.id ? 'true' : undefined} onClick={() => onGhost(ghost.id)} className={clsx('block w-full rounded-lg border border-dashed px-2 py-1.5 text-left transition-colors', ghostId === ghost.id ? 'border-writer bg-writer-soft/60' : 'border-line-2 hover:bg-subtle')}>
              <span className="flex items-center gap-1.5 text-sm text-ink-2"><span className="min-w-0 truncate">{createData(ghost).name}</span><span className="ml-auto shrink-0 text-[11px] text-writer">AI 建议</span></span>
            </button></li>)}
            {!items.length && !ghostItems.length && creating !== category.key && <li><button type="button" onClick={() => setCreating(category.key)} className="w-full rounded-lg px-2 py-1.5 text-left text-[13px] text-ink-3 hover:bg-subtle hover:text-ink-2">还没有 · ＋ 写一条</button></li>}
          </ul>}
        </div>
      })}
      <button type="button" onClick={() => onEditCategory('new')} className="mt-2 flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm text-chief hover:bg-subtle"><Plus className="size-4" />自建类别</button>
    </nav>
    <div className="shrink-0 px-2.5 pb-2"><ErrorText error={resolve.error} /></div>
  </aside>
}

// ---------------------------------------------------------------- 页面

export function LibraryPage() {
  const { bookId, book, job, working, manualNavigate } = useBookContext()
  const config = useLibraryConfig()
  const library = useLibrary(bookId)
  const suggestions = useLibrarySuggestions(bookId)
  const actions = useLibrarySuggestionActions(bookId)
  const [params] = useSearchParams()
  const [search, setSearch] = useState('')
  const [categoryEditor, setCategoryEditor] = useState<LibraryCategory | 'new' | null>(null)
  const data = library.data
  const statusOrder = config.data ? Object.keys(config.data.statuses) : []
  const all = data ? libraryRows(data) : []
  const pending = suggestions.data ?? []
  const ghosts = pending.filter(isCreate)
  const targeted = pending.filter(suggestion => !isCreate(suggestion) && all.some(row => row.id === suggestionTargetId(suggestion)))
  const general = pending.filter(suggestion => !isCreate(suggestion) && !targeted.includes(suggestion))
  const suggested = new Set(targeted.map(suggestionTargetId))
  const rows = new Map((data?.categories ?? []).map(category => [category.key, data && config.data ? filterLibraryRows(data, pending, { category: category.key, search }, statusOrder) : []]))
  const explicitId = params.get('id')
  const ghostId = params.get('ghost')
  const protagonist = all.find(row => row.targetType === 'character' && row.role_type === '主角')
  const fromCategory = params.get('cat') ? all.find(row => row.categoryKey === params.get('cat')) : undefined
  const ghost = ghostId ? ghosts.find(item => item.id === ghostId) : undefined
  const selected = all.find(row => row.id === explicitId) ?? (ghost ? undefined : fromCategory ?? protagonist ?? all[0])
  const shownGhost = ghost ?? (!selected ? ghosts[0] : undefined)
  const explicit = !!explicitId || !!ghostId
  const go = (query: string) => manualNavigate(`/books/${bookId}/library${query ? `?${query}` : ''}`)
  const select = (id: string) => go(`id=${id}`)
  const total = all.length
  const settingUp = job?.kind === 'book_setup' && working
  return <section data-testid="library-page">
    <SetupGate piece="settings" />
    <PageHeader eyebrow="书稿 · 设定" title="设定"
      subtitle={data ? total ? `共 ${total} 条${settingUp ? ' · 编辑部还在写' : ''}。点左边一条就在中间打开，哪里要改直接点哪里。` : '人物、世界、等级、势力、物品、往事与秘密、特殊规则，都放在这里。' : undefined}
      action={<>
        <Button size="sm" variant="outline" disabled={actions.inspect.isPending} onClick={() => actions.inspect.mutate({ mode: 'fill-gaps' })}><Sparkles className="size-3.5" />让 AI 补上缺的</Button>
        <Button size="sm" variant="outline" disabled={actions.inspect.isPending || !total} onClick={() => actions.inspect.mutate({ mode: 'review' })}>全部查一遍</Button>
      </>} />
    {actions.inspect.isPending && <p role="status" className="mb-4 flex items-center gap-2 text-sm text-chief"><Spinner className="size-3.5" />AI 正在看整个设定……想新建的会以虚线出现在左边目录里，意见会挂在对应的卡上。</p>}
    <ErrorText error={config.error ?? library.error ?? suggestions.error ?? actions.inspect.error} />
    {(config.isLoading || library.isLoading) && <div className="grid gap-6 @4xl/manuscript:grid-cols-[290px_minmax(0,1fr)]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>}
    {data && config.data && <div className="grid items-start gap-6 @4xl/manuscript:grid-cols-[290px_minmax(0,1fr)] @6xl/manuscript:gap-10">
      <div className={clsx(explicit && 'max-[1023px]:hidden @4xl/manuscript:block')}>
        <LibraryList bookId={bookId} data={data} config={config.data} rows={rows} ghosts={ghosts} suggested={suggested} selectedId={shownGhost ? undefined : selected?.id} ghostId={shownGhost?.id} search={search} setSearch={setSearch}
          onSelect={select} onGhost={id => go(`ghost=${id}`)} onCreated={select} onEditCategory={setCategoryEditor} />
      </div>
      <div className={clsx('min-w-0', !explicit && 'max-[1023px]:hidden @4xl/manuscript:block')}>
        {explicit && <Button className="mb-3 @4xl/manuscript:hidden" variant="ghost" size="sm" onClick={() => go('')}><ArrowLeft className="size-4" />回到目录</Button>}
        <GeneralNotes bookId={bookId} suggestions={general} />
        {shownGhost ? <GhostView key={shownGhost.id} bookId={bookId} suggestion={shownGhost}
          onKept={(name, category) => { const kept = libraryRows(data).find(row => row.name === name && row.categoryKey === category); if (kept) select(kept.id); else go('') }} onDropped={() => go('')} />
          : selected ? <EntryView key={selected.id} bookId={bookId} row={selected} library={data} config={config.data} suggestions={targeted.filter(suggestion => suggestionTargetId(suggestion) === selected.id)} onDeleted={() => go('')} />
            : <div className="mx-auto max-w-[860px] rounded-2xl border-[1.5px] border-dashed border-line-2 bg-card/50 px-8 py-16 text-center">
              <BookMarked aria-hidden className="mx-auto size-7 text-ink-3" />
              <p className="mt-3 font-serif text-xl font-bold text-ink">设定还空着</p>
              <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-ink-2">{job?.kind === 'book_setup' && !book.concept.story ? '在左边任意一类点「写一条」自己先写；在群聊里聊定了，「总结一下」再「按这个来」也会直接写进来；挑了故事方向，编辑部会一口气建好。' : '在左边任意一类点「写一条」，或者让 AI 先补上缺的。'}</p>
              <Button className="mt-5" variant="outline" disabled={actions.inspect.isPending} onClick={() => actions.inspect.mutate({ mode: 'fill-gaps' })}><Sparkles className="size-4" />让 AI 先补一批</Button>
            </div>}
      </div>
    </div>}
    {categoryEditor && <CategoryModal key={categoryEditor === 'new' ? 'new' : categoryEditor.id} bookId={bookId} category={categoryEditor === 'new' ? undefined : categoryEditor} config={config.data} onClose={() => setCategoryEditor(null)} onSaved={key => { setCategoryEditor(null); go(`cat=${encodeURIComponent(key)}`) }} />}
  </section>
}
