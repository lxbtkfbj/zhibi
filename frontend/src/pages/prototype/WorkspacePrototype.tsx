import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, ArrowUp, BookOpen, ChevronDown, ChevronRight, ChevronUp, Globe, Inbox, Library, Lock, Minus, PanelRight, PictureInPicture2, Plus, Search, Settings, Sparkles, Wand2 } from 'lucide-react'
import { type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { get } from '../../api/client'
import type { LibrarySnapshot } from '../../api/library'
import type { BookSummary, ChapterBrief } from '../../api/types'
import { BookCover } from '../../components/BookCover'
import type { OutlineTree } from '../../lib/outlineTree'
import { type ApiParts, bookFromApi } from './fromApi'
import {
  CHARACTER_PLACEHOLDERS, GOLDFINGER_PLACEHOLDERS, ROLE_ORDER, cn, emptyCategory, findEntry, findNode, numberChapters,
  type VBook, type VCategory, type VEntry, type VField, type VNode,
} from './model'
import { CHAT, PENDING, SAMPLE_BOOK, emptyBook } from './sampleBook'

type Tab = '简介' | '设定' | '大纲'
type Dock = 'ball' | 'float' | 'side'
type CategoryStyle = NonNullable<VCategory['custom']>['style']

const ROLE_STYLE: Record<string, string> = {
  主编: 'bg-chief text-on-role',
  设定师: 'bg-lore text-on-role',
  写手: 'bg-writer text-on-role',
  审稿: 'bg-reviewer text-on-role',
}

/** 页面之间互相跳：关系点到人，出场点到大纲节点，大纲用到的设定点回设定。 */
interface Nav {
  openEntry: (id: string) => void
  openNode: (id: string) => void
  toast: (text: string) => void
}

/* ---------------- 读哪本书 ---------------- */

const SNAPSHOTS = [
  { key: 'nisu', title: '逆溯邮差', note: '以前用真模型写的，字段长、关系多' },
  { key: 'nishi', title: '逆世帝尊', note: '演示模型写的，地点有 62 条' },
]

function useBookSource(source: string): { book?: VBook; loading: boolean; error?: string } {
  const live = source.startsWith('live:') ? source.slice(5) : ''
  const snap = source.startsWith('snap:') ? source.slice(5) : ''
  const query = useQuery({
    queryKey: ['prototype-book', source],
    enabled: !!(live || snap),
    staleTime: 60_000,
    queryFn: async (): Promise<VBook> => {
      if (snap) return bookFromApi((await (await fetch(`/prototype-data/${snap}.json`)).json()) as ApiParts)
      const [book, library, outline, bible, chapters] = await Promise.all([
        get<ApiParts['book']>(`/books/${live}`),
        get<LibrarySnapshot>(`/books/${live}/library`),
        get<OutlineTree>(`/books/${live}/outline-tree`),
        get<{ relationships: ApiParts['relationships'] }>(`/books/${live}/bible`),
        get<ChapterBrief[]>(`/books/${live}/chapters`),
      ])
      return bookFromApi({ book, library, outline, relationships: bible.relationships ?? [], chapters })
    },
  })
  const empty = useMemo(() => emptyBook(), [])
  if (source === 'empty') return { book: empty, loading: false }
  if (!live && !snap) return { book: SAMPLE_BOOK, loading: false }
  return { book: query.data, loading: query.isPending, error: query.error ? String(query.error) : undefined }
}

function BookSwitcher({ source, onSource, inline }: { source: string; onSource: (source: string) => void; inline?: boolean }) {
  const [open, setOpen] = useState(false)
  const shelf = useQuery({ queryKey: ['books'], queryFn: () => get<BookSummary[]>('/books') })
  const label = source === 'empty' ? '刚开的空书'
    : source.startsWith('snap:') ? SNAPSHOTS.find((s) => `snap:${s.key}` === source)?.title
      : source.startsWith('live:') ? shelf.data?.find((b) => `live:${b.id}` === source)?.title ?? '书架上的书' : '示例书'
  const item = (key: string, title: string, note: string) => (
    <button key={key} type="button" onClick={() => { onSource(key); setOpen(false) }}
      className={clsx('block w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-subtle', source === key && 'bg-subtle')}>
      <span className="block font-serif text-[15px] text-ink">{title}</span>
      <span className="block text-xs text-ink-3">{note}</span>
    </button>
  )
  return (
    <div className={inline ? 'relative' : 'fixed bottom-4 left-4 z-30'}>
      {open && (
        <div className={clsx('scroll-thin absolute z-40 max-h-[70vh] w-80 overflow-y-auto rounded-xl border border-line bg-card p-2 shadow-[var(--shadow-lift)]', inline ? 'top-[calc(100%+8px)] right-0' : 'bottom-[calc(100%+8px)] left-0')}>
          {item('sample', '示例书 · 窥命长生', '我挑过的理想内容')}
          {item('empty', '刚开的空书', '点完「下一步」看到的样子')}
          <p className="mt-2 px-3 pb-1 text-xs tracking-wider text-ink-3">你书架上的书 · 只读</p>
          {shelf.isPending && <p className="px-3 py-2 text-[13px] text-ink-3">正在读书架…</p>}
          {shelf.data?.map((b) => item(`live:${b.id}`, b.title || '未命名', [b.genre, b.idea].filter(Boolean).join(' · ').slice(0, 40) || '没有简介'))}
          {shelf.data?.length === 0 && <p className="px-3 py-2 text-[13px] text-ink-3">书架是空的</p>}
          <p className="mt-2 px-3 pb-1 text-xs tracking-wider text-ink-3">以前的书 · 快照，只读</p>
          {SNAPSHOTS.map((s) => item(`snap:${s.key}`, s.title, s.note))}
        </div>
      )}
      <button type="button" onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-full border border-writer/30 bg-writer-soft py-1.5 pr-3 pl-3.5 text-xs text-writer shadow-[var(--shadow-paper)] transition-colors hover:border-writer/60">
        <Library className="size-3.5" />
        原型 · 正在看：{label}
        <ChevronUp className={clsx('size-3.5 transition-transform', inline ? !open && 'rotate-180' : open || 'rotate-180')} />
      </button>
    </div>
  )
}

/* ---------------- 小部件 ---------------- */

/** 可以直接改的字：点上去就是输入框，不用先点「编辑」；空着时显示该写什么。 */
function Editable({ children, className, multiline, boxed, placeholder, autoFocus }: { children?: ReactNode; className?: string; multiline?: boolean; boxed?: boolean; placeholder?: string; autoFocus?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (autoFocus) ref.current?.focus()
  }, [autoFocus])
  return (
    <div
      ref={ref}
      contentEditable
      suppressContentEditableWarning
      spellCheck={false}
      data-placeholder={placeholder}
      className={clsx(
        'outline-none transition-colors',
        boxed ? 'focus:ring-1 focus:ring-line-2' : '-mx-2 rounded-md px-2 hover:bg-subtle focus:bg-subtle',
        multiline && 'whitespace-pre-line',
        placeholder && 'empty:before:text-ink-3/60 empty:before:content-[attr(data-placeholder)]',
        className,
      )}
    >
      {children}
    </div>
  )
}

const LONG = 260

/** 一段长文字：可以直接改；太长先折起来。 */
function Prose({ text, placeholder, autoFocus }: { text: string; placeholder?: string; autoFocus?: boolean }) {
  const long = text.length > LONG
  const [open, setOpen] = useState(false)
  return (
    <>
      <div className={clsx('relative', long && !open && 'max-h-[11.5em] overflow-hidden')}>
        <Editable multiline autoFocus={autoFocus} placeholder={placeholder ?? '还没写'} className="font-serif text-[17px] leading-[1.95] text-ink 2xl:text-lg">{text}</Editable>
        {long && !open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-manuscript to-transparent" />}
      </div>
      {long && (
        <button type="button" onClick={() => setOpen(!open)} className="mt-1 text-[13px] text-chief hover:underline">
          {open ? '收起' : `展开全文（${text.length} 字）`}
        </button>
      )}
    </>
  )
}

/** 正文里的一栏：小标题加一段字。 */
function Section({ field, children }: { field: VField; children?: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-[13px] tracking-[0.15em] text-ink-3">{field.label}</h3>
      <Prose text={field.text} placeholder={field.placeholder} />
      {children}
    </section>
  )
}

/** 右边资料卡里的一块。 */
function Side({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section>
      <div className="mb-2.5 flex items-baseline justify-between gap-2">
        <h3 className="text-[13px] tracking-[0.15em] text-ink-3">{title}</h3>
        {note && <span className="text-[11px] text-ink-3/80">{note}</span>}
      </div>
      {children}
    </section>
  )
}

function FactRows({ rows }: { rows: [string, string, string?][] }) {
  if (!rows.length) return null
  return (
    <dl className="divide-y divide-line/70 rounded-xl border border-line bg-card/70">
      {rows.map(([label, value, placeholder]) => (
        // 内容长的：名称放上面、内容占满一行，别挤在窄栏里
        <div key={label} className={clsx('px-4 py-2.5', value.length > 18 ? 'space-y-1' : 'grid grid-cols-[4rem_minmax(0,1fr)] items-baseline gap-3')}>
          <dt className="text-[13px] text-ink-3">{label}</dt>
          <dd className="min-w-0"><Editable placeholder={placeholder ?? '—'} className="text-[15px] leading-relaxed break-words text-ink">{value}</Editable></dd>
        </div>
      ))}
    </dl>
  )
}

function LinkChip({ icon, children, onClick }: { icon?: ReactNode; children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-subtle px-3 py-1 text-[13px] text-ink-2 transition-colors hover:bg-line/60 hover:text-ink">
      {icon}<span className="truncate">{children}</span>
    </button>
  )
}

function Appears({ items, nav }: { items: VEntry['appears']; nav: Nav }) {
  if (!items.length) return <p className="text-[13px] leading-relaxed text-ink-3">大纲里还没用到。</p>
  return (
    <div className="space-y-1">
      {items.map((item) => (
        <button key={item.node} type="button" onClick={() => nav.openNode(item.node)}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[14px] text-ink-2 transition-colors hover:bg-subtle hover:text-ink">
          <BookOpen className="size-3.5 shrink-0 text-ink-3" />
          <span className="truncate">{item.label}</span>
        </button>
      ))}
    </div>
  )
}

function AskButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="flex h-10 items-center gap-2 rounded-lg bg-ink px-5 text-sm text-paper-2 transition-colors hover:bg-ink-2">
      <span className="flex size-5 items-center justify-center rounded-full bg-chief font-serif text-[11px] text-on-role">编</span>
      {children}
    </button>
  )
}

