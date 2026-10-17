import clsx from 'clsx'
import { ArrowLeft, Check, ChevronDown, ChevronRight, EyeOff, Flag, Gem, Globe2, Layers, LockKeyhole, MoreHorizontal, Plus, ScrollText, Search, Sparkles, Tags, Trash2, UnlockKeyhole, Users, X } from 'lucide-react'
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

// 界面照 docs/界面规矩.md：按钮两到四个字、一块一个主按钮、空着的项不占地方、分组靠留白。

const CATEGORY_ICON: Record<string, typeof Users> = { 角色卡片: Users, 等级体系: Layers, 世界与地图: Globe2, 势力划分: Flag, 物品与功法: Gem, 往事与秘密: EyeOff, 特殊规则: ScrollText }
/** 空页面上每类的一句话。类别自带的 hint 是写给 AI 的长说明，这里只要一眼看懂；不分题材。 */
const CATEGORY_BLURB: Record<string, string> = {
  角色卡片: '有名有姓、会再出场的人',
  等级体系: '分高低的一串等级：境界、等级、官阶',
  世界与地图: '什么时代，有哪些地方',
  势力划分: '宗门、家族、国家、公司，谁和谁是敌是友',
  物品与功法: '法宝、道具、功法、技能',
  往事与秘密: '过去的事和藏着的真相',
  特殊规则: '这个世界独有的机制和代价',
}
const blurbOf = (category: LibraryCategory) => CATEGORY_BLURB[category.key] ?? category.hint.split(/[：；。]/)[0]?.slice(0, 24) ?? ''
/** 角色卡上方一行的小项，其余长的一项一行。 */
const CHARACTER_SHORT = ['name', 'aliases', 'role_type', 'gender', 'age']
const MAIN_ROLES = ['主角', '女主', '男主']
const FILL_INSTRUCTION = (label: string) => `按定调、设定库和这一类该写清的事，写「${label}」这一项：具体、能直接用在正文里`
/** 建议的「接受」按钮统一叫法。 */
const ACCEPT_LABEL: Record<string, string> = { 改: '采纳', 补: '补上', 建: '新建', 前文也一起换: '前文也改' }

type Target = { path: string; label: string }
const isCreate = (suggestion: LibrarySuggestion) => suggestion.payload.op === 'create_entry' || suggestion.payload.op === 'create_character'
const createData = (suggestion: LibrarySuggestion) => ((suggestion.payload.op === 'create_character' ? suggestion.payload.character : suggestion.payload.entry) ?? {}) as Record<string, string>
const createCategory = (suggestion: LibrarySuggestion) => suggestion.payload.op === 'create_character' ? '角色卡片' : createData(suggestion).category ?? ''
const reasonOf = (suggestion: LibrarySuggestion) => suggestion.title.includes('——') ? suggestion.title.split('——').slice(1).join('——') : String(suggestion.payload.why ?? '')
const acceptLabel = (suggestion: LibrarySuggestion) => { const action = suggestionAction(suggestion); return ACCEPT_LABEL[action] ?? action }

const sheet = 'mx-auto max-w-[820px] rounded-2xl px-6 py-6 @2xl/manuscript:px-10 @2xl/manuscript:py-8'
const panel = 'absolute z-40 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]'
const menuItem = 'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-ink hover:bg-subtle disabled:opacity-50'
const iconButton = 'flex size-8 shrink-0 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-line/60 hover:text-ink disabled:opacity-40'
const section = 'mt-8 border-t border-line/70 pt-6'
const sectionTitle = 'text-[15px] font-semibold text-ink'
const quietButton = 'flex items-center gap-1 rounded-lg px-2 py-1.5 text-[13px] text-ink-3 transition-colors hover:bg-subtle hover:text-ink'

// ---------------------------------------------------------------- 小部件

/** 点按钮打开、点别处或按 Esc 关上的小浮层。 */
function usePopover() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('pointerdown', close)
    window.addEventListener('keydown', escape)
    return () => { window.removeEventListener('pointerdown', close); window.removeEventListener('keydown', escape) }
  }, [open])
  return { open, setOpen, ref }
}

function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-4 py-2 @2xl/manuscript:grid-cols-[7.5rem_minmax(0,1fr)]">
    <dt className="pt-1 text-[13px] text-ink-3">{label}</dt>
    <dd className="min-w-0 text-[15px] leading-[1.8]">{children}</dd>
  </div>
}

/** 空着的项不占地方：点「＋ 添加」挑一项再写。 */
function AddField({ items, onPick }: { items: Target[]; onPick: (path: string) => void }) {
  const { open, setOpen, ref } = usePopover()
  if (!items.length) return null
  return <div ref={ref} className="relative mt-1 -ml-2 w-fit">
    <button type="button" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(value => !value)} className={quietButton}><Plus className="size-4" />添加</button>
    {open && <div role="menu" aria-label="添加哪一项" className={clsx(panel, 'top-full left-0 mt-1 w-52')}>
      {items.map(item => <button key={item.path} type="button" role="menuitem" onClick={() => { setOpen(false); onPick(item.path) }} className={menuItem}>{item.label}</button>)}
    </div>}
  </div>
}

/** 「⋯」里的东西一直挂着，关上只是藏起来：里面打开的「历史」弹窗不会跟着消失。 */
function MoreMenu({ children }: { children: ReactNode }) {
  const { open, setOpen, ref } = usePopover()
  return <div ref={ref} className="relative">
    <button type="button" aria-label="更多" title="更多" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(value => !value)} className={iconButton}><MoreHorizontal className="size-[18px]" /></button>
    <div role="menu" aria-label="更多" onClick={event => { if ((event.target as HTMLElement).closest('button')) setOpen(false) }}
      className={clsx(panel, 'top-full right-0 mt-1 w-56 space-y-0.5 [&_button]:w-full [&_button]:justify-start', !open && 'hidden')}>{children}</div>
  </div>
}

