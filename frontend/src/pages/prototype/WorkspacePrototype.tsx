import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, ArrowUp, BookOpen, ChevronDown, ChevronRight, ChevronUp, Inbox, Library, Lock, Minus, PanelRight, PictureInPicture2, Plus, Search, Settings, Sparkles, Wand2 } from 'lucide-react'
import { type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { get } from '../../api/client'
import type { LibrarySnapshot } from '../../api/library'
import type { BookSummary, ChapterBrief } from '../../api/types'
import { BookCover } from '../../components/BookCover'
import type { OutlineTree } from '../../lib/outlineTree'
import { type ApiParts, bookFromApi } from './fromApi'
import { CATEGORY_HINTS, ROLE_ORDER, findEntry, findNode, type VBook, type VCategory, type VEntry, type VField, type VNode } from './model'
import { CHAT, PENDING, SAMPLE_BOOK, emptyBook } from './sampleBook'

type Tab = '简介' | '设定' | '大纲'
type Dock = 'ball' | 'float' | 'side'

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
  { key: 'nishi', title: '逆世帝尊', note: '演示模型写的，世界与地图有 63 条' },
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

function BookSwitcher({ source, onSource }: { source: string; onSource: (source: string) => void }) {
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
    <div className="fixed bottom-4 left-4 z-30">
      {open && (
        <div className="scroll-thin absolute bottom-[calc(100%+8px)] left-0 max-h-[70vh] w-80 overflow-y-auto rounded-xl border border-line bg-card p-2 shadow-[var(--shadow-lift)]">
          {item('sample', '示例书 · 窥命长生', '我挑过的理想内容')}
          {item('empty', '刚开的空书', '点完「下一步」看到的样子（设成都市）')}
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
        <ChevronUp className={clsx('size-3.5 transition-transform', !open && 'rotate-180')} />
      </button>
    </div>
  )
}

/* ---------------- 小部件 ---------------- */

/** 可以直接改的字：点上去就是输入框，不用先点「编辑」；空着时显示该写什么。 */
function Editable({ children, className, multiline, boxed, placeholder }: { children?: ReactNode; className?: string; multiline?: boolean; boxed?: boolean; placeholder?: string }) {
  return (
    <div
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

/** 正文里的一段：小标题加可以直接改的字；太长先折起来。 */
function Section({ field, children }: { field: VField; children?: ReactNode }) {
  const long = field.text.length > LONG
  const [open, setOpen] = useState(false)
  return (
    <section>
      <h3 className="mb-2 text-[13px] tracking-[0.15em] text-ink-3">{field.label}</h3>
      <div className={clsx('relative', long && !open && 'max-h-[11.5em] overflow-hidden')}>
        <Editable multiline placeholder={field.placeholder ?? '还没写'} className="font-serif text-[17px] leading-[1.95] text-ink 2xl:text-lg">{field.text}</Editable>
        {long && !open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-manuscript to-transparent" />}
      </div>
      {long && (
        <button type="button" onClick={() => setOpen(!open)} className="mt-1 text-[13px] text-chief hover:underline">
          {open ? '收起' : `展开全文（${field.text.length} 字）`}
        </button>
      )}
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
      className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full bg-subtle px-3 py-1 text-[13px] text-ink-2 transition-colors hover:bg-line/60 hover:text-ink">
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

function HintList({ hints }: { hints: string[] }) {
  if (!hints.length) return null
  return (
    <ul className="space-y-2 rounded-xl bg-subtle px-4 py-3.5">
      {hints.map((hint) => (
        <li key={hint} className="flex gap-2 text-[13px] leading-relaxed text-ink-2">
          <span className="mt-[7px] size-1 shrink-0 rounded-full bg-ink-3" />
          {hint}
        </li>
      ))}
      <li className="pt-1 text-xs text-ink-3">用得上的写，用不上的不写。</li>
    </ul>
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

function TopBar({ book, tab, onTab }: { book: VBook; tab: Tab; onTab: (tab: Tab) => void }) {
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

      <nav className="ml-8 flex h-full items-stretch">
        {(['简介', '设定', '大纲'] as const).map((key) => (
          <button key={key} type="button" onClick={() => onTab(key)}
            className={clsx('relative px-4 text-[15px] transition-colors 2xl:px-5 2xl:text-base', tab === key ? 'font-medium text-ink' : 'text-ink-3 hover:text-ink')}>
            {key}
            {tab === key && <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-seal" />}
          </button>
        ))}
        <span className="flex cursor-not-allowed items-center px-4 text-[15px] text-ink-3/50 2xl:px-5 2xl:text-base" title="开写以后才有">正文</span>
      </nav>

      <div className="ml-auto flex items-center gap-1">
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

function DirectoryShell({ title, search, onTitle, children, footer }: { title: string; search: string; onTitle?: () => void; children: ReactNode; footer?: ReactNode }) {
  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-line bg-paper-2 2xl:w-80">
      <div className="flex items-center justify-between px-5 pt-5 pb-3">
        <button type="button" onClick={onTitle} className="text-xs tracking-[0.25em] text-ink-3 hover:text-ink">{title}</button>
        <button type="button" className="rounded-md p-1 text-ink-3 transition-colors hover:bg-line/60 hover:text-ink" aria-label="新建" title="新建">
          <Plus className="size-4" />
        </button>
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

function EntryButton({ entry, selected, depth = 0, onSelect }: { entry: VEntry; selected: string; depth?: number; onSelect: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onSelect(entry.id)} title={entry.name}
      style={{ paddingLeft: 10 + depth * 14 }}
      className={clsx('flex w-full items-center gap-2 rounded-md py-[7px] pr-2.5 text-left font-serif text-[15px] transition-colors 2xl:text-base',
        selected === entry.id ? 'bg-card font-bold text-ink shadow-[0_1px_2px_rgb(60_40_20/0.08)]' : 'text-ink-2 hover:bg-line/40 hover:text-ink')}>
      {depth > 0 && <span className="text-ink-3/60">└</span>}
      <span className="truncate">{entry.name}</span>
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

function SettingsDirectory({ book, selected, onSelect, unfolded, onUnfold }: { book: VBook; selected: string; onSelect: (id: string) => void; unfolded: string[]; onUnfold: (name: string) => void }) {
  const [closed, setClosed] = useState<string[]>([])
  const folded = book.folded.filter((name) => !unfolded.includes(name))
  return (
    <DirectoryShell title="设定" search="找人物、地方、规矩……" onTitle={() => onSelect('overview')}
      footer={folded.length > 0 && (
        <div className="mt-6 border-t border-line px-2 pt-4">
          <p className="mb-2 text-xs leading-relaxed text-ink-3">按题材先收起来的：</p>
          <div className="flex flex-wrap gap-1.5">
            {folded.map((name) => (
              <button key={name} type="button" onClick={() => onUnfold(name)}
                className="flex items-center gap-1 rounded-full border border-dashed border-line-2 px-2.5 py-1 text-xs text-ink-2 hover:border-ink-3/60 hover:text-ink">
                <Plus className="size-3" />{name}
              </button>
            ))}
          </div>
        </div>
      )}>
      {selected === 'overview' && <div className="mb-1 rounded-md bg-card px-3 py-1.5 text-sm font-medium text-ink shadow-[0_1px_2px_rgb(60_40_20/0.08)]">设定总览</div>}
      {[...book.categories, ...unfolded.filter((n) => book.folded.includes(n)).map((name) => ({ name, hints: CATEGORY_HINTS[name] ?? [], entries: [] }))].map((cat) => {
        const open = !closed.includes(cat.name)
        const catId = `cat:${cat.name}`
        return (
          <div key={cat.name} className="mt-1.5">
            <div className={clsx('group flex items-center rounded-md transition-colors', selected === catId ? 'bg-card shadow-[0_1px_2px_rgb(60_40_20/0.08)]' : 'hover:bg-line/50')}>
              <button type="button" onClick={() => setClosed(open ? [...closed, cat.name] : closed.filter((n) => n !== cat.name))}
                className={clsx('flex size-7 items-center justify-center text-ink-3', !cat.entries.length && 'invisible')} aria-label={open ? '收起' : '展开'}>
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              </button>
              <button type="button" onClick={() => onSelect(catId)} className={clsx('flex-1 py-1.5 text-left text-sm', selected === catId ? 'font-medium text-ink' : cat.entries.length ? 'text-ink-2' : 'text-ink-3')}>
                {cat.name}
              </button>
              <span className="pr-3 text-xs text-ink-3 tabular-nums">{cat.entries.length || '空'}</span>
            </div>
            {open && cat.entries.length > 0 && (
              <div className="mt-0.5 mb-1 ml-[17px] border-l border-line pl-1.5">
                {cat.name === '角色' ? <CharacterGroups entries={cat.entries} selected={selected} onSelect={onSelect} />
                  : <EntryList entries={cat.entries} selected={selected} onSelect={onSelect} />}
              </div>
            )}
          </div>
        )
      })}
    </DirectoryShell>
  )
}

function OutlineTreeView({ node, depth, selected, onSelect, open, toggle }: { node: VNode; depth: number; selected: string; onSelect: (id: string) => void; open: string[]; toggle: (id: string) => void }) {
  const expandable = !!node.children?.length
  const expanded = open.includes(node.id)
  return (
    <div>
      <div className={clsx('group flex items-center rounded-md transition-colors', selected === node.id ? 'bg-card shadow-[0_1px_2px_rgb(60_40_20/0.08)]' : 'hover:bg-line/40')}
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
        {node.locked && <Lock className="mr-1.5 size-3 shrink-0 text-ink-3" />}
        {node.chapters && <span className="pr-3 text-xs text-ink-3 tabular-nums">{node.chapters} 章</span>}
      </div>
      {expandable && expanded && node.children!.map((child) => (
        <OutlineTreeView key={child.id} node={child} depth={depth + 1} selected={selected} onSelect={onSelect} open={open} toggle={toggle} />
      ))}
    </div>
  )
}

/* ---------------- 中间一页纸 ---------------- */

function Sheet({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[1080px] px-8 py-10 2xl:max-w-[1180px] 2xl:py-12">
      <article className="rounded-xl border border-line bg-manuscript px-12 py-11 shadow-[var(--shadow-paper)] 2xl:px-16 2xl:py-14">{children}</article>
    </div>
  )
}

function Crumb({ items }: { items: string[] }) {
  return <p className="mb-4 text-[13px] tracking-wider text-ink-3">{items.join('  /  ')}</p>
}

function EntryHeader({ entry }: { entry: VEntry }) {
  return (
    <header>
      <Crumb items={['设定', entry.category]} />
      <div className="flex flex-wrap items-center gap-3">
        <Editable className="font-serif text-[34px] leading-tight font-bold break-all 2xl:text-[38px]">{entry.name}</Editable>
        {entry.tags.map((tag) => (
          <span key={tag} className="rounded-full bg-seal-soft px-2.5 py-0.5 text-xs text-seal">{tag}</span>
        ))}
        {entry.locked && <span className="flex items-center gap-1 rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2"><Lock className="size-3" />锁住，AI 不改</span>}
      </div>
      <Editable placeholder="一句话说清这是什么" className="mt-3 font-serif text-lg leading-relaxed text-ink-2 2xl:text-xl">{entry.oneLine}</Editable>
    </header>
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

function EntryPage({ book, entry, nav }: { book: VBook; entry: VEntry; nav: Nav }) {
  const secret = entry.secret ? findEntry(book, entry.secret) : undefined
  const goldfinger = entry.goldfinger ? findEntry(book, entry.goldfinger) : undefined
  const holder = entry.holder ? findEntry(book, entry.holder) : undefined
  const parent = entry.parent ? findEntry(book, entry.parent) : undefined
  const hints = book.categories.find((c) => c.name === entry.category)?.hints ?? []
  const secretChip = secret && <LinkChip icon={<Lock className="size-3" />} onClick={() => nav.openEntry(secret.id)}>另有秘密：{secret.name}</LinkChip>
  return (
    <Sheet>
      <EntryHeader entry={entry} />
      <Body
        side={
          <>
            <FactRows rows={entry.facts} />
            {parent && (
              <Side title="属于">
                <LinkChip onClick={() => nav.openEntry(parent.id)}>{parent.name}</LinkChip>
              </Side>
            )}
            {holder && (
              <Side title="谁在用">
                <LinkChip onClick={() => nav.openEntry(holder.id)}>{holder.name}</LinkChip>
              </Side>
            )}
            {entry.now && (
              <Side title="此刻" note="设定师每写完一章更新">
                <FactRows rows={entry.now} />
              </Side>
            )}
            {entry.kind === 'character' && (
              <Side title="关系">
                {entry.relations?.length ? (
                  <div className="space-y-1">
                    {entry.relations.map((rel) => {
                      const target = findEntry(book, rel.to)
                      return (
                        <button key={rel.to + rel.kind} type="button" onClick={() => nav.openEntry(rel.to)} className="block w-full rounded-lg px-2 py-2 text-left transition-colors hover:bg-subtle" title={rel.text}>
                          <span className="flex items-center gap-2">
                            <span className="truncate font-serif text-[15px] font-bold text-ink">{target?.name}</span>
                            <span className="shrink-0 rounded-full bg-line/70 px-2 py-px text-[11px] text-ink-2">{rel.kind}</span>
                          </span>
                          <span className="mt-0.5 line-clamp-2 text-[13px] leading-relaxed text-ink-3">{rel.text}</span>
                        </button>
                      )
                    })}
                  </div>
                ) : <p className="px-2 text-[13px] text-ink-3">还没写。</p>}
                <button type="button" className="mt-1 flex items-center gap-1 px-2 text-[13px] text-ink-3 hover:text-ink"><Plus className="size-3.5" />加一个关系</button>
              </Side>
            )}
            <Side title="出现在"><Appears items={entry.appears} nav={nav} /></Side>
            {entry.kind !== 'character' && <Side title="写的时候想一想"><HintList hints={hints} /></Side>}
          </>
        }
      >
        {entry.kind === 'ladder' ? (
          <>
            <Section field={{ label: '总说明', text: entry.overview ?? '', placeholder: '怎么往上升、越级多难、有什么代价' }} />
            <section>
              <h3 className="mb-4 text-[13px] tracking-[0.15em] text-ink-3">各级 · 从低到高</h3>
              <ol>
                {(entry.levels ?? []).map((level, i, levels) => (
                  <li key={level.name + i} className="relative flex gap-5 pb-7 last:pb-0">
                    {i < levels.length - 1 && <span className="absolute top-9 bottom-1 left-[17px] w-px bg-line-2" />}
                    <span className="relative flex size-9 shrink-0 items-center justify-center rounded-full border border-line-2 bg-card font-serif text-[15px] text-ink-2">{i + 1}</span>
                    <div className="min-w-0 flex-1 pt-1">
                      <Editable className="font-serif text-lg font-bold">{level.name}</Editable>
                      <Editable placeholder="这一级能做到什么，先空着也行" className="mt-1 font-serif text-[17px] leading-[1.9] text-ink-2">{level.text}</Editable>
                    </div>
                  </li>
                ))}
              </ol>
              <button type="button" className="mt-5 ml-14 flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink"><Plus className="size-3.5" />加一级</button>
            </section>
          </>
        ) : (
          entry.sections.map((field) => (
            <Section key={field.label} field={field}>
              {(field.label === '身世' || field.label === '来历') && secretChip}
              {field.label === '能力' && goldfinger && <LinkChip icon={<Sparkles className="size-3" />} onClick={() => nav.openEntry(goldfinger.id)}>金手指：{goldfinger.name}</LinkChip>}
            </Section>
          ))
        )}
      </Body>
    </Sheet>
  )
}

function CategoryPage({ category, nav }: { category: VCategory; nav: Nav }) {
  return (
    <Sheet>
      <Crumb items={['设定']} />
      <h1 className="font-serif text-[34px] font-bold 2xl:text-[38px]">{category.name}</h1>
      <p className="mt-3 font-serif text-lg leading-relaxed text-ink-2">{category.hints.join('；')}。</p>
      <Body side={<Side title="写的时候想一想"><HintList hints={category.hints} /></Side>}>
        {category.entries.length ? (
          <div className="divide-y divide-line border-y border-line">
            {category.entries.map((entry) => (
              <button key={entry.id} type="button" onClick={() => nav.openEntry(entry.id)} className="group flex w-full items-baseline gap-5 py-4 text-left">
                <span className="w-36 shrink-0 truncate font-serif text-[17px] font-bold text-ink group-hover:text-seal">{entry.name}</span>
                <span className="line-clamp-1 flex-1 text-[15px] text-ink-2">{entry.oneLine || <span className="text-ink-3">还没写一句话</span>}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-line-2 px-8 py-12 text-center">
            <p className="text-[15px] text-ink-2">这一类还没有写。</p>
            <p className="mt-1 text-[13px] text-ink-3">可以自己写，也可以让编辑部按简介先补几条，你写过的不会动。</p>
            <div className="mt-6 flex justify-center gap-3">
              <button type="button" className="h-10 rounded-lg border border-line-2 bg-card px-5 text-sm text-ink transition-colors hover:border-ink-3/50">自己写一条</button>
              <AskButton onClick={() => nav.toast('原型：点了以后编辑部开始写，写好的条目一条条出现在左边目录里')}>让编辑部补几条</AskButton>
            </div>
            {category.starters && (
              <div className="mt-8 border-t border-line pt-6">
                <p className="mb-3 text-[13px] text-ink-3">这本书可能用得上，点一下就建一条：</p>
                <div className="flex flex-wrap justify-center gap-2">
                  {category.starters.map((name) => (
                    <button key={name} type="button" onClick={() => nav.toast(`原型：会建一条空的「${name}」，你自己写`)}
                      className="flex items-center gap-1 rounded-full border border-dashed border-line-2 px-3.5 py-1.5 font-serif text-[15px] text-ink-2 transition-colors hover:border-ink-3/60 hover:text-ink">
                      <Plus className="size-3.5" />{name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Body>
    </Sheet>
  )
}

/** 设定总览：空书点完「下一步」先看到这里；有内容的书点目录上的「设定」也到这里。 */
function SettingsOverview({ book, nav, onSelect }: { book: VBook; nav: Nav; onSelect: (id: string) => void }) {
  const total = book.categories.reduce((sum, c) => sum + c.entries.length, 0)
  const first = ['角色', '金手指']
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
              {cat.entries.length ? cat.entries.slice(0, 4).map((e) => e.name).join('、') : cat.hints[0]}
            </span>
            <span className="mt-2 block text-[13px] text-chief opacity-0 transition-opacity group-hover:opacity-100">{cat.entries.length ? '进去看 →' : '写第一条 →'}</span>
          </button>
        ))}
      </div>
      {book.folded.length > 0 && (
        <p className="mt-6 text-[13px] leading-relaxed text-ink-3">
          这本书是{book.genre}，「{book.folded.join('」「')}」一般用不上，先收起来了；要用就在左边目录最下面加上。
        </p>
      )}
    </Sheet>
  )
}

const NODE_PLACEHOLDER: Record<VNode['kind'], string> = {
  全书: '结局往哪走，一句话',
  篇: '在哪个舞台；主角这一篇想做成什么；谁挡路；怎么收尾；读者在等什么',
  卷: '这一卷想做成什么；卷首处境；卷末的高潮和结果；这一卷的对手',
  单元: '什么事找上门；主角怎么应对；读者叫好的那一下；做完拿到什么',
  章: '发生什么；看点；结尾的钩子',
}

function OutlinePage({ book, id, nav }: { book: VBook; id: string; nav: Nav }) {
  const path = findNode(book.outline, id) ?? [book.outline]
  const node = path[path.length - 1]
  const parent = path[path.length - 2]
  const emptyBookOutline = node.kind === '全书' && !node.children?.length
  return (
    <Sheet>
      <div className="flex items-start justify-between gap-6">
        <Crumb items={['大纲', ...path.slice(0, -1).map((n) => n.title)]} />
        {node.locked && <span className="flex shrink-0 items-center gap-1 rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2"><Lock className="size-3" />锁住，AI 规划时不改</span>}
      </div>
      <div className="flex flex-wrap items-baseline gap-3">
        <Editable className="font-serif text-[34px] leading-tight font-bold 2xl:text-[38px]">{node.title}</Editable>
        {node.later && <span className="rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2">写到再定</span>}
      </div>
      <Body
        side={
          <>
            <FactRows rows={[
              ['层级', node.kind],
              ...(node.chapters ? [['章数', `${node.chapters} 章`] as [string, string]] : []),
              ...(parent ? [['属于', parent.title] as [string, string]] : []),
            ]} />
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
              ) : <p className="text-[13px] text-ink-3">还没挂上设定。</p>}
            </Side>
            <Side title="写的时候想一想"><HintList hints={NODE_PLACEHOLDER[node.kind].split('；')} /></Side>
          </>
        }
      >
        {node.sections
          ? node.sections.map((field) => <Section key={field.label} field={field} />)
          : <Section field={{ label: node.kind === '全书' ? '结局' : '一段话', text: node.text, placeholder: NODE_PLACEHOLDER[node.kind] }} />}
        {emptyBookOutline && (
          <div className="rounded-2xl border border-dashed border-line-2 px-8 py-12 text-center">
            <p className="text-[15px] text-ink-2">大纲还空着。</p>
            <p className="mt-1 text-[13px] text-ink-3">先有一段话就行：第一篇在哪个舞台、主角想做成什么。写到哪里展开到哪里。</p>
            <div className="mt-6 flex justify-center gap-3">
              <button type="button" className="h-10 rounded-lg border border-line-2 bg-card px-5 text-sm text-ink transition-colors hover:border-ink-3/50">自己写第一篇</button>
              <AskButton onClick={() => nav.toast('原型：编辑部会按简介和设定出第一篇和第一卷，写好出现在左边的树里')}>让编辑部出一版</AskButton>
            </div>
          </div>
        )}
        {!!node.children?.length && (
          <section>
            <h3 className="mb-2 text-[13px] tracking-[0.15em] text-ink-3">下面一层 · {node.children.length} 个</h3>
            <div className="divide-y divide-line border-y border-line">
              {node.children.map((child) => (
                <button key={child.id} type="button" onClick={() => nav.openNode(child.id)} className="group flex w-full items-baseline gap-5 py-3.5 text-left">
                  <span className={clsx('w-52 shrink-0 truncate font-serif text-[16px] font-bold group-hover:text-seal', child.later ? 'text-ink-3' : 'text-ink')}>{child.title}</span>
                  <span className="line-clamp-1 flex-1 text-[14px] text-ink-3">{(child.text || child.sections?.[0]?.text || '').split('\n')[0] || '写到再定'}</span>
                  {child.chapters && <span className="text-xs text-ink-3 tabular-nums">{child.chapters} 章</span>}
                </button>
              ))}
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
  const characters = book.categories.find((c) => c.name === '角色')?.entries ?? []
  const lead = characters.find((c) => c.role === '主角') ?? characters[0]
  return lead?.id ?? (book.categories.find((c) => c.entries.length)?.entries[0]?.id ?? 'overview')
}

function Workspace({ book }: { book: VBook }) {
  const [tab, setTab] = useState<Tab>('设定')
  const [entry, setEntry] = useState(() => (book.categories.some((c) => c.entries.length) ? firstSelection(book) : 'overview'))
  const firstChild = book.outline.children?.[0]
  const [node, setNode] = useState(firstChild?.children?.[0]?.id ?? firstChild?.id ?? 'book')
  const [open, setOpen] = useState(() => {
    const path = findNode(book.outline, firstChild?.children?.[0]?.id ?? 'book') ?? []
    return ['book', ...path.map((n) => n.id)]
  })
  const [unfolded, setUnfolded] = useState<string[]>([])
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
      pageRef.current?.scrollTo({ top: 0 })
    },
    openNode: (id) => {
      setTab('大纲')
      setNode(id)
      const path = findNode(book.outline, id)
      if (path) setOpen((list) => [...new Set([...list, ...path.slice(0, -1).map((n) => n.id)])])
      pageRef.current?.scrollTo({ top: 0 })
    },
    toast: setToast,
  }

  const categoryName = entry.startsWith('cat:') ? entry.slice(4) : ''
  const category = categoryName
    ? book.categories.find((c) => c.name === categoryName) ?? { name: categoryName, hints: CATEGORY_HINTS[categoryName] ?? [], entries: [] }
    : undefined
  const current = entry !== 'overview' && !categoryName ? findEntry(book, entry) : undefined

  return (
    <div className="flex h-dvh flex-col bg-paper text-ink">
      <TopBar book={book} tab={tab} onTab={setTab} />
      <div className="flex min-h-0 flex-1">
        {tab === '设定' && <SettingsDirectory book={book} selected={entry} onSelect={nav.openEntry} unfolded={unfolded} onUnfold={(name) => { setUnfolded([...unfolded, name]); nav.openEntry(`cat:${name}`) }} />}
        {tab === '大纲' && (
          <DirectoryShell title="大纲" search="找篇、卷、单元、章……">
            <OutlineTreeView node={book.outline} depth={0} selected={node} onSelect={nav.openNode} open={open} toggle={(id) => setOpen(open.includes(id) ? open.filter((x) => x !== id) : [...open, id])} />
          </DirectoryShell>
        )}
        <main ref={pageRef} className="scroll-thin min-w-0 flex-1 overflow-y-auto">
          {tab === '简介' && <BlurbPage book={book} />}
          {tab === '设定' && (current ? <EntryPage key={current.id} book={book} entry={current} nav={nav} />
            : category ? <CategoryPage category={category} nav={nav} />
              : <SettingsOverview book={book} nav={nav} onSelect={nav.openEntry} />)}
          {tab === '大纲' && <OutlinePage key={node} book={book} id={node} nav={nav} />}
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
  return (
    <>
      {book ? <Workspace key={source} book={book} />
        : (
          <div className="flex h-dvh items-center justify-center bg-paper text-[15px] text-ink-3">
            {loading ? '正在读这本书…' : `这本书没读出来：${error ?? ''}`}
          </div>
        )}
      <BookSwitcher source={source} onSource={(next) => setParams(next === 'sample' ? {} : { book: next })} />
    </>
  )
}