/* ---------------- 顶栏 ---------------- */

function TopBar({ book, tab, onTab, switcher }: { book: VBook; tab: Tab; onTab: (tab: Tab) => void; switcher: ReactNode }) {
  const [inbox, setInbox] = useState(false)
  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-paper px-4 2xl:h-16 2xl:px-6">
      <Link to="/" className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
        <ArrowLeft className="size-4" />
        书房
      </Link>
      <span className="h-5 w-px bg-line-2" />
      <BookCover title={book.title} seed={book.id === 'sample' ? '开新书' : book.id} size="xs" />
      <span className="max-w-64 truncate font-serif text-[17px] font-bold tracking-wide 2xl:text-lg">{book.title}</span>

      {/* 四个入口放在整条顶栏正中 */}
      <nav className="absolute inset-y-0 left-1/2 flex -translate-x-1/2 items-stretch">
        {(['简介', '设定', '大纲'] as const).map((key) => (
          <button key={key} type="button" onClick={() => onTab(key)}
            className={clsx('relative px-5 text-[15px] transition-colors 2xl:px-6 2xl:text-base', tab === key ? 'font-medium text-ink' : 'text-ink-3 hover:text-ink')}>
            {key}
            {tab === key && <span className="absolute inset-x-4 bottom-0 h-0.5 rounded-full bg-seal" />}
          </button>
        ))}
        <span className="flex cursor-not-allowed items-center px-5 text-[15px] text-ink-3/50 2xl:px-6 2xl:text-base" title="开写以后才有">正文</span>
      </nav>

      <div className="ml-auto flex items-center gap-1">
        <div className="mr-3">{switcher}</div>
        {book.pending > 0 && (
          <div className="relative">
            <button type="button" onClick={() => setInbox(!inbox)} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-ink-2 transition-colors hover:bg-line/50 hover:text-ink">
              <Inbox className="size-4" />
              待处理
              <span className="flex min-w-5 items-center justify-center rounded-full bg-seal px-1.5 text-[11px] leading-5 text-on-role">{book.pending}</span>
            </button>
            {inbox && (
              <div className="absolute top-[calc(100%+6px)] right-0 w-80 rounded-xl border border-line bg-card p-2 shadow-[var(--shadow-lift)]">
                {(book.id === 'sample' ? PENDING : [{ id: 'x', text: `这本书有 ${book.pending} 条编辑部挂着的建议，原型里先不展开。` }]).map((item) => (
                  <div key={item.id} className="rounded-lg px-3 py-2.5 hover:bg-subtle">
                    <p className="text-[13px] leading-relaxed text-ink">{item.text}</p>
                    {book.id === 'sample' && (
                      <div className="mt-1.5 flex gap-3 text-xs">
                        <button type="button" className="text-chief hover:underline">去看看</button>
                        <button type="button" className="text-ink-3 hover:text-ink">不用</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <button type="button" className="rounded-lg p-2 text-ink-3 transition-colors hover:bg-line/50 hover:text-ink" aria-label="本书设置" title="本书设置">
          <Settings className="size-4" />
        </button>
      </div>
    </header>
  )
}

/* ---------------- 左边目录 ---------------- */

function DirectoryShell({ title, search, onTitle, children, footer, addMenu }: { title: string; search: string; onTitle?: () => void; children: ReactNode; footer?: ReactNode; addMenu?: { label: string; onClick: () => void }[] }) {
  const [menu, setMenu] = useState(false)
  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-line bg-paper-2 2xl:w-80">
      <div className="relative flex items-center justify-between px-5 pt-5 pb-3">
        <button type="button" onClick={onTitle} className="text-xs tracking-[0.25em] text-ink-3 hover:text-ink">{title}</button>
        <button type="button" onClick={() => setMenu(!menu)} className="rounded-md p-1 text-ink-3 transition-colors hover:bg-line/60 hover:text-ink" aria-label="新建" title="新建">
          <Plus className="size-4" />
        </button>
        {menu && addMenu && (
          <div className="absolute top-[calc(100%-4px)] right-4 z-30 w-48 rounded-xl border border-line bg-card p-1 shadow-[var(--shadow-lift)]">
            {addMenu.map((item) => (
              <button key={item.label} type="button" onClick={() => { setMenu(false); item.onClick() }}
                className="block w-full rounded-lg px-3 py-2 text-left text-sm text-ink-2 hover:bg-subtle hover:text-ink">
                {item.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <label className="mx-4 mb-3 flex h-9 items-center gap-2 rounded-lg border border-line bg-card/70 px-3 text-sm text-ink-3 focus-within:border-line-2">
        <Search className="size-4 shrink-0" />
        <input placeholder={search} className="min-w-0 flex-1 bg-transparent text-ink placeholder:text-ink-3 focus:outline-none" />
      </label>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pb-20">
        {children}
        {footer}
      </div>
    </aside>
  )
}

const rowSelected = 'bg-card shadow-[0_1px_2px_rgb(60_40_20/0.08)]'

function EntryButton({ entry, selected, depth = 0, onSelect }: { entry: VEntry; selected: string; depth?: number; onSelect: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onSelect(entry.id)} title={entry.name}
      style={{ paddingLeft: 10 + depth * 14 }}
      className={clsx('flex w-full items-center gap-2 rounded-md py-[7px] pr-2.5 text-left font-serif text-[15px] transition-colors 2xl:text-base',
        selected === entry.id ? `${rowSelected} font-bold text-ink` : 'text-ink-2 hover:bg-line/40 hover:text-ink')}>
      {depth > 0 && <span className="text-ink-3/60">└</span>}
      <span className={clsx('truncate', !entry.name && 'text-ink-3')}>{entry.name || '未命名'}</span>
      {entry.locked && <Lock className="size-3 shrink-0 text-ink-3" />}
    </button>
  )
}

const SHOW_FIRST = 12

/** 一类里的条目：地点按「属于哪里」缩进；太多先只显示前面一部分。 */
function EntryList({ entries, selected, onSelect }: { entries: VEntry[]; selected: string; onSelect: (id: string) => void }) {
  const [all, setAll] = useState(false)
  const ids = new Set(entries.map((e) => e.id))
  const children = new Map<string, VEntry[]>()
  for (const e of entries) if (e.parent && ids.has(e.parent)) children.set(e.parent, [...(children.get(e.parent) ?? []), e])
  const rows: { entry: VEntry; depth: number }[] = []
  const walk = (e: VEntry, depth: number) => {
    rows.push({ entry: e, depth })
    for (const child of children.get(e.id) ?? []) walk(child, Math.min(depth + 1, 3))
  }
  entries.filter((e) => !e.parent || !ids.has(e.parent)).forEach((e) => walk(e, 0))
  const selectedAt = rows.findIndex((r) => r.entry.id === selected)
  const limit = all || selectedAt >= SHOW_FIRST ? rows.length : SHOW_FIRST
  return (
    <>
      {rows.slice(0, limit).map(({ entry, depth }) => <EntryButton key={entry.id} entry={entry} depth={depth} selected={selected} onSelect={onSelect} />)}
      {rows.length > limit && (
        <button type="button" onClick={() => setAll(true)} className="w-full rounded-md px-2.5 py-1.5 text-left text-[13px] text-chief hover:bg-line/40">
          还有 {rows.length - limit} 条，展开
        </button>
      )}
    </>
  )
}

function CharacterGroups({ entries, selected, onSelect }: { entries: VEntry[]; selected: string; onSelect: (id: string) => void }) {
  const roles = [...ROLE_ORDER, ...new Set(entries.map((e) => e.role ?? '配角').filter((r) => !ROLE_ORDER.includes(r)))]
  const [closed, setClosed] = useState<string[]>(() => (entries.filter((e) => e.role === '配角').length > 4 ? ['配角'] : []))
  return (
    <>
      {roles.map((role) => {
        const members = entries.filter((e) => (e.role ?? '配角') === role)
        if (!members.length) return null
        const open = !closed.includes(role) || members.some((m) => m.id === selected)
        return (
          <div key={role} className="mb-1">
            <button type="button" onClick={() => setClosed(open ? [...closed, role] : closed.filter((r) => r !== role))}
              className="flex w-full items-center gap-1.5 px-2.5 pt-2 pb-1 text-left text-xs text-ink-3 hover:text-ink">
              {role}
              <span className="tabular-nums">{members.length}</span>
              {!open && <span className="ml-auto">展开</span>}
            </button>
            {open && members.map((entry) => <EntryButton key={entry.id} entry={entry} selected={selected} onSelect={onSelect} />)}
          </div>
        )
      })}
    </>
  )
}

const CATEGORY_STYLES: [CategoryStyle, string, string][] = [
  ['card', '卡片', '一栏一栏填，栏目自己定，像角色卡'],
  ['paragraph', '段落', '一个名字加一段话，像特殊规则'],
  ['ladder', '阶梯', '一级一级往上排，像境界'],
]

/** 自建类别：起名、选每一条长什么样；选卡片就自己定有哪几栏。 */
function NewCategoryForm({ taken, onCreate, onCancel }: { taken: string[]; onCreate: (name: string, style: CategoryStyle, fields: string[]) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [style, setStyle] = useState<CategoryStyle>('card')
  const [fields, setFields] = useState('')
  const clean = name.trim()
  const error = taken.includes(clean) ? '已经有这一类了' : ''
  const create = () => {
    if (clean && !error) onCreate(clean, style, fields.split(/[、,，;；\s]+/).map((f) => f.trim()).filter(Boolean))
  }
  return (
    <div className="mt-3 rounded-xl border border-line bg-card p-3.5 shadow-[var(--shadow-paper)]">
      <p className="mb-2 text-xs text-ink-3">新建一类</p>
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={20} placeholder="起个名字，比如：厉鬼、剧本、副本"
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) create() }}
        className="h-9 w-full rounded-lg border border-line-2 bg-card px-3 text-sm text-ink placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
      <p className="mt-3 mb-1.5 text-xs text-ink-3">每一条长什么样</p>
      <div className="space-y-1">
        {CATEGORY_STYLES.map(([key, label, desc]) => (
          <button key={key} type="button" onClick={() => setStyle(key)}
            className={clsx('block w-full rounded-lg border px-3 py-2 text-left transition-colors', style === key ? 'border-ink-3 bg-subtle' : 'border-line hover:border-line-2')}>
            <span className="text-sm text-ink">{label}</span>
            <span className="block text-xs text-ink-3">{desc}</span>
          </button>
        ))}
      </div>
      {style === 'card' && (
        <>
          <p className="mt-3 mb-1.5 text-xs text-ink-3">每条有哪几栏</p>
          <input value={fields} onChange={(e) => setFields(e.target.value)} placeholder="用顿号隔开：杀人规律、关押方法、等级"
            className="h-9 w-full rounded-lg border border-line-2 bg-card px-3 text-sm text-ink placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
        </>
      )}
      {error && <p className="mt-2 text-xs text-seal">{error}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="h-8 rounded-lg px-3 text-sm text-ink-2 hover:bg-subtle">取消</button>
        <button type="button" onClick={create} disabled={!clean || !!error}
          className="h-8 rounded-lg bg-ink px-4 text-sm text-paper-2 transition-colors hover:bg-ink-2 disabled:opacity-40">建好</button>
      </div>
    </div>
  )
}

function SettingsDirectory({ book, selected, onSelect, onCreateCategory, onNewEntry }: {
  book: VBook; selected: string; onSelect: (id: string) => void
  onCreateCategory: (name: string, style: CategoryStyle, fields: string[]) => void; onNewEntry: (category: string) => void
}) {
  const [closed, setClosed] = useState<string[]>([])
  const [creating, setCreating] = useState(false)
  const current = selected.startsWith('cat:') ? selected.slice(4) : findEntry(book, selected)?.category
  return (
    <DirectoryShell title="设定" search="找人物、地方、规矩……" onTitle={() => onSelect('overview')}
      addMenu={[
        ...(current ? [{ label: `在「${current}」里新建一条`, onClick: () => onNewEntry(current) }] : []),
        { label: '新建一类', onClick: () => setCreating(true) },
      ]}
      footer={creating ? (
        <NewCategoryForm taken={book.categories.map((c) => c.name)} onCancel={() => setCreating(false)}
          onCreate={(name, style, fields) => { setCreating(false); onCreateCategory(name, style, fields) }} />
      ) : (
        <button type="button" onClick={() => setCreating(true)}
          className="mt-4 flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-line-2 py-2 text-[13px] text-ink-3 transition-colors hover:border-ink-3/60 hover:text-ink">
          <Plus className="size-3.5" />新建一类
        </button>
      )}>
      {selected === 'overview' && <div className={clsx('mb-1 rounded-md px-3 py-1.5 text-sm font-medium text-ink', rowSelected)}>设定总览</div>}
      <button type="button" onClick={() => onSelect('world')}
        className={clsx('mb-1 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors', selected === 'world' ? `${rowSelected} font-medium text-ink` : 'text-ink-2 hover:bg-line/50')}>
        <Globe className="size-3.5 text-ink-3" />
        世界概况
        {!book.world && <span className="ml-auto pr-0.5 text-xs text-ink-3">空</span>}
      </button>
      {book.categories.map((cat) => {
        const open = !closed.includes(cat.name)
        const catId = `cat:${cat.name}`
        return (
          <div key={cat.name} className="mt-1.5">
            <div className={clsx('group flex items-center rounded-md transition-colors', selected === catId ? rowSelected : 'hover:bg-line/50')}>
              <button type="button" onClick={() => setClosed(open ? [...closed, cat.name] : closed.filter((n) => n !== cat.name))}
                className={clsx('flex size-7 items-center justify-center text-ink-3', !cat.entries.length && 'invisible')} aria-label={open ? '收起' : '展开'}>
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              </button>
              <button type="button" onClick={() => onSelect(catId)} className={clsx('flex-1 py-1.5 text-left text-sm', selected === catId ? 'font-medium text-ink' : cat.entries.length ? 'text-ink-2' : 'text-ink-3')}>
                {cat.name}
                {cat.custom && <span className="ml-1.5 text-[11px] text-ink-3">自建</span>}
              </button>
              <span className="pr-3 text-xs text-ink-3 tabular-nums">{cat.entries.length || '空'}</span>
            </div>
            {open && cat.entries.length > 0 && (
              <div className="mt-0.5 mb-1 ml-[17px] border-l border-line pl-1.5">
                {cat.name === '角色列表' ? <CharacterGroups entries={cat.entries} selected={selected} onSelect={onSelect} />
                  : <EntryList entries={cat.entries} selected={selected} onSelect={onSelect} />}
              </div>
            )}
          </div>
        )
      })}
    </DirectoryShell>
  )
}

/** 大纲树的一行：鼠标移上去出现「+」，在这一层下面加一个。 */
function OutlineTreeView({ node, depth, selected, onSelect, open, toggle, onAdd }: {
  node: VNode; depth: number; selected: string; onSelect: (id: string) => void; open: string[]; toggle: (id: string) => void; onAdd: (id: string) => void
}) {
  const expandable = !!node.children?.length
  const expanded = open.includes(node.id)
  const child = childKind(node)
  return (
    <div>
      <div className={clsx('group flex items-center rounded-md transition-colors', selected === node.id ? rowSelected : 'hover:bg-line/40')}
        style={{ paddingLeft: depth * 12 }}>
        <button type="button" onClick={() => expandable && toggle(node.id)} className={clsx('flex size-7 shrink-0 items-center justify-center text-ink-3', !expandable && 'invisible')} aria-label={expanded ? '收起' : '展开'}>
          {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
        <button type="button" onClick={() => onSelect(node.id)} title={node.title}
          className={clsx('min-w-0 flex-1 truncate py-[7px] pr-2 text-left',
            node.kind === '章' ? 'text-sm' : 'font-serif text-[15px] 2xl:text-base',
            node.later ? 'text-ink-3' : selected === node.id ? 'font-bold text-ink' : 'text-ink-2 group-hover:text-ink')}>
          {node.title}
          {node.later && <span className="ml-1.5 text-xs font-normal">· 写到再定</span>}
        </button>
        {node.locked && <Lock className="mr-1.5 size-3 shrink-0 text-ink-3 group-hover:hidden" />}
        {node.chapters && <span className="pr-3 text-xs text-ink-3 tabular-nums group-hover:hidden">{node.chapters} 章</span>}
        {child && (
          <button type="button" onClick={() => onAdd(node.id)} title={`在下面加${ONE[child]}`} aria-label={`在下面加${ONE[child]}`}
            className="mr-1.5 hidden rounded p-1 text-ink-3 hover:bg-line/70 hover:text-ink group-hover:block">
            <Plus className="size-3.5" />
          </button>
        )}
      </div>
      {expandable && expanded && node.children!.map((c) => (
        <OutlineTreeView key={c.id} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} open={open} toggle={toggle} onAdd={onAdd} />
      ))}
    </div>
  )
}

/* ---------------- 中间一页纸 ---------------- */

function Sheet({ children, narrow }: { children: ReactNode; narrow?: boolean }) {
  return (
    // 不再是一张浮在背景上的卡片：整块中间区域就是纸，字在里面居中
    <article className={clsx('mx-auto w-full px-12 pt-12 pb-24 2xl:px-16 2xl:pt-16', narrow ? 'max-w-[860px] 2xl:max-w-[920px]' : 'max-w-[1080px] 2xl:max-w-[1180px]')}>
      {children}
    </article>
  )
}

function Crumb({ items }: { items: string[] }) {
  return <p className="mb-4 text-[13px] tracking-wider text-ink-3">{items.join('  /  ')}</p>
}

function Title({ children, placeholder, autoFocus }: { children?: ReactNode; placeholder?: string; autoFocus?: boolean }) {
  return <Editable autoFocus={autoFocus} placeholder={placeholder} className="font-serif text-[34px] leading-tight font-bold break-all 2xl:text-[38px]">{children}</Editable>
}

function Tags({ entry }: { entry: VEntry }) {
  return (
    <>
      {entry.tags.map((tag) => <span key={tag} className="rounded-full bg-seal-soft px-2.5 py-0.5 text-xs text-seal">{tag}</span>)}
      {entry.locked && <span className="flex items-center gap-1 rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2"><Lock className="size-3" />锁住，AI 不改</span>}
    </>
  )
}

function Body({ children, side }: { children: ReactNode; side: ReactNode }) {
  return (
    <div className="mt-10 grid gap-x-12 gap-y-10 border-t border-line pt-9 lg:grid-cols-[minmax(0,1fr)_17rem] 2xl:grid-cols-[minmax(0,1fr)_19rem]">
      <div className="min-w-0 space-y-8">{children}</div>
      <aside className="min-w-0 space-y-8">{side}</aside>
    </div>
  )
}

/** 角色卡、金手指：一栏一栏的正文＋右边资料卡。 */
function CardEntryPage({ book, entry, nav, fresh }: { book: VBook; entry: VEntry; nav: Nav; fresh: boolean }) {
  const secret = entry.secret ? findEntry(book, entry.secret) : undefined
  const goldfinger = entry.goldfinger ? findEntry(book, entry.goldfinger) : undefined
  const holder = entry.holder ? findEntry(book, entry.holder) : undefined
  const secretChip = secret && <div className="mt-2"><LinkChip icon={<Lock className="size-3" />} onClick={() => nav.openEntry(secret.id)}>另有秘密：{secret.name}</LinkChip></div>
  return (
    <Sheet>
      <Crumb items={['设定', entry.category]} />
      <div className="flex flex-wrap items-center gap-3">
        <Title autoFocus={fresh} placeholder="起个名字">{entry.name}</Title>
        <Tags entry={entry} />
      </div>
      <Editable placeholder="一句话说清这是谁、这是什么" className="mt-3 font-serif text-lg leading-relaxed text-ink-2 2xl:text-xl">{entry.oneLine}</Editable>
      <Body
        side={
          <>
            <FactRows rows={entry.facts} />
            {holder && <Side title="谁在用"><LinkChip onClick={() => nav.openEntry(holder.id)}>{holder.name}</LinkChip></Side>}
            {entry.now && <Side title="此刻" note="设定师每写完一章更新"><FactRows rows={entry.now} /></Side>}
            {entry.kind === 'character' && (
              <Side title="关系">
                {entry.relations?.length ? (
                  <div className="space-y-1">
                    {entry.relations.map((rel) => (
                      <button key={rel.to + rel.kind} type="button" onClick={() => nav.openEntry(rel.to)} className="block w-full rounded-lg px-2 py-2 text-left transition-colors hover:bg-subtle" title={rel.text}>
                        <span className="flex items-center gap-2">
                          <span className="truncate font-serif text-[15px] font-bold text-ink">{findEntry(book, rel.to)?.name}</span>
                          <span className="shrink-0 rounded-full bg-line/70 px-2 py-px text-[11px] text-ink-2">{rel.kind}</span>
                        </span>
                        <span className="mt-0.5 line-clamp-2 text-[13px] leading-relaxed text-ink-3">{rel.text}</span>
                      </button>
                    ))}
                  </div>
                ) : <p className="px-2 text-[13px] text-ink-3">还没写。</p>}
                <button type="button" className="mt-1 flex items-center gap-1 px-2 text-[13px] text-ink-3 hover:text-ink"><Plus className="size-3.5" />加一个关系</button>
              </Side>
            )}
            <Side title="出现在"><Appears items={entry.appears} nav={nav} /></Side>
          </>
        }
      >
        {entry.sections.map((field) => (
          <Section key={field.label} field={field}>
            {(field.label === '身世' || field.label === '来历') && secretChip}
            {field.label === '能力' && goldfinger && <div className="mt-2"><LinkChip icon={<Sparkles className="size-3" />} onClick={() => nav.openEntry(goldfinger.id)}>金手指：{goldfinger.name}</LinkChip></div>}
          </Section>
        ))}
      </Body>
    </Sheet>
  )
}

/** 段落类和阶梯：一个名字加一段话（或一级一级），一栏到底。 */
function PlainEntryPage({ book, entry, category, nav, fresh }: { book: VBook; entry: VEntry; category?: VCategory; nav: Nav; fresh: boolean }) {
  const parent = entry.parent ? findEntry(book, entry.parent) : undefined
  const example = category?.example
  return (
    <Sheet narrow>
      <Crumb items={['设定', entry.category]} />
      <div className="flex flex-wrap items-center gap-3">
        <Title autoFocus={fresh} placeholder={example ? `起个名字，比如「${example.name}」` : '起个名字'}>{entry.name}</Title>
        <Tags entry={entry} />
      </div>
      {(parent || entry.knownBy) && (
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink-3">
          {parent && <span className="flex items-center gap-2">属于 <LinkChip onClick={() => nav.openEntry(parent.id)}>{parent.name}</LinkChip></span>}
          {entry.knownBy && <span className="flex items-center gap-1.5"><Lock className="size-3" />谁知道：{entry.knownBy}</span>}
        </div>
      )}
      <div className="mt-8 space-y-8 border-t border-line pt-8">
        {entry.kind === 'ladder' ? (
          <>
            <Prose text={entry.overview ?? ''} placeholder="总的说一句：怎么往上升、越级多难、有什么代价" />
            <ol>
              {(entry.levels ?? []).map((level, i, levels) => (
                <li key={level.name + i} className="relative flex gap-5 pb-7 last:pb-0">
                  {i < levels.length - 1 && <span className="absolute top-9 bottom-1 left-[17px] w-px bg-line-2" />}
                  <span className="relative flex size-9 shrink-0 items-center justify-center rounded-full border border-line-2 bg-card font-serif text-[15px] text-ink-2">{i + 1}</span>
                  <div className="min-w-0 flex-1 pt-1">
                    <Editable placeholder="这一级叫什么" className="font-serif text-lg font-bold">{level.name}</Editable>
                    <Editable placeholder="这一级能做到什么，先空着也行" className="mt-1 font-serif text-[17px] leading-[1.9] text-ink-2">{level.text}</Editable>
                  </div>
                </li>
              ))}
            </ol>
            <button type="button" className="ml-14 flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink"><Plus className="size-3.5" />加一级</button>
          </>
        ) : entry.sections.length ? (
          entry.sections.map((field) => <Section key={field.label} field={field} />)
        ) : (
          <Prose text={entry.body ?? ''} autoFocus={false} placeholder={example ? `比如：\n${example.text}` : '写这一条的内容，可以一条条列'} />
        )}
      </div>
      {entry.appears.length > 0 && (
        <div className="mt-10 flex flex-wrap items-center gap-2 border-t border-line pt-5 text-[13px] text-ink-3">
          <span className="mr-1">出现在</span>
          {entry.appears.map((a) => <LinkChip key={a.node} icon={<BookOpen className="size-3" />} onClick={() => nav.openNode(a.node)}>{a.label}</LinkChip>)}
        </div>
      )}
    </Sheet>
  )
}

function WorldPage({ book }: { book: VBook }) {
  return (
    <Sheet narrow>
      <Crumb items={['设定']} />
      <h1 className="font-serif text-[34px] font-bold 2xl:text-[38px]">世界概况</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-3">整个世界一段话说清：什么时代、超凡的力量公开还是藏着、钱用什么、普通人过得怎么样。一本书只有这一篇。</p>
      <div className="mt-8 border-t border-line pt-8">
        <Prose text={book.world} placeholder={'比如：\n九天大陆，以武为尊，宗门、世家、王朝并立。钱用灵石，灵石也是修炼资源。凡人活不过百岁，武者靠境界续命。'} />
      </div>
    </Sheet>
  )
}

/** 让编辑部写几条：先说想要什么，写出来的每一条和自己写的一样，是「名字＋一段话」，挑着收下。 */
function AskPanel({ category, onAccept, onClose }: { category: VCategory; onAccept: (items: { name: string; text: string }[]) => void; onClose: () => void }) {
  const [want, setWant] = useState('')
  const [state, setState] = useState<'ask' | 'writing' | 'done'>('ask')
  const [results, setResults] = useState<{ name: string; text: string; taken?: boolean; dropped?: boolean }[]>([])
  const write = () => {
    setState('writing')
    setTimeout(() => {
      setResults(fakeResults(category, want))
      setState('done')
    }, 1200)
  }
  const left = results.filter((r) => !r.taken && !r.dropped)
  return (
    <div className="rounded-2xl border border-line bg-subtle p-5">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-full bg-chief font-serif text-xs text-on-role">编</span>
        <p className="text-[15px] text-ink">想让编辑部在「{category.name}」里写点什么？</p>
        <button type="button" onClick={onClose} className="ml-auto text-[13px] text-ink-3 hover:text-ink">收起</button>
      </div>
      {state !== 'done' && (
        <>
          <textarea value={want} onChange={(e) => setWant(e.target.value)} rows={2} disabled={state === 'writing'}
            placeholder="说说你想要什么，比如：写三条跟寿命有关的规矩，要有代价。不写也行，编辑部按简介和已有的设定来。"
            className="w-full resize-none rounded-xl border border-line-2 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
          <div className="mt-3 flex items-center justify-between gap-4">
            <p className="text-xs text-ink-3">写出来的每一条都是「名字＋一段话」，跟你自己写的一样，你挑着收下。</p>
            <button type="button" onClick={write} disabled={state === 'writing'}
              className="h-9 shrink-0 rounded-lg bg-ink px-5 text-sm text-paper-2 transition-colors hover:bg-ink-2 disabled:opacity-60">
              {state === 'writing' ? '编辑部在写…' : '写'}
            </button>
          </div>
        </>
      )}
      {state === 'done' && (
        <div className="space-y-3">
          {results.map((r, i) => (
            <div key={r.name + i} className={clsx('rounded-xl border bg-card px-5 py-4 transition-opacity', r.dropped ? 'opacity-40' : 'border-line')}>
              <p className="font-serif text-[17px] font-bold text-ink">{r.name}</p>
              <p className="mt-1.5 font-serif text-[15px] leading-[1.9] whitespace-pre-line text-ink-2">{r.text}</p>
              <div className="mt-3 flex gap-2 text-[13px]">
                {r.taken ? <span className="text-lore">已收下</span> : r.dropped ? <span className="text-ink-3">不要了</span> : (
                  <>
                    <button type="button" onClick={() => { onAccept([r]); setResults(results.map((x, j) => (j === i ? { ...x, taken: true } : x))) }}
                      className="rounded-md bg-ink px-3 py-1 text-paper-2 hover:bg-ink-2">收下</button>
                    <button type="button" onClick={() => setResults(results.map((x, j) => (j === i ? { ...x, dropped: true } : x)))}
                      className="rounded-md px-3 py-1 text-ink-2 hover:bg-subtle">不要</button>
                  </>
                )}
              </div>
            </div>
          ))}
          <div className="flex items-center gap-3">
            {left.length > 1 && (
              <button type="button" onClick={() => { onAccept(left); setResults(results.map((x) => (x.taken || x.dropped ? x : { ...x, taken: true }))) }}
                className="h-9 rounded-lg border border-line-2 bg-card px-4 text-sm text-ink hover:border-ink-3/50">剩下的全部收下</button>
            )}
            <button type="button" onClick={() => { setState('ask'); setResults([]) }} className="text-[13px] text-ink-3 hover:text-ink">都不满意，再写一批</button>
          </div>
        </div>
      )}
    </div>
  )
}

/** 原型里编辑部写出来的假内容。 */
function fakeResults(category: VCategory, want: string): { name: string; text: string }[] {
  if (category.name === '特殊规则') {
    return [
      { name: '借寿契', text: '1. 寿命只能借，不能送：借出去的寿命，三年后连本带利收回\n2. 借寿要双方立契，契纸烧掉就作废\n3. 借来的寿命会让人越来越像出借的人' },
      { name: '宗门门规', text: '1. 外门弟子不得私入后山\n2. 每月初一必须到传功堂领丹，不领视同叛宗\n3. 杂役不得修炼宗门功法' },
      { name: '“下山”', text: '考核不过的外门弟子会被“送下山”。名义上是遣返回家，实际没有一个人回到过山下。' },
    ]
  }
  const base = category.example?.name ?? category.name
  return [1, 2].map((i) => ({ name: `${base}（候选${cn(i)}）`, text: `原型里的假内容。真用时，编辑部会按你说的「${want || '按简介补'}」，照简介和已有设定写一条「${category.name}」。` }))
}

function CategoryPage({ category, nav, onNewEntry, onAccept }: { category: VCategory; nav: Nav; onNewEntry: () => void; onAccept: (items: { name: string; text: string }[]) => void }) {
  const [asking, setAsking] = useState(false)
  return (
    <Sheet narrow>
      <Crumb items={['设定']} />
      <h1 className="font-serif text-[34px] font-bold 2xl:text-[38px]">{category.name}</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-3">{category.about}</p>

      {category.entries.length > 0 && (
        <div className="mt-8 divide-y divide-line border-y border-line">
          {category.entries.map((entry) => (
            <button key={entry.id} type="button" onClick={() => nav.openEntry(entry.id)} className="group flex w-full items-baseline gap-5 py-4 text-left">
              <span className="w-40 shrink-0 truncate font-serif text-[17px] font-bold text-ink group-hover:text-seal">{entry.name || '未命名'}</span>
              <span className="line-clamp-1 flex-1 text-[15px] text-ink-2">{(entry.oneLine || entry.body || entry.overview || '').split('\n')[0] || <span className="text-ink-3">还没写</span>}</span>
            </button>
          ))}
        </div>
      )}

      {!category.entries.length && category.example && (
        <div className="mt-8 rounded-xl border border-dashed border-line-2 px-6 py-5">
          <p className="mb-2 text-xs tracking-wider text-ink-3">比如这样写一条</p>
          <p className="font-serif text-[17px] font-bold text-ink-2">{category.example.name}</p>
          <p className="mt-1.5 font-serif text-[15px] leading-[1.9] whitespace-pre-line text-ink-3">{category.example.text}</p>
        </div>
      )}

      <div className="mt-8 flex flex-wrap gap-3">
        <button type="button" onClick={onNewEntry} className="flex h-10 items-center gap-1.5 rounded-lg border border-line-2 bg-card px-5 text-sm text-ink transition-colors hover:border-ink-3/50">
          <Plus className="size-4" />自己写一条
        </button>
        {!asking && <AskButton onClick={() => setAsking(true)}>让编辑部写几条</AskButton>}
      </div>
      {asking && <div className="mt-5"><AskPanel category={category} onAccept={onAccept} onClose={() => setAsking(false)} /></div>}
    </Sheet>
  )
}

/** 设定总览：空书点完「下一步」先看到这里；有内容的书点目录上的「设定」也到这里。 */
function SettingsOverview({ book, nav, onSelect }: { book: VBook; nav: Nav; onSelect: (id: string) => void }) {
  const total = book.categories.reduce((sum, c) => sum + c.entries.length, 0)
  const first = ['角色列表', '金手指']
  return (
    <Sheet>
      <Crumb items={['设定']} />
      <h1 className="font-serif text-[34px] font-bold 2xl:text-[38px]">设定</h1>
      <p className="mt-3 max-w-2xl font-serif text-lg leading-relaxed text-ink-2">
        {total
          ? `已经写了 ${total} 条。点一类进去看，或者在左边目录里直接挑。`
          : '这本书的设定还空着。不用一次写全，先写最要紧的两样：主角和金手指；其余的写到哪补到哪。'}
      </p>
      {!total && (
        <div className="mt-8 flex flex-wrap items-center gap-5 rounded-2xl bg-subtle px-6 py-5">
          <div className="min-w-0 flex-1">
            <p className="text-[15px] text-ink">想省事，可以让编辑部按简介先补一版。</p>
            <p className="mt-1 text-[13px] leading-relaxed text-ink-3">它先写主角和金手指，再补其余的。写完你随便改，你自己写过的它不会动。</p>
          </div>
          <AskButton onClick={() => nav.toast('原型：点了以后编辑部开始写，写好的一条条出现在左边目录里')}>让编辑部补一版</AskButton>
        </div>
      )}
      <div className="mt-8 grid gap-3 md:grid-cols-2">
        {book.categories.map((cat) => (
          <button key={cat.name} type="button" onClick={() => onSelect(cat.entries[0]?.id ?? `cat:${cat.name}`)}
            className="group rounded-xl border border-line bg-card/70 px-5 py-4 text-left transition-colors hover:border-line-2 hover:bg-card">
            <span className="flex items-center gap-2">
              <span className="font-serif text-lg font-bold text-ink">{cat.name}</span>
              {cat.entries.length > 0 && <span className="text-xs text-ink-3 tabular-nums">{cat.entries.length} 条</span>}
              {!total && first.includes(cat.name) && <span className="rounded-full bg-seal-soft px-2 py-px text-[11px] text-seal">先写</span>}
            </span>
            <span className="mt-1 line-clamp-1 block text-[13px] text-ink-3">
              {cat.entries.length ? cat.entries.slice(0, 4).map((e) => e.name).join('、') : cat.about}
            </span>
          </button>
        ))}
      </div>
    </Sheet>
  )
}

/* ---------------- 大纲 ---------------- */

const NEXT_KIND: Partial<Record<VNode['kind'], VNode['kind']>> = { 全书: '篇', 篇: '卷', 卷: '单元', 单元: '章' }
/** 一篇、一卷、一个单元、一章 */
const ONE: Record<VNode['kind'], string> = { 全书: '全书', 篇: '一篇', 卷: '一卷', 单元: '一个单元', 章: '一章' }

/** 在这个节点下面加的是哪一层：已经有下一层就照着它，没有就按默认。 */
function childKind(node: VNode): VNode['kind'] | undefined {
  return node.children?.[0]?.kind ?? NEXT_KIND[node.kind]
}

const NODE_PLACEHOLDER: Record<VNode['kind'], string> = {
  全书: '结局往哪走，一句话',
  篇: '在哪个舞台；主角这一篇想做成什么；谁挡路；怎么收尾',
  卷: '这一卷想做成什么；卷首处境；卷末的高潮和结果',
  单元: '什么事找上门；主角怎么应对；读者叫好的那一下；做完拿到什么',
  章: '发生什么；看点；结尾的钩子',
}

const KIND_NOTE: Partial<Record<VNode['kind'], string>> = {
  单元: '一个单元是一个完整的小故事，几章到十几章，给读者一次爽点。',
}

function OutlinePage({ book, outline, id, nav, onAdd }: { book: VBook; outline: VNode; id: string; nav: Nav; onAdd: (id: string) => void }) {
  const path = findNode(outline, id) ?? [outline]
  const node = path[path.length - 1]
  const child = childKind(node)
  const rows: [string, string][] = []
  if (node.range) rows.push(['章数', `${node.range[1] - node.range[0] + 1} 章 · 第 ${node.range[0]}–${node.range[1]} 章`])
  else if (node.chapters) rows.push(['章数', `${node.chapters} 章`])
  if (node.progress && node.progress !== '已规划') rows.push(['写到', node.progress])
  return (
    <Sheet>
      <div className="flex items-start justify-between gap-6">
        <Crumb items={['大纲', ...path.slice(0, -1).map((n) => n.title)]} />
        {node.locked && <span className="flex shrink-0 items-center gap-1 rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2"><Lock className="size-3" />锁住，AI 规划时不改</span>}
      </div>
      <div className="flex flex-wrap items-baseline gap-3">
        <Title placeholder={`给${ONE[node.kind]}起个名字`}>{node.title}</Title>
        {node.later && <span className="rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2">写到再定</span>}
      </div>
      <Body
        side={
          <>
            {rows.length > 0 && <FactRows rows={rows} />}
            <Side title="用到的设定">
              {node.uses.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {node.uses.map((entryId) => {
                    const entry = findEntry(book, entryId)
                    return entry && (
                      <button key={entryId} type="button" onClick={() => nav.openEntry(entryId)}
                        className="max-w-full truncate rounded-full border border-line bg-card px-3 py-1 font-serif text-[14px] text-ink-2 transition-colors hover:border-line-2 hover:text-ink">
                        {entry.name}
                      </button>
                    )
                  })}
                </div>
              ) : <p className="text-[13px] text-ink-3">文字里提到设定里的人和地方，会自动挂上。</p>}
            </Side>
          </>
        }
      >
        {node.sections
          ? node.sections.map((field) => <Section key={field.label} field={field} />)
          : <Section field={{ label: node.kind === '全书' ? '结局' : '一段话', text: node.text, placeholder: NODE_PLACEHOLDER[node.kind] }} />}
        {child && (
          <section>
            <h3 className="mb-1 text-[13px] tracking-[0.15em] text-ink-3">下面的{child}{node.children?.length ? ` · ${node.children.length} 个` : ''}</h3>
            {KIND_NOTE[child] && <p className="mb-2 text-xs text-ink-3">{KIND_NOTE[child]}</p>}
            {!!node.children?.length && (
              <div className="divide-y divide-line border-y border-line">
                {node.children.map((c) => (
                  <button key={c.id} type="button" onClick={() => nav.openNode(c.id)} className="group flex w-full items-baseline gap-5 py-3.5 text-left">
                    <span className={clsx('w-52 shrink-0 truncate font-serif text-[16px] font-bold group-hover:text-seal', c.later ? 'text-ink-3' : 'text-ink')}>{c.title}</span>
                    <span className="line-clamp-1 flex-1 text-[14px] text-ink-3">{(c.text || c.sections?.[0]?.text || '').split('\n')[0] || '还没写'}</span>
                    {c.range && c.kind !== '章' && <span className="text-xs text-ink-3 tabular-nums">{c.range[1] - c.range[0] + 1} 章</span>}
                  </button>
                ))}
              </div>
            )}
            <div className="mt-4 flex flex-wrap gap-3">
              <button type="button" onClick={() => onAdd(node.id)} className="flex h-9 items-center gap-1.5 rounded-lg border border-line-2 bg-card px-4 text-sm text-ink transition-colors hover:border-ink-3/50">
                <Plus className="size-4" />自己加{ONE[child]}
              </button>
              <AskButton onClick={() => nav.toast(`原型：编辑部会按上面这段话和设定，拆出几个${child}给你挑`)}>让编辑部拆{child}</AskButton>
            </div>
          </section>
        )}
      </Body>
    </Sheet>
  )
}

function BlurbPage({ book }: { book: VBook }) {
  const chapters = book.length ? Math.round((book.length * 10000) / book.chapterWords) : null
  const facts = [book.genre, ...book.tags].filter(Boolean).join(' · ')
  return (
    <div className="flex min-h-full items-center justify-center px-6 py-10">
      <div className="grid w-full max-w-[1000px] rounded-2xl border border-line bg-card shadow-[var(--shadow-lift)] md:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="hidden flex-col items-center justify-center rounded-l-2xl border-r border-line bg-paper-2 px-8 py-12 md:flex">
          <BookCover title={book.title} seed={book.id === 'sample' ? '开新书' : book.id} size="lg" className="shadow-[0_22px_34px_-18px_rgb(40_25_10/0.55)]" />
          <p className="mt-7 max-w-full truncate font-serif text-xl font-bold">{book.title}</p>
          <p className="mt-1.5 text-center text-[13px] text-ink-3">{facts || '还没分类'}</p>
          {chapters && <p className="mt-0.5 text-[13px] text-ink-3">{book.length} 万字 · 约 {chapters} 章</p>}
        </aside>
        <div className="px-12 py-10">
          <Editable className="font-serif text-[34px] font-bold">{book.title}</Editable>
          <p className="mt-7 mb-2.5 text-sm text-ink-3">简介</p>
          <Editable multiline boxed placeholder="写给读者看的那段话" className="rounded-xl bg-paper/45 px-5 py-4 font-serif text-[17px] leading-[1.95]">{book.blurb}</Editable>
          <div className="mt-5 divide-y divide-line border-y border-line text-sm">
            {[
              ['类别', [book.channel, book.genre].filter(Boolean).join(' · ')],
              ['标签', book.tags.join('、')],
              ['篇幅', book.length ? `${book.length} 万字 · 约 ${chapters} 章` : ''],
            ].map(([label, value]) => (
              <div key={label} className="grid grid-cols-[64px_minmax(0,1fr)] gap-4 py-3.5">
                <span className="text-ink-3">{label}</span>
                <span className={value ? 'text-ink' : 'text-ink-3'}>{value || '还没填'}</span>
              </div>
            ))}
          </div>
          <p className="mt-5 text-[13px] text-ink-3">点哪改哪，改了就存。</p>
        </div>
      </div>
    </div>
  )
}

/* ---------------- 编辑部 ---------------- */

function ChatBody() {
  return (
    <>
      <div className="scroll-thin min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {CHAT.map((msg, i) =>
          msg.who === '作者' ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-md bg-author-bubble px-3.5 py-2 text-[14px] leading-relaxed text-ink">{msg.text}</p>
            </div>
          ) : (
            <div key={i} className="flex gap-2.5">
              <span className={clsx('flex size-7 shrink-0 items-center justify-center rounded-full font-serif text-[13px]', ROLE_STYLE[msg.who])}>{msg.who[0]}</span>
              <div className="min-w-0">
                <p className="mb-1 text-xs text-ink-3">{msg.who}</p>
                <p className="rounded-2xl rounded-tl-md border border-line bg-card px-3.5 py-2 text-[14px] leading-relaxed text-ink">{msg.text}</p>
              </div>
            </div>
          ),
        )}
      </div>
      <div className="border-t border-line p-3">
        <div className="flex items-end gap-2 rounded-xl border border-line-2 bg-card px-3 py-2 focus-within:border-ink-3">
          <textarea rows={1} placeholder="跟编辑部说点什么" className="max-h-28 min-h-6 flex-1 resize-none bg-transparent text-[14px] leading-6 text-ink [field-sizing:content] placeholder:text-ink-3 focus:outline-none" />
          <button type="button" className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ink text-paper-2 hover:bg-ink-2" aria-label="发送"><ArrowUp className="size-4" /></button>
        </div>
      </div>
    </>
  )
}

function ChatHeader({ dock, setDock, onDragStart }: { dock: Dock; setDock: (dock: Dock) => void; onDragStart?: (e: ReactPointerEvent) => void }) {
  return (
    <div onPointerDown={onDragStart} className={clsx('flex h-12 shrink-0 items-center gap-2 border-b border-line px-3', onDragStart && 'cursor-grab active:cursor-grabbing')}>
      <div className="flex -space-x-1.5">
        {Object.keys(ROLE_STYLE).map((role) => (
          <span key={role} className={clsx('flex size-6 items-center justify-center rounded-full font-serif text-[11px] ring-2 ring-card', ROLE_STYLE[role])}>{role[0]}</span>
        ))}
      </div>
      <span className="text-[14px] font-medium">编辑部</span>
      <div className="ml-auto flex items-center gap-0.5">
        {dock === 'float' ? (
          <button type="button" onClick={() => setDock('side')} className="rounded-md p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" title="贴到右边" aria-label="贴到右边"><PanelRight className="size-4" /></button>
        ) : (
          <button type="button" onClick={() => setDock('float')} className="rounded-md p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" title="浮起来" aria-label="浮起来"><PictureInPicture2 className="size-4" /></button>
        )}
        <button type="button" onClick={() => setDock('ball')} className="rounded-md p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" title="收起" aria-label="收起"><Minus className="size-4" /></button>
      </div>
    </div>
  )
}

function FloatingEditorial({ setDock }: { setDock: (dock: Dock) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<{ dx: number; dy: number } | null>(null)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [nearEdge, setNearEdge] = useState(false)

  const start = (e: ReactPointerEvent) => {
    if ((e.target as Element).closest('button') || !ref.current) return
    const rect = ref.current.getBoundingClientRect()
    drag.current = { dx: e.clientX - rect.left, dy: e.clientY - rect.top }
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  }
  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (!drag.current || !ref.current) return
      const w = ref.current.offsetWidth
      const h = ref.current.offsetHeight
      setPos({
        x: Math.min(Math.max(8, e.clientX - drag.current.dx), window.innerWidth - w - 8),
        y: Math.min(Math.max(64, e.clientY - drag.current.dy), window.innerHeight - h - 8),
      })
      setNearEdge(e.clientX > window.innerWidth - 48)
    }
    const up = (e: PointerEvent) => {
      if (!drag.current) return
      drag.current = null
      setNearEdge(false)
      // 拖到右边缘松手，就贴成侧栏
      if (e.clientX > window.innerWidth - 48) setDock('side')
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [setDock])

  return (
    <>
      {nearEdge && <div className="pointer-events-none fixed top-14 right-0 bottom-0 z-30 w-[380px] border-l-2 border-chief/40 bg-chief-soft/40" />}
      <div ref={ref}
        className="fixed z-40 flex flex-col overflow-hidden rounded-2xl border border-line bg-paper shadow-[0_24px_60px_-20px_rgb(40_25_10/0.45),0_2px_6px_rgb(40_25_10/0.08)]"
        style={{ ...(pos ? { left: pos.x, top: pos.y } : { right: 24, bottom: 24 }), width: 380, height: 520, resize: 'both', minWidth: 320, minHeight: 360, maxWidth: 680, maxHeight: '85vh' }}>
        <ChatHeader dock="float" setDock={setDock} onDragStart={start} />
        <ChatBody />
      </div>
    </>
  )
}

/* ---------------- 选中文字后冒出的小按钮 ---------------- */

function SelectionActions({ pageRef, onToast }: { pageRef: React.RefObject<HTMLElement | null>; onToast: (text: string) => void }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null)
  useEffect(() => {
    const up = () => setTimeout(() => {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed || !sel.toString().trim() || !pageRef.current?.contains(sel.anchorNode)) return setAt(null)
      const rect = sel.getRangeAt(0).getBoundingClientRect()
      setAt({ x: rect.left + rect.width / 2, y: rect.top })
    }, 0)
    const hide = () => setAt(null)
    document.addEventListener('mouseup', up)
    const page = pageRef.current
    page?.addEventListener('scroll', hide)
    return () => {
      document.removeEventListener('mouseup', up)
      page?.removeEventListener('scroll', hide)
    }
  }, [pageRef])
  if (!at) return null
  return (
    <div className="fixed z-50 flex -translate-x-1/2 items-center gap-0.5 rounded-xl border border-line bg-card p-1 shadow-[var(--shadow-lift)]" style={{ left: at.x, top: at.y - 46 }}
      onMouseDown={(e) => e.preventDefault()}>
      <span className="ml-1 flex size-6 items-center justify-center rounded-full bg-chief font-serif text-[11px] text-on-role">编</span>
      {['改这一句', '给我几个写法', '写细一点'].map((label) => (
        <button key={label} type="button" onClick={() => { setAt(null); onToast(`原型：「${label}」会让编辑部只改你选中的这几个字，改好在原地给你挑`) }}
          className="rounded-lg px-2.5 py-1 text-[13px] text-ink-2 transition-colors hover:bg-subtle hover:text-ink">
          {label}
        </button>
      ))}
    </div>
  )
}

/* ---------------- 整页 ---------------- */

function firstSelection(book: VBook): string {
  const characters = book.categories.find((c) => c.name === '角色列表')?.entries ?? []
  const lead = characters.find((c) => c.role === '主角') ?? characters[0]
  return lead?.id ?? (book.categories.find((c) => c.entries.length)?.entries[0]?.id ?? 'overview')
}

/** 自建类别一句话说清每条写什么。 */
function customAbout(style: CategoryStyle, fields: string[]): string {
  if (style === 'card') return fields.length ? `每条有这几栏：${fields.join('、')}。` : '每条有哪几栏，自己定。'
  if (style === 'ladder') return '一级一级往上排，每级一个名称加一段介绍。'
  return '一个名字加一段话。'
}

let nextId = 1

/** 在某一类里新建一条空的：照这一类的样子。 */
function blankEntry(category: VCategory): VEntry {
  const id = `new-${nextId++}`
  const base = { id, category: category.name, name: '', oneLine: '', tags: [], locked: false, facts: [] as VEntry['facts'], sections: [] as VField[], appears: [] }
  if (category.name === '角色列表') {
    const labels = ['外貌', '性格与说话方式', '身世', '想要什么', '能力', '和主角的关系', '备注']
    return { ...base, kind: 'character', role: '配角', facts: [['别名', ''], ['定位', '配角'], ['性别', ''], ['年龄', '']], sections: labels.map((label) => ({ label, text: '', placeholder: CHARACTER_PLACEHOLDERS[label] })) }
  }
  if (category.name === '金手指') {
    return {
      ...base, kind: 'goldfinger', facts: [['是什么', '', GOLDFINGER_PLACEHOLDERS.是什么], ['谁知道', '', GOLDFINGER_PLACEHOLDERS.谁知道]],
      sections: ['能做什么', '规矩和限制', '代价', '怎么变强', '来历'].map((label) => ({ label, text: '', placeholder: GOLDFINGER_PLACEHOLDERS[label] })),
    }
  }
  if (category.name === '等级体系' || category.custom?.style === 'ladder') return { ...base, kind: 'ladder', overview: '', levels: [{ name: '', text: '' }, { name: '', text: '' }] }
  if (category.custom?.style === 'card') return { ...base, kind: 'paragraph', sections: category.custom.fields.map((label) => ({ label, text: '' })) }
  return { ...base, kind: 'paragraph', body: '' }
}

/** 在节点下面加一个下一层，返回新的大纲树和新节点 id。 */
function addOutlineChild(root: VNode, parentId: string): { root: VNode; id: string } | null {
  const copy: VNode = structuredClone(root)
  const parent = findNode(copy, parentId)?.at(-1)
  const kind = parent && childKind(parent)
  if (!parent || !kind) return null
  const siblings = parent.children ?? []
  const all = (k: VNode['kind']) => {
    let n = 0
    const walk = (x: VNode) => { if (x.kind === k) n++; x.children?.forEach(walk) }
    walk(copy)
    return n
  }
  const title = kind === '篇' ? `第${cn(siblings.length + 1)}篇　` : kind === '卷' ? `第${cn(all('卷') + 1)}卷　` : kind === '单元' ? `单元${cn(siblings.length + 1)}　` : '新的一章'
  const id = `added-${nextId++}`
  parent.children = [...siblings, { id, kind, title, text: '', uses: [], ...(kind === '章' ? { sections: [{ label: '发生什么', text: '' }, { label: '看点', text: '' }, { label: '结尾钩子', text: '' }] } : {}) }]
  numberChapters(copy)
  return { root: copy, id }
}

function Workspace({ book: base, switcher }: { book: VBook; switcher: ReactNode }) {
  // 原型里新建的类别、条目、大纲节点只放在这一页，不存
  const [customCats, setCustomCats] = useState<VCategory[]>([])
  const [added, setAdded] = useState<Record<string, VEntry[]>>({})
  const [outline, setOutline] = useState(base.outline)
  const book = useMemo(() => ({
    ...base,
    categories: [...base.categories, ...customCats].map((c) => ({ ...c, entries: [...c.entries, ...(added[c.name] ?? [])] })),
  }), [base, customCats, added])
  const [tab, setTab] = useState<Tab>('设定')
  const [entry, setEntry] = useState(() => (base.categories.some((c) => c.entries.length) ? firstSelection(base) : 'overview'))
  const [fresh, setFresh] = useState('')
  const firstChild = base.outline.children?.[0]
  const [node, setNode] = useState(firstChild?.children?.[0]?.id ?? firstChild?.id ?? 'book')
  const [open, setOpen] = useState(() => {
    const path = findNode(base.outline, firstChild?.children?.[0]?.id ?? 'book') ?? []
    return ['book', ...path.map((n) => n.id)]
  })
  const [dock, setDock] = useState<Dock>('ball')
  const [toast, setToast] = useState('')
  const pageRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 3200)
    return () => clearTimeout(timer)
  }, [toast])

  const nav: Nav = {
    openEntry: (id) => {
      setTab('设定')
      setEntry(id)
      setFresh('')
      pageRef.current?.scrollTo({ top: 0 })
    },
    openNode: (id) => {
      setTab('大纲')
      setNode(id)
      const path = findNode(outline, id)
      if (path) setOpen((list) => [...new Set([...list, ...path.slice(0, -1).map((n) => n.id)])])
      pageRef.current?.scrollTo({ top: 0 })
    },
    toast: setToast,
  }

  const categoryName = entry.startsWith('cat:') ? entry.slice(4) : ''
  const category = categoryName ? book.categories.find((c) => c.name === categoryName) ?? emptyCategory(categoryName) : undefined
  const current = entry !== 'overview' && entry !== 'world' && !categoryName ? findEntry(book, entry) : undefined
  const currentCategory = current && book.categories.find((c) => c.name === current.category)

  const newEntry = (name: string) => {
    const cat = book.categories.find((c) => c.name === name)
    if (!cat) return
    const blank = blankEntry(cat)
    setAdded({ ...added, [name]: [...(added[name] ?? []), blank] })
    nav.openEntry(blank.id)
    setFresh(blank.id)
  }
  const accept = (name: string, items: { name: string; text: string }[]) => {
    const made = items.map((item): VEntry => ({ ...blankEntry(book.categories.find((c) => c.name === name) ?? emptyCategory(name)), name: item.name, body: item.text }))
    setAdded((prev) => ({ ...prev, [name]: [...(prev[name] ?? []), ...made] }))
  }
  const addNode = (parentId: string) => {
    const result = addOutlineChild(outline, parentId)
    if (!result) return
    setOutline(result.root)
    setOpen((list) => [...new Set([...list, parentId])])
    setNode(result.id)
    setTab('大纲')
  }
  const selectedNode = findNode(outline, node)?.at(-1)
  const outlineAdd = [
    { label: `新建${ONE[childKind(outline) ?? '篇']}`, onClick: () => addNode('book') },
    ...(selectedNode && selectedNode.id !== 'book' && childKind(selectedNode) ? [{ label: `在「${selectedNode.title.trim()}」下面加${ONE[childKind(selectedNode)!]}`, onClick: () => addNode(selectedNode.id) }] : []),
  ]

  return (
    <div className="flex h-dvh flex-col bg-paper text-ink">
      <TopBar book={book} tab={tab} onTab={setTab} switcher={switcher} />
      <div className="flex min-h-0 flex-1">
        {tab === '设定' && (
          <SettingsDirectory book={book} selected={entry} onSelect={nav.openEntry} onNewEntry={newEntry}
            onCreateCategory={(name, style, fields) => {
              setCustomCats([...customCats, { name, about: customAbout(style, fields), entries: [], custom: { style, fields } }])
              nav.openEntry(`cat:${name}`)
            }} />
        )}
        {tab === '大纲' && (
          <DirectoryShell title="大纲" search="找篇、卷、单元、章……" addMenu={outlineAdd}>
            <OutlineTreeView node={outline} depth={0} selected={node} onSelect={nav.openNode} open={open} onAdd={addNode}
              toggle={(id) => setOpen(open.includes(id) ? open.filter((x) => x !== id) : [...open, id])} />
          </DirectoryShell>
        )}
        <main ref={pageRef} className={clsx('scroll-thin min-w-0 flex-1 overflow-y-auto', tab === '简介' ? 'bg-paper' : 'bg-manuscript')}>
          {tab === '简介' && <BlurbPage book={book} />}
          {tab === '设定' && (
            current ? (current.kind === 'character' || current.kind === 'goldfinger'
              ? <CardEntryPage key={current.id} book={book} entry={current} nav={nav} fresh={fresh === current.id} />
              : <PlainEntryPage key={current.id} book={book} entry={current} category={currentCategory} nav={nav} fresh={fresh === current.id} />)
              : entry === 'world' ? <WorldPage book={book} />
                : category ? <CategoryPage key={category.name} category={category} nav={nav} onNewEntry={() => newEntry(category.name)} onAccept={(items) => accept(category.name, items)} />
                  : <SettingsOverview book={book} nav={nav} onSelect={nav.openEntry} />
          )}
          {tab === '大纲' && <OutlinePage key={node} book={book} outline={outline} id={node} nav={nav} onAdd={addNode} />}
        </main>
        {dock === 'side' && (
          <aside className="flex w-[380px] shrink-0 flex-col border-l border-line bg-paper">
            <ChatHeader dock="side" setDock={setDock} />
            <ChatBody />
          </aside>
        )}
      </div>

      {dock === 'float' && <FloatingEditorial setDock={setDock} />}
      {dock === 'ball' && (
        <button type="button" onClick={() => setDock('float')} title="编辑部"
          className="press fixed right-6 bottom-6 z-40 flex size-14 items-center justify-center rounded-full bg-chief font-serif text-xl text-on-role shadow-[0_14px_30px_-10px_rgb(40_50_90/0.6)] transition-transform hover:-translate-y-0.5">
          编
          <span className="absolute top-1 right-1 size-3 rounded-full bg-seal ring-2 ring-paper" />
        </button>
      )}

      <SelectionActions pageRef={pageRef} onToast={setToast} />
      {toast && (
        <div className="fixed bottom-8 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-full bg-ink px-5 py-2.5 text-[13px] text-paper-2 shadow-[var(--shadow-lift)]">
          <Wand2 className="size-3.5" />{toast}
        </div>
      )}
    </div>
  )
}

export function WorkspacePrototype() {
  const [params, setParams] = useSearchParams()
  const source = params.get('book') ?? 'sample'
  const { book, loading, error } = useBookSource(source)
  const choose = (next: string) => setParams(next === 'sample' ? {} : { book: next })
  if (book) return <Workspace key={source} book={book} switcher={<BookSwitcher inline source={source} onSource={choose} />} />
  return (
    <>
      <div className="flex h-dvh items-center justify-center bg-paper text-[15px] text-ink-3">
        {loading ? '正在读这本书…' : `这本书没读出来：${error ?? ''}`}
      </div>
      <BookSwitcher source={source} onSource={choose} />
    </>
  )
}