/** 「＋ 新建」：先挑一类，目录里那一类下面出现输入框。 */
function NewMenu({ categories, onPick, align = 'right', size = 'sm' }: { categories: LibraryCategory[]; onPick: (key: string) => void; align?: 'right' | 'center'; size?: 'sm' | 'md' }) {
  const { open, setOpen, ref } = usePopover()
  return <div ref={ref} className="relative">
    <Button variant="primary" size={size} aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(value => !value)}><Plus className="size-4" />新建</Button>
    {open && <div role="menu" aria-label="新建哪一类" className={clsx(panel, 'top-full mt-1.5 w-48 text-left', align === 'right' ? 'right-0' : 'left-1/2 -translate-x-1/2')}>
      {categories.map(category => {
        const Icon = CATEGORY_ICON[category.key] ?? Tags
        return <button key={category.key} type="button" role="menuitem" onClick={() => { setOpen(false); onPick(category.key) }} className={menuItem}><Icon className="size-4 text-ink-3" />{category.name}</button>
      })}
    </div>}
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

function useKeepAll(bookId: string, ghosts: LibrarySuggestion[]) {
  const { resolve } = useLibrarySuggestionActions(bookId)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const run = async () => {
    setRunning(true); setError(null)
    try { for (const ghost of ghosts) await resolve.mutateAsync({ id: ghost.id, action: 'accept' }) } catch (cause) { setError(cause) } finally { setRunning(false) }
  }
  return { run, running, error }
}

// ---------------------------------------------------------------- 建议：都收在页头「建议」里

function InboxGroup({ title, count, action, children }: { title: string; count: number; action?: ReactNode; children: ReactNode }) {
  return <section aria-label={title} className="py-1">
    <p className="flex items-center gap-1.5 px-2.5 pt-1.5 pb-1 text-xs text-ink-3">{title}<span className="tabular-nums">{count}</span>{action && <span className="ml-auto">{action}</span>}</p>
    <ul>{children}</ul>
  </section>
}

function InboxItem({ title, detail, onOpen, children }: { title: string; detail?: string; onOpen?: () => void; children?: ReactNode }) {
  const body = <><span className="block truncate text-sm font-medium text-ink">{title}</span>{detail && <span className="mt-0.5 line-clamp-2 block text-[13px] leading-snug text-ink-2">{detail}</span>}</>
  return <li className="flex items-start gap-2 rounded-lg px-2.5 py-2 hover:bg-subtle">
    {onOpen ? <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">{body}</button> : <div className="min-w-0 flex-1">{body}</div>}
    {children && <div className="flex shrink-0 items-center gap-1">{children}</div>}
  </li>
}

/** 所有等你看的建议放在一处；标签上的数字就是这里的条数。挂在某一条上的，卡上也会显示。 */
function SuggestionInbox({ bookId, ghosts, targeted, general, names, onOpenEntry, onOpenGhost }: {
  bookId: string; ghosts: LibrarySuggestion[]; targeted: LibrarySuggestion[]; general: LibrarySuggestion[]; names: Map<string, string>
  onOpenEntry: (id: string) => void; onOpenGhost: (id: string) => void
}) {
  const { working, waiting, asking } = useBookContext()
  const { resolve } = useLibrarySuggestionActions(bookId)
  const qc = useQueryClient()
  const runChat = useMutation({ mutationFn: (id: string) => post(`/suggestions/${id}/run-chat`), onSuccess: () => qc.invalidateQueries() })
  const keepAll = useKeepAll(bookId, ghosts)
  const { open, setOpen, ref } = usePopover()
  const total = ghosts.length + targeted.length + general.length
  if (!total) return null
  const go = (action: () => void) => { setOpen(false); action() }
  return <div ref={ref} className="relative">
    <Button variant="ghost" size="sm" aria-expanded={open} title="编辑部给设定的建议" onClick={() => setOpen(value => !value)}>建议<span className="rounded-full bg-writer-soft px-1.5 text-[11px] leading-[18px] text-writer tabular-nums">{total}</span></Button>
    {open && <div aria-label="建议" className={clsx(panel, 'top-full right-0 mt-1.5 max-h-[70vh] w-[26rem] max-w-[calc(100vw-2rem)] overflow-y-auto p-2')}>
      {ghosts.length > 0 && <InboxGroup title="想新建" count={ghosts.length} action={<button type="button" disabled={keepAll.running} onClick={() => void keepAll.run()} className="font-medium text-chief hover:underline disabled:opacity-50">{keepAll.running ? '正在留下…' : '全部留下'}</button>}>
        {ghosts.map(ghost => <InboxItem key={ghost.id} title={createData(ghost).name} detail={[createCategory(ghost), reasonOf(ghost)].filter(Boolean).join(' · ')} onOpen={() => go(() => onOpenGhost(ghost.id))}>
          <Button size="sm" variant="outline" disabled={resolve.isPending || keepAll.running} onClick={() => resolve.mutate({ id: ghost.id, action: 'accept' })}>留下</Button>
          <Button size="sm" variant="ghost" disabled={resolve.isPending || keepAll.running} onClick={() => resolve.mutate({ id: ghost.id, action: 'ignore' })}>不要</Button>
        </InboxItem>)}
      </InboxGroup>}
      {targeted.length > 0 && <InboxGroup title="挂在条目上" count={targeted.length}>
        {targeted.map(suggestion => {
          const id = suggestionTargetId(suggestion) ?? ''
          return <InboxItem key={suggestion.id} title={names.get(id) ?? '某一条'} detail={suggestion.title.replaceAll('（已锁）', '')} onOpen={() => go(() => onOpenEntry(id))} />
        })}
      </InboxGroup>}
      {general.length > 0 && <InboxGroup title="其他意见" count={general.length}>
        {general.map(suggestion => <InboxItem key={suggestion.id} title={suggestion.title} detail={String(suggestion.payload.why ?? '')}>
          {suggestion.kind === 'chat'
            ? <Button size="sm" variant="outline" disabled={runChat.isPending || working || waiting || asking} loading={runChat.isPending && runChat.variables === suggestion.id} onClick={() => runChat.mutate(suggestion.id)}>现在改</Button>
            : <Button size="sm" variant="outline" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' })}>{acceptLabel(suggestion) === '采纳' ? '知道了' : acceptLabel(suggestion)}</Button>}
          <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' })}>忽略</Button>
        </InboxItem>)}
      </InboxGroup>}
      <div className="px-2.5"><ErrorText error={resolve.error ?? runChat.error ?? keepAll.error} /></div>
    </div>}
  </div>
}

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
  const tags = row.tags.filter(tag => tag !== row.role_type)
  const deleteItem = async () => {
    if (!window.confirm(`删除「${row.name}」？这条设定会从设定里拿掉。`)) return
    try { await remove.mutateAsync({ type: row.targetType, id: row.id }); onDeleted() } catch { /* 显示错误 */ }
  }
  return <header>
    <div className="flex min-h-8 items-center gap-2 text-[13px] text-ink-3">
      <Icon className="size-3.5" />{category?.name ?? row.categoryKey}
      {row.status === 'later' && <span className="rounded bg-subtle px-1.5 text-xs leading-5 text-ink-2 ring-1 ring-line">以后再说</span>}
      <div className="ml-auto flex items-center gap-0.5">
        {fillTargets.length > 0 && !row.locked && (fill.progress
          ? <Button variant="ghost" size="sm" title="停下" onClick={fill.stop}><Spinner className="size-3.5" />{fill.progress.done}/{fill.progress.total}</Button>
          : <Button variant="ghost" size="sm" title={`让 AI 写空着的 ${fillTargets.length} 项`} onClick={() => void fill.run(row, fillTargets)}><Sparkles className="size-3.5 text-chief" />补全</Button>)}
        <button type="button" aria-label={row.locked ? '解锁' : '锁住'} aria-pressed={row.locked} title={row.locked ? '已锁住：AI 不会改它，你自己照样能改。点一下解锁' : '锁住：AI 就不会再改它'}
          disabled={update.isPending} onClick={() => void save({ locked: !row.locked }).catch(() => undefined)} className={clsx(iconButton, row.locked && 'bg-subtle text-ink')}>
          {row.locked ? <LockKeyhole className="size-4" /> : <UnlockKeyhole className="size-4" />}
        </button>
        <MoreMenu>
          <TargetHistory bookId={bookId} targetType={row.targetType} targetId={row.id} />
          <button type="button" className={menuItem} onClick={() => void save({ status: row.status === 'later' ? 'must' : 'later' }).catch(() => undefined)}>{row.status === 'later' ? '改成现在就定' : '改成以后再说'}</button>
          {config.focus_tags.map(tag => <button key={tag} type="button" className={menuItem} onClick={() => toggleTag(tag)}>{row.tags.includes(tag) ? `取消「${tag}」` : `标成「${tag}」`}</button>)}
          {row.targetType === 'entry' && moveTo.length > 0 && <label className="flex items-center gap-2 px-3 py-2 text-sm">移到<select aria-label="移到别的类别" value="" onChange={event => event.target.value && void save({ category: event.target.value }).catch(() => undefined)} className="min-w-0 flex-1 rounded-md border border-line-2 bg-card px-1.5 py-1"><option value="">别的类别…</option>{moveTo.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>}
          <button type="button" className={menuItem} disabled={inspect.isPending} onClick={() => inspect.mutate({ mode: 'check', target_type: row.targetType, target_id: row.id })}>检查这一条</button>
          <button type="button" className={clsx(menuItem, 'text-seal hover:bg-seal-soft')} onClick={() => void deleteItem()}><Trash2 className="size-4" />删除</button>
        </MoreMenu>
      </div>
    </div>
    <InlineText multiline={false} value={row.name} label="名字" placeholder="名字" onSave={name => { if (!name) throw new Error('名字不能空着'); return save({ name }) }} className="mt-1.5 font-serif text-[30px] leading-tight font-bold" />
    {tags.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{tags.map(tag => <span key={tag} className="rounded-md bg-writer-soft px-2 text-xs leading-6 text-writer">{tag}</span>)}</div>}
    {inspect.isPending && <p role="status" className="mt-2 flex items-center gap-1.5 text-[13px] text-chief"><Spinner className="size-3" />审稿在看这一条…</p>}
    <ErrorText error={update.error ?? remove.error ?? inspect.error ?? fill.error} />
  </header>
}

// ---------------------------------------------------------------- 卡片上的意见

function EntryNotes({ bookId, row, suggestions }: { bookId: string; row: LibraryRow; suggestions: LibrarySuggestion[] }) {
  const { resolve } = useLibrarySuggestionActions(bookId)
  const [open, setOpen] = useState<string | null>(null)
  if (!suggestions.length) return null
  return <section aria-label="这一条的意见" className="mt-5 space-y-2">
    {suggestions.map(suggestion => {
      const written = suggestion.kind === 'written'
      const why = String(suggestion.payload.why ?? '')
      return <div key={suggestion.id} className="rounded-xl bg-writer-soft/70 px-4 py-3 text-sm">
        <p className="leading-relaxed text-ink">{suggestion.title.replaceAll('（已锁）', '')}</p>
        {why && why !== suggestion.title && <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{why}</p>}
        {written && open === suggestion.id && Array.isArray(suggestion.payload.matches) && <div className="mt-2 space-y-2 text-[13px] text-ink-2">{(suggestion.payload.matches as { chapter: number; count: number; contexts: string[] }[]).map(match => <div key={match.chapter}><p className="font-medium">第 {match.chapter} 章 · {match.count} 处</p>{match.contexts.map((context, index) => <p key={index} className="mt-1 rounded bg-card p-2 leading-relaxed">…{context}…</p>)}</div>)}</div>}
        <div className="mt-2.5 flex flex-wrap gap-2">
          {written && open !== suggestion.id
            ? <Button size="sm" variant="outline" onClick={() => setOpen(suggestion.id)}>看看前文</Button>
            : <Button size="sm" variant="primary" disabled={row.locked || resolve.isPending} title={row.locked ? '锁住了，先解锁' : undefined} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' })}>{written ? '前文也改' : acceptLabel(suggestion)}</Button>}
          <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' })}>{written ? '只改以后' : '忽略'}</Button>
        </div>
      </div>
    })}
    <ErrorText error={resolve.error} />
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
const keepAdding = (setAdding: (path: string | null) => void) => (text: string) => { if (!text) setAdding(null) }

function CharacterBody({ bookId, row, config, adding, setAdding }: { bookId: string; row: LibraryRow; config: LibraryConfig; adding: string | null; setAdding: (path: string | null) => void }) {
  const save = useRowSave(bookId, row)
  const long = config.character_category.fields.filter(field => !CHARACTER_SHORT.includes(field.column))
  const value = (column: keyof LibraryItem) => String(row[column] ?? '')
  const all = [{ column: 'one_line' as keyof LibraryItem, name: '一句话' }, ...long]
  const shown = all.filter(field => field.column === 'one_line' || value(field.column).trim() || adding === field.column)
  const missing = all.filter(field => !shown.includes(field))
  const roles = [...new Set([row.role_type ?? '', ...config.role_types])].filter(Boolean)
  return <>
    <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink-3">
      <select aria-label="定位" value={row.role_type ?? ''} onChange={event => void save({ role_type: event.target.value }).catch(() => undefined)} className="-ml-0.5 rounded-md bg-subtle px-2 py-1 text-[13px] font-medium text-ink ring-1 ring-line hover:ring-line-2">{roles.map(role => <option key={role}>{role}</option>)}</select>
      <span className="flex items-center gap-2">性别<InlineText multiline={false} value={row.gender ?? ''} label="性别" placeholder="—" onSave={gender => save({ gender })} className="w-12 text-[14px] text-ink" /></span>
      <span className="flex items-center gap-2">年龄<InlineText multiline={false} value={row.age ?? ''} label="年龄" placeholder="—" onSave={age => save({ age })} className="w-16 text-[14px] text-ink" /></span>
      <span className="flex min-w-48 flex-1 items-center gap-2">也叫<InlineText multiline={false} value={(row.aliases ?? []).join('、')} label="也叫" placeholder="别名，用顿号隔开" onSave={text => save({ aliases: text.split(/[、,，]/).map(item => item.trim()).filter(Boolean) })} className="min-w-0 flex-1 text-[14px] text-ink" /></span>
    </div>
    <dl className="mt-6">
      {shown.map(field => <FieldRow key={field.column} label={field.name}>
        <InlineText value={value(field.column)} placeholder={field.column === 'one_line' ? '一句话说清这个人' : '点这里写'} autoEdit={adding === field.column} onDone={keepAdding(setAdding)} onSave={text => save({ [field.column]: text } as LibraryItemPatch)} ai={aiFor(bookId, row, field.column, field.name)} />
      </FieldRow>)}
    </dl>
    <AddField items={missing.map(field => ({ path: field.column, label: field.name }))} onPick={setAdding} />
  </>
}

function ParagraphBody({ bookId, row, library }: { bookId: string; row: LibraryRow; library: LibrarySnapshot }) {
  const save = useRowSave(bookId, row)
  return <dl className="mt-6">
    <FieldRow label="一句话"><InlineText value={row.one_line ?? ''} placeholder="一句话说清这是什么" onSave={one_line => save({ one_line })} ai={aiFor(bookId, row, 'one_line', '一句话')} /></FieldRow>
    <FieldRow label="详细"><InlineText value={row.content ?? ''} placeholder="详细写写：样子、规矩、来历、和谁有关" onSave={content => save({ content })} ai={aiFor(bookId, row, 'content', '详细')} /></FieldRow>
    {row.categoryKey === '世界与地图' && <FieldRow label="属于"><select aria-label="属于哪里" value={row.parent_id ?? ''} onChange={event => void save({ parent_id: event.target.value || null }).catch(() => undefined)} className="-ml-0.5 rounded-md bg-subtle px-2 py-1 text-[14px] text-ink ring-1 ring-line hover:ring-line-2"><option value="">不属于别的地方</option>{parentChoices(library.entries, row).map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></FieldRow>}
  </dl>
}

function CardBody({ bookId, row, library, adding, setAdding }: { bookId: string; row: LibraryRow; library: LibrarySnapshot; adding: string | null; setAdding: (path: string | null) => void }) {
  const save = useRowSave(bookId, row)
  const category = library.categories.find(item => item.key === row.categoryKey)
  const names = [...new Set([...(category?.fields ?? []), ...(row.fields ?? []).map(field => field.name)])]
  const valueOf = (name: string) => row.fields?.find(field => field.name === name)?.value ?? ''
  const saveField = (name: string, value: string) => save({ fields: names.map(item => ({ name: item, value: item === name ? value : valueOf(item) })) })
  const shown = names.filter(name => valueOf(name).trim() || adding === `fields.${name}`)
  const missing = names.filter(name => !shown.includes(name))
  return <>
    <dl className="mt-6">
      <FieldRow label="一句话"><InlineText value={row.one_line ?? ''} placeholder="一句话说清这是什么" onSave={one_line => save({ one_line })} ai={aiFor(bookId, row, 'one_line', '一句话')} /></FieldRow>
      {shown.map(name => <FieldRow key={name} label={name}><InlineText value={valueOf(name)} autoEdit={adding === `fields.${name}`} onDone={keepAdding(setAdding)} onSave={text => saveField(name, text)} ai={aiFor(bookId, row, `fields.${name}`, name)} /></FieldRow>)}
    </dl>
    <AddField items={missing.map(name => ({ path: `fields.${name}`, label: name }))} onPick={setAdding} />
  </>
}

function LadderBody({ bookId, row }: { bookId: string; row: LibraryRow }) {
  const save = useRowSave(bookId, row)
  const levels = row.levels ?? []
  const saveLevels = (next: typeof levels) => save({ levels: next })
  const move = (index: number, offset: number) => { const next = [...levels]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; void saveLevels(next).catch(() => undefined) }
  return <>
    <dl className="mt-6"><FieldRow label="总说明"><InlineText value={row.content ?? ''} placeholder="怎么往上升、越级多难、有什么代价" onSave={content => save({ content })} ai={aiFor(bookId, row, 'content', '总说明')} /></FieldRow></dl>
    <ol aria-label="各级" className="mt-4 space-y-2">{levels.map((level, index) => <li key={index} className="group/level flex gap-4 py-1.5">
      <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-ink font-serif text-[13px] text-paper-2" style={{ opacity: 0.45 + Math.min(index, 8) * 0.07 }}>{index + 1}</span>
      <div className="min-w-0 flex-1">
        <InlineText multiline={false} value={level.name} label={`第 ${index + 1} 级叫什么`} placeholder="这一级叫什么" onSave={name => saveLevels(levels.map((item, at) => at === index ? { ...item, name } : item))} className="font-serif text-[17px] font-bold" />
        <InlineText value={level.text} placeholder="能做到什么、凭什么升上来" onSave={text => saveLevels(levels.map((item, at) => at === index ? { ...item, text } : item))} ai={aiFor(bookId, row, `levels.${index}.text`, level.name || `第 ${index + 1} 级`)} className="mt-0.5 text-[15px] leading-[1.8]" />
      </div>
      <div className="flex shrink-0 flex-col opacity-0 transition-opacity group-hover/level:opacity-100 focus-within:opacity-100">
        <button type="button" aria-label="上移" title="上移" disabled={index === 0} onClick={() => move(index, -1)} className="rounded p-1 text-ink-3 hover:text-ink disabled:opacity-30"><ChevronDown className="size-4 rotate-180" /></button>
        <button type="button" aria-label="下移" title="下移" disabled={index === levels.length - 1} onClick={() => move(index, 1)} className="rounded p-1 text-ink-3 hover:text-ink disabled:opacity-30"><ChevronDown className="size-4" /></button>
        <button type="button" aria-label="删掉这一级" title="删掉这一级" onClick={() => { if (window.confirm(`删掉「${level.name || `第 ${index + 1} 级`}」？`)) void saveLevels(levels.filter((_, at) => at !== index)).catch(() => undefined) }} className="rounded p-1 text-ink-3 hover:text-seal"><X className="size-4" /></button>
      </div>
    </li>)}</ol>
    <button type="button" onClick={() => void saveLevels([...levels, { name: '', text: '' }]).catch(() => undefined)} className={clsx(quietButton, 'mt-2 -ml-2')}><Plus className="size-4" />加一级</button>
  </>
}

function Relations({ bookId, characterId }: { bookId: string; characterId: string }) {
  const { working } = useBookContext()
  const { data: bible } = useBible(bookId)
  const { create, update, remove } = useBibleMutations(bookId, 'relationships')
  const [adding, setAdding] = useState(false)
  const [target, setTarget] = useState('')
  const [kind, setKind] = useState('')
  const characters = bible?.characters ?? []
  const names = Object.fromEntries(characters.map(row => [row.id, row.name]))
  const rows = (bible?.relationships ?? []).filter(row => row.source_id === characterId || row.target_id === characterId)
  const others = characters.filter(row => row.id !== characterId)
  const canAdd = !working && others.length > 0
  const close = () => { setAdding(false); setKind(''); setTarget('') }
  if (!rows.length && !adding) return canAdd ? <section aria-label="人物关系" className={section}><button type="button" onClick={() => setAdding(true)} className={clsx(quietButton, '-ml-2')}><Plus className="size-4" />人物关系</button></section> : null
  return <section aria-label="人物关系" className={section}>
    <div className="flex items-center"><h3 className={sectionTitle}>人物关系</h3>{canAdd && !adding && <button type="button" onClick={() => setAdding(true)} className={clsx(quietButton, 'ml-auto')}><Plus className="size-4" />添加</button>}</div>
    {rows.length > 0 && <ul className="mt-3 space-y-2">{rows.map(row => {
      const other = row.source_id === characterId ? row.target_id : row.source_id
      return <li key={row.id} className="group flex items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-subtle font-serif text-sm text-ink-2 ring-1 ring-line">{(names[other] ?? '？').slice(0, 1)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><b className="text-[15px] font-semibold">{names[other] ?? '（已删除）'}</b><InlineText multiline={false} value={row.kind} label="什么关系" placeholder="什么关系" disabled={working} onSave={value => update.mutateAsync({ id: row.id, kind: value })} className="min-w-24 text-[14px] text-ink-2" /></div>
          <InlineText value={row.description} label="这段关系的说明" placeholder="之间有什么张力、以后会怎样" disabled={working} onSave={value => update.mutateAsync({ id: row.id, description: value })} className="mt-0.5 text-[13px] text-ink-2" />
        </div>
        {!working && <button type="button" aria-label={`删除和${names[other]}的关系`} title="删除这段关系" onClick={() => remove.mutate(row.id)} className="rounded p-1 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:text-seal focus-visible:opacity-100"><Trash2 className="size-4" /></button>}
      </li>
    })}</ul>}
    {adding && <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={async event => { event.preventDefault(); if (!target || !kind.trim()) return; try { await create.mutateAsync({ source_id: characterId, target_id: target, kind: kind.trim(), description: '' }); close() } catch { /* 显示错误 */ } }}>
      <select autoFocus aria-label="和谁" value={target} onChange={event => setTarget(event.target.value)} className="h-9 rounded-lg border border-line-2 bg-card px-2.5 text-sm"><option value="">和谁…</option>{others.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
      <input aria-label="什么关系" value={kind} onChange={event => setKind(event.target.value)} placeholder="什么关系：师徒、死敌、青梅竹马…" className="h-9 min-w-0 flex-1 rounded-lg border border-line-2 bg-card px-3 text-sm placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
      <Button type="submit" size="sm" variant="primary" disabled={!target || !kind.trim()} loading={create.isPending}>添加</Button>
      <Button type="button" size="sm" variant="ghost" onClick={close}>取消</Button>
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
  const error = <ErrorText error={create.error ?? update.error ?? updateItem.error ?? secrets.error} />
  if (!secret) return <section aria-label="谁知道这件事" className={section}><button type="button" disabled={create.isPending} onClick={() => void link()} title="记下谁知道、读者知不知道、打算怎么揭开" className={clsx(quietButton, '-ml-2')}><Plus className="size-4" />谁知道</button>{error}</section>
  return <section aria-label="谁知道这件事" className={section}>
    <h3 className={sectionTitle}>谁知道这件事</h3>
    <dl className="mt-2">
      <FieldRow label="谁知道"><div className="flex flex-wrap items-center gap-1.5 pt-0.5">
        {secret.knowers.map((knower, index) => <span key={`${knower.name}-${index}`} className="inline-flex items-center gap-1 rounded-full bg-subtle py-0.5 pr-1 pl-3 text-[13px] ring-1 ring-line" title={knower.how || undefined}>{knower.name}{knower.since_chapter !== null && <span className="text-ink-3">· 第 {knower.since_chapter} 章起</span>}<button type="button" aria-label={`${knower.name}不知道`} title="拿掉" onClick={() => void save({ knowers: secret.knowers.filter((_, at) => at !== index) }).catch(() => undefined)} className="rounded-full p-0.5 text-ink-3 hover:text-seal"><X className="size-3" /></button></span>)}
        {!secret.knowers.length && <span className="text-[14px] text-ink-3">还没人知道</span>}
        {others.length > 0 && <select aria-label="加一个知道的人" value={adding} onChange={event => { const name = event.target.value; setAdding(''); if (name) void save({ knowers: [...secret.knowers, { name, since_chapter: null, how: '' }] }).catch(() => undefined) }} className="rounded-full bg-card px-2.5 py-0.5 text-[13px] text-ink-3 ring-1 ring-line hover:text-ink"><option value="">＋ 加人</option>{others.map(character => <option key={character.id}>{character.name}</option>)}</select>}
      </div></FieldRow>
      <FieldRow label="读者知道吗"><div className="flex flex-wrap gap-1.5 pt-0.5">{(['不知道', '部分', '知道'] as const).map(choice => <button key={choice} type="button" aria-pressed={secret.reader_knows === choice} onClick={() => void save({ reader_knows: secret.reader_knows === choice ? null : choice }).catch(() => undefined)} className={clsx('rounded-full px-3 py-0.5 text-[13px] ring-1', secret.reader_knows === choice ? 'bg-ink text-paper-2 ring-ink' : 'bg-card text-ink-2 ring-line hover:text-ink')}>{choice === '部分' ? '知道一部分' : choice}</button>)}</div></FieldRow>
      <FieldRow label="怎么揭开"><InlineText value={secret.reveal_plan} label="打算怎么揭开" placeholder="在什么情境下、怎么揭开" onSave={reveal_plan => save({ reveal_plan })} /></FieldRow>
    </dl>
    {error}
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
  return <article aria-label={row.name} className={clsx(sheet, 'bg-card shadow-[var(--shadow-paper)] ring-1 ring-line')}>
    <EntryHeader bookId={bookId} row={row} library={library} config={config} fillTargets={fillTargets} onDeleted={onDeleted} />
    <EntryNotes bookId={bookId} row={row} suggestions={suggestions} />
    {row.targetType === 'character' ? <CharacterBody bookId={bookId} row={row} config={config} adding={adding} setAdding={setAdding} />
      : style === 'ladder' ? <LadderBody bookId={bookId} row={row} />
        : style === 'card' ? <CardBody bookId={bookId} row={row} library={library} adding={adding} setAdding={setAdding} />
          : <ParagraphBody bookId={bookId} row={row} library={library} />}
    {row.targetType === 'character' && <Relations bookId={bookId} characterId={row.id} />}
    {row.categoryKey === '往事与秘密' && <SecretSection bookId={bookId} row={row} />}
    {row.targetType === 'character' && writing && <section aria-label="写到现在" className={section}><h3 className={sectionTitle}>写到现在<span className="ml-2 text-[13px] font-normal text-ink-3">每章更新</span></h3><dl className="mt-3 grid gap-x-6 gap-y-2 text-sm @2xl/manuscript:grid-cols-2">{config.character_category.state_fields.map(field => <div key={field.column} className="flex gap-3"><dt className="w-16 shrink-0 text-ink-3">{field.name}</dt><dd>{typeof row[field.column] === 'boolean' ? (row[field.column] ? '活着' : '已故') : String(row[field.column] || '—')}</dd></div>)}</dl></section>}
  </article>
}

/** AI 补全想新建的一条：先看全文，留下才进设定。 */
function GhostView({ bookId, suggestion, onKept, onDropped }: { bookId: string; suggestion: LibrarySuggestion; onKept: (name: string, category: string) => void; onDropped: () => void }) {
  const { resolve } = useLibrarySuggestionActions(bookId)
  const config = useLibraryConfig()
  const data = createData(suggestion)
  const character = suggestion.payload.op === 'create_character'
  const rows: [string, string][] = character
    ? [['一句话', data.one_line], ...(config.data?.character_category.fields ?? []).filter(field => !['name', 'aliases'].includes(field.column)).map(field => [field.name, data[field.column as string]] as [string, string])]
    : [['一句话', data.one_line], ['详细', data.content]]
  return <article aria-label={`AI 建议新建：${data.name}`} className={clsx(sheet, 'border-[1.5px] border-dashed border-line-2 bg-card/70')}>
    <p className="flex min-h-8 items-center gap-1.5 text-[13px] text-writer"><Sparkles className="size-3.5" />AI 建议新建 · {createCategory(suggestion)}</p>
    <h2 className="mt-1.5 font-serif text-[30px] leading-tight font-bold text-ink">{data.name}</h2>
    {reasonOf(suggestion) && <p className="mt-2 text-sm leading-relaxed text-ink-2">{reasonOf(suggestion)}</p>}
    <dl className="mt-6">{rows.filter(([, value]) => String(value ?? '').trim()).map(([label, value]) => <FieldRow key={label} label={label}><p className="whitespace-pre-wrap text-ink-2">{value}</p></FieldRow>)}</dl>
    <div className="mt-6 flex gap-2">
      <Button variant="primary" loading={resolve.isPending && resolve.variables?.action === 'accept'} disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' }, { onSuccess: () => onKept(data.name, createCategory(suggestion)) })}><Check className="size-4" />留下</Button>
      <Button variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' }, { onSuccess: onDropped })}>不要</Button>
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
  return <li className="py-0.5">
    <input autoFocus aria-label={`新的${category.name}叫什么`} value={name} onChange={event => setName(event.target.value)} disabled={create.isPending}
      onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); void submit() } else if (event.key === 'Escape') onCancel() }} onBlur={() => { if (!name.trim()) onCancel() }}
      placeholder="叫什么？回车建好" className="h-8 w-full rounded-lg bg-card px-2.5 text-[14px] shadow-[0_0_0_1px_var(--color-line-2)] outline-none placeholder:text-ink-3" />
    <ErrorText error={create.error} />
  </li>
}

function LibraryList({ bookId, data, config, rows, ghosts, suggested, selectedId, ghostId, search, setSearch, creating, setCreating, onSelect, onGhost, onCreated, onEditCategory }: {
  bookId: string; data: LibrarySnapshot; config: LibraryConfig; rows: Map<string, LibraryRow[]>; ghosts: LibrarySuggestion[]; suggested: Set<string | null>; selectedId?: string; ghostId?: string
  search: string; setSearch: (value: string) => void; creating: string | null; setCreating: (key: string | null) => void
  onSelect: (id: string) => void; onGhost: (id: string) => void; onCreated: (id: string) => void; onEditCategory: (category: LibraryCategory | 'new') => void
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const query = search.trim()
  const found = !query || data.categories.some(category => (rows.get(category.key)?.length ?? 0) > 0)
  return <aside aria-label="设定目录" className="flex max-h-[calc(100vh-13rem)] min-h-80 flex-col @4xl/manuscript:sticky @4xl/manuscript:top-0">
    <label className="relative block shrink-0"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" /><input aria-label="搜索设定" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索" className="h-9 w-full rounded-lg bg-card pr-3 pl-9 text-sm ring-1 ring-line placeholder:text-ink-3 focus:ring-ink-3/60 focus:outline-none" /></label>
    <nav className="scroll-thin mt-3 min-h-0 flex-1 overflow-y-auto pr-1 pb-2">
      {data.categories.map(category => {
        const Icon = CATEGORY_ICON[category.key] ?? Tags
        const items = rows.get(category.key) ?? []
        const ghostItems = ghosts.filter(ghost => createCategory(ghost) === category.key && (!query || createData(ghost).name.includes(query)))
        if (query && !items.length && !ghostItems.length) return null
        const hasAny = items.length > 0 || ghostItems.length > 0 || creating === category.key
        const open = !collapsed[category.key] || !!query || creating === category.key
        return <div key={category.key} className="mb-1.5">
          <div className="group flex items-center rounded-lg hover:bg-line/40">
            <button type="button" aria-expanded={hasAny ? open : undefined} onClick={() => hasAny && setCollapsed(previous => ({ ...previous, [category.key]: open }))} className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left text-[13px] font-semibold text-ink-2">
              <ChevronRight className={clsx('size-3.5 shrink-0 text-ink-3 transition-transform', open && 'rotate-90', !hasAny && 'invisible')} /><Icon className="size-4 shrink-0 text-ink-3" /><span className="truncate">{category.name}</span>{items.length > 0 && <span className="text-xs font-normal text-ink-3 tabular-nums">{items.length}</span>}
            </button>
            {!category.builtin && <button type="button" aria-label={`改「${category.name}」这个类别`} title="改这个类别" onClick={() => onEditCategory(category)} className="rounded p-1.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:text-ink focus-visible:opacity-100"><MoreHorizontal className="size-4" /></button>}
            <button type="button" aria-label={`新建一条${category.name}`} title={`新建一条${category.name}`} onClick={() => { setCollapsed(previous => ({ ...previous, [category.key]: false })); setCreating(category.key) }} className="mr-1 rounded p-1.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:bg-card hover:text-ink focus-visible:opacity-100"><Plus className="size-4" /></button>
          </div>
          {open && hasAny && <ul className="mt-0.5 space-y-px pl-6">
            {creating === category.key && <NewEntryRow bookId={bookId} category={category} config={config} onCancel={() => setCreating(null)} onCreated={id => { setCreating(null); onCreated(id) }} />}
            {items.map(row => <li key={row.id}><button type="button" data-testid={`library-item-${row.id}`} aria-current={selectedId === row.id ? 'true' : undefined} onClick={() => onSelect(row.id)}
              className={clsx('flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-[14px] transition-colors', selectedId === row.id ? 'bg-chief-soft font-medium text-chief' : 'text-ink hover:bg-line/40', row.status === 'later' && selectedId !== row.id && 'text-ink-3')} style={{ paddingLeft: `${10 + Math.min(row.depth, 4) * 12}px` }}>
              <span className="min-w-0 truncate">{row.name}</span>
              {row.targetType === 'character' && row.role_type && MAIN_ROLES.includes(row.role_type) && <span className="shrink-0 rounded bg-subtle px-1 text-[11px] leading-4 font-normal text-ink-2 ring-1 ring-line">{row.role_type}</span>}
              {row.locked && <LockKeyhole aria-label="已锁住" className="size-3 shrink-0 text-ink-3" />}
              {suggested.has(row.id) && <span aria-label="有意见" title="有意见" className="ml-auto size-1.5 shrink-0 rounded-full bg-writer" />}
            </button></li>)}
            {ghostItems.map(ghost => <li key={ghost.id}><button type="button" aria-current={ghostId === ghost.id ? 'true' : undefined} onClick={() => onGhost(ghost.id)} title="AI 建议新建，点开看全文" className={clsx('flex w-full items-center gap-1.5 rounded-lg border border-dashed px-2.5 py-1 text-left text-[14px] text-ink-2 transition-colors', ghostId === ghost.id ? 'border-writer bg-writer-soft/60' : 'border-line-2 hover:bg-line/40')}>
              <span className="min-w-0 truncate">{createData(ghost).name}</span><Sparkles aria-label="AI 建议" className="ml-auto size-3.5 shrink-0 text-writer" />
            </button></li>)}
          </ul>}
        </div>
      })}
      {!found && <p className="px-2 py-4 text-[13px] text-ink-3">没找到</p>}
      <button type="button" onClick={() => onEditCategory('new')} className={clsx(quietButton, 'mt-1 w-full')}><Plus className="size-4" />新类别</button>
    </nav>
  </aside>
}

/**
 * 一条设定都没有：不是孤零零一个图标，而是一张「设定目录」——几类各占一行，说清这里放什么，
 * 点哪一类就从哪一类自己写。最上面一句话说清这些什么时候、由谁写好；平时编辑部写，作者改。
 */
function EmptyLibrary({ story, settingUp, categories, filling, busy, onFill, onCreate, onNewCategory }: {
  story: boolean; settingUp: boolean; categories: LibraryCategory[]; filling: boolean; busy: boolean
  onFill: () => void; onCreate: (key: string) => void; onNewCategory: () => void
}) {
  const idle = story && !settingUp
  // 和页头「设定」左边对齐，不居中：一页只留一条对齐线。
  return <div className={clsx(sheet, 'ml-0 bg-card shadow-[var(--shadow-paper)] ring-1 ring-line')}>
    <div className="flex flex-wrap items-start gap-x-6 gap-y-4">
      <div className="min-w-0 flex-1">
        <h2 className="flex items-center gap-2.5 font-serif text-[22px] leading-tight font-bold text-ink">{settingUp && <Spinner className="size-4 text-chief" />}{settingUp ? '编辑部正在写设定' : '还没有设定'}</h2>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-2">{settingUp ? '写好一条，这里就多一条。想先自己写也行，点下面任意一类。' : idle ? '可以让编辑部照着定调补全，也可以点下面任意一类自己写。' : '方向定下来以后，编辑部会按下面几类一口气建好。想先写也行，点任意一类。'}</p>
      </div>
      {idle && <Button variant="primary" loading={filling} disabled={busy} title="让编辑部照着定调把设定补全" onClick={onFill}>{!filling && <Sparkles className="size-4" />}补全</Button>}
    </div>
    <ul aria-label="设定分这几类" className="mt-7 divide-y divide-line/70 border-y border-line/70">
      {categories.map(category => {
        const Icon = CATEGORY_ICON[category.key] ?? Tags
        return <li key={category.key}>
          <button type="button" onClick={() => onCreate(category.key)} title={`自己写一条${category.name}`} className="group flex w-full items-center gap-4 rounded-lg px-2 py-3 text-left transition-colors hover:bg-subtle/70">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-subtle text-ink-2 ring-1 ring-line"><Icon className="size-[18px]" /></span>
            <span className="w-24 shrink-0 text-[15px] font-semibold text-ink">{category.name}</span>
            <span className="min-w-0 flex-1 truncate text-[14px] text-ink-3">{blurbOf(category)}</span>
            <span className="flex shrink-0 items-center gap-1 text-[13px] text-ink-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"><Plus className="size-4" />写一条</span>
          </button>
        </li>
      })}
    </ul>
    <button type="button" onClick={onNewCategory} className={clsx(quietButton, 'mt-3 -ml-2')}><Plus className="size-4" />新类别</button>
  </div>
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
  const [creating, setCreating] = useState<string | null>(null)
  const [categoryEditor, setCategoryEditor] = useState<LibraryCategory | 'new' | null>(null)
  const data = library.data
  const statusOrder = config.data ? Object.keys(config.data.statuses) : []
  const all = data ? libraryRows(data) : []
  const pending = suggestions.data ?? []
  const ghosts = pending.filter(isCreate)
  const targeted = pending.filter(suggestion => !isCreate(suggestion) && all.some(row => row.id === suggestionTargetId(suggestion)))
  const general = pending.filter(suggestion => !isCreate(suggestion) && !targeted.includes(suggestion))
  const suggested = new Set(targeted.map(suggestionTargetId))
  const names = new Map(all.map(row => [row.id, row.name]))
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
  const busy = actions.inspect.isPending
  const filling = busy && actions.inspect.variables?.mode === 'fill-gaps'
  const reviewing = busy && actions.inspect.variables?.mode === 'review'
  const fillGaps = () => actions.inspect.mutate({ mode: 'fill-gaps' })
  const startCreate = (key: string) => { setSearch(''); setCreating(key) }
  const empty = !!data && !!config.data && !total && !ghosts.length && creating === null
  return <section data-testid="library-page">
    <SetupGate piece="settings" />
    <PageHeader eyebrow="书稿 · 设定" title={<span className="flex items-baseline gap-2.5">设定{total > 0 && <span className="font-sans text-[15px] font-normal text-ink-3 tabular-nums">{total}</span>}</span>}
      subtitle={settingUp ? <span className="flex items-center gap-1.5 text-chief"><Spinner className="size-3" />编辑部在写</span> : undefined}
      action={data && config.data ? <div className="flex items-center gap-1.5">
        <SuggestionInbox bookId={bookId} ghosts={ghosts} targeted={targeted} general={general} names={names} onOpenEntry={select} onOpenGhost={id => go(`ghost=${id}`)} />
        {!empty && <>
          <Button size="sm" variant="ghost" loading={filling} disabled={busy} title="让 AI 看看还缺哪些人和设定，想新建的会用虚线列在目录里" onClick={fillGaps}>{!filling && <Sparkles className="size-3.5 text-chief" />}补全</Button>
          <Button size="sm" variant="ghost" loading={reviewing} disabled={busy || !total} title="让审稿把设定从头查一遍，有意见会挂在对应的卡上" onClick={() => actions.inspect.mutate({ mode: 'review' })}>检查</Button>
          <NewMenu categories={data.categories} onPick={startCreate} />
        </>}
      </div> : undefined} />
    <ErrorText error={config.error ?? library.error ?? suggestions.error ?? actions.inspect.error} />
    {(config.isLoading || library.isLoading) && <div className="grid gap-6 @4xl/manuscript:grid-cols-[250px_minmax(0,1fr)]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>}
    {empty && <EmptyLibrary story={!!book.concept.story?.trim()} settingUp={settingUp} categories={data.categories} filling={filling} busy={busy} onFill={fillGaps} onCreate={startCreate} onNewCategory={() => setCategoryEditor('new')} />}
    {data && config.data && !empty && <div className="grid items-start gap-6 @4xl/manuscript:grid-cols-[250px_minmax(0,1fr)] @6xl/manuscript:gap-10">
      <div className={clsx(explicit && creating === null && 'max-[1023px]:hidden @4xl/manuscript:block')}>
        <LibraryList bookId={bookId} data={data} config={config.data} rows={rows} ghosts={ghosts} suggested={suggested} selectedId={shownGhost ? undefined : selected?.id} ghostId={shownGhost?.id} search={search} setSearch={setSearch}
          creating={creating} setCreating={setCreating} onSelect={select} onGhost={id => go(`ghost=${id}`)} onCreated={select} onEditCategory={setCategoryEditor} />
      </div>
      <div className={clsx('min-w-0', !explicit && 'max-[1023px]:hidden @4xl/manuscript:block')}>
        {explicit && <Button className="mb-3 @4xl/manuscript:hidden" variant="ghost" size="sm" onClick={() => go('')}><ArrowLeft className="size-4" />目录</Button>}
        {shownGhost ? <GhostView key={shownGhost.id} bookId={bookId} suggestion={shownGhost}
          onKept={(name, category) => { const kept = libraryRows(data).find(row => row.name === name && row.categoryKey === category); if (kept) select(kept.id); else go('') }} onDropped={() => go('')} />
          : selected ? <EntryView key={selected.id} bookId={bookId} row={selected} library={data} config={config.data} suggestions={targeted.filter(suggestion => suggestionTargetId(suggestion) === selected.id)} onDeleted={() => go('')} />
            : null}
      </div>
    </div>}
    {categoryEditor && <CategoryModal key={categoryEditor === 'new' ? 'new' : categoryEditor.id} bookId={bookId} category={categoryEditor === 'new' ? undefined : categoryEditor} config={config.data} onClose={() => setCategoryEditor(null)} onSaved={key => { setCategoryEditor(null); go(`cat=${encodeURIComponent(key)}`) }} />}
  </section>
}
