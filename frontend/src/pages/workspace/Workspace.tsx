import clsx from 'clsx'
import { ArrowLeft, BookOpen, ChevronDown, ChevronRight, ChevronUp, Globe, Inbox, Lock, Minus, PanelRight, PictureInPicture2, Pin, Plus, X } from 'lucide-react'
import { type PointerEvent as ReactPointerEvent, type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ChatViewing } from '../../api/types'
import { useBookMeta } from '../../api/newBook'
import { CategoryPicker, LengthInput, Row, TagPicker } from '../../components/BookFields'
import { BookCover } from '../../components/BookCover'
import { readEditorialDock, writeEditorialDock, type EditorialDock as Dock } from '../../lib/editorialDock'
import { readWorkspaceReadingPosition, writeWorkspaceReadingPosition, type WorkspaceReadingPosition } from '../../lib/workspaceReadingPosition'
import {
  ActionsContext, type CategoryStyle, type DraftItem, type EntryChange, type RewriteMode, type RewriteOutcome, type WorkspaceActions,
  blankEntry, childKind, draftToEntry, entryIn, useSave, useWorkspace, withFields,
} from './actions'
import { PendingNote } from './Inbox'
import {
  ROLE_ORDER, applyTemplate, cn, emptyCategory, findEntry, findNode, isLadder, nounOf, pinnedFirst, splitTitle, templateOf, undecidedParts,
  type CardTemplate, type FieldItem, type VBook, type VCategory, type VEntry, type VNode,
} from './model'
import { PENDING } from './sampleBook'
import { ChapterPage, GateCard, ManuscriptDirectory, ManuscriptHome, WritingStrip } from './Manuscript'
import { type WritingControl, gateTarget } from './writing'
import { SplitPanel } from './Split'
import { useSplit } from './useSplit'
import {
  AskButton, CardMenu, Crumb, DirectoryShell, Editable, LinkChip, Prose, Section, Sheet, SideColumn,
} from './widgets'
import { ColumnWidthContext, SideFooterContext, useColumnWidth, zoomOf } from './column'
import { paperCard, readText, rowSelected, smallButton, titleClass } from './styles'

export type Tab = '简介' | '设定' | '大纲' | '正文'
/** 点了左边：滚到哪一张；同一类里平滑滚，换类直接跳 */
interface ScrollReq { id: string; smooth: boolean; n: number }

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
  /** 正文里的某一章；home 是正文首页（开写） */
  openChapter: (id: string) => void
  toast: (text: string) => void
}

/* ---------------- 顶栏 ---------------- */

/** 待处理：编辑部挂着的建议。 */
export function InboxButton({ count, children }: { count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  if (!count) return null
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-ink-2 transition-colors hover:bg-line/50 hover:text-ink">
        <Inbox className="size-4" />
        待处理
        <span className="flex min-w-5 items-center justify-center rounded-full bg-seal px-1.5 text-[11px] leading-5 text-on-role">{count}</span>
      </button>
      {open && <div className="absolute top-[calc(100%+6px)] right-0 z-30 w-80 rounded-xl border border-line bg-card p-2 shadow-[var(--shadow-lift)]">{children}</div>}
    </div>
  )
}

/** 原型里待处理的样子。 */
export function SampleInbox({ book }: { book: VBook }) {
  return (
    <InboxButton count={book.pending}>
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
    </InboxButton>
  )
}

function TopBar({ book, tab, onTab, right, manuscriptHref, manuscript, leftOffset, rightOffset }: {
  book: VBook; tab: Tab; onTab: (tab: Tab) => void; right: ReactNode; manuscriptHref?: string; manuscript?: boolean
  /** 左边那一栏、右边贴着的编辑部各多宽：四个入口对准中间那一栏，换页签时不跳 */
  leftOffset: number; rightOffset: number
}) {
  const item = 'flex h-8 items-center rounded-lg px-5 text-[15px] transition-colors 2xl:px-6'
  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-paper px-4 2xl:h-16 2xl:px-6">
      <Link to="/" className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
        <ArrowLeft className="size-4" />
        书房
      </Link>
      <span className="h-5 w-px bg-line-2" />
      <BookCover title={book.title} seed={book.id === 'sample' ? '开新书' : book.id} size="xs" />
      <span className="max-w-64 truncate font-serif text-[17px] font-bold tracking-wide 2xl:text-lg">{book.title}</span>

      {/* 四个入口对准中间那一栏，正好在那页纸上方 */}
      <nav className="pointer-events-none absolute inset-y-0 flex items-center justify-center" style={{ left: leftOffset, right: rightOffset }}>
        <div className="pointer-events-auto flex items-center gap-0.5 rounded-xl bg-paper-2 p-1 ring-1 ring-line">
          {(manuscript ? ['简介', '设定', '大纲', '正文'] as const : ['简介', '设定', '大纲'] as const).map((key) => (
            <button key={key} type="button" onClick={() => onTab(key)} aria-current={tab === key ? 'page' : undefined}
              className={clsx(item, tab === key ? 'bg-card font-medium text-ink shadow-[0_1px_3px_rgb(60_40_20/0.14)]' : 'text-ink-3 hover:text-ink')}>
              {key}
            </button>
          ))}
          {manuscript ? null : manuscriptHref
            ? <Link to={manuscriptHref} title="正文还没搬到新书页，先在旧版里看" className={clsx(item, 'text-ink-3 hover:text-ink')}>正文</Link>
            : <span className={clsx(item, 'cursor-not-allowed text-ink-3/50')} title="开写以后才有">正文</span>}
        </div>
      </nav>

      <div className="ml-auto flex items-center gap-1">{right}</div>
    </header>
  )
}

/* ---------------- 左边目录 ---------------- */

function EntryButton({ entry, selected, depth = 0, pinned, onSelect }: { entry: VEntry; selected: string; depth?: number; pinned?: boolean; onSelect: (id: string) => void }) {
  const ref = useRef<HTMLButtonElement>(null)
  // 右边滚动换了选中的那条，左边目录跟着滚到看得见
  useEffect(() => {
    if (selected === entry.id) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [selected, entry.id])
  return (
    <button ref={ref} type="button" onClick={() => onSelect(entry.id)} title={entry.name}
      style={{ paddingLeft: 10 + depth * 14 }}
      className={clsx('flex w-full items-center gap-2 rounded-md py-1.5 pr-2.5 text-left font-serif text-[14px] transition-colors 2xl:text-[15px]',
        selected === entry.id ? `${rowSelected} font-bold text-ink` : 'text-ink-2 hover:bg-line/40 hover:text-ink')}>
      {depth > 0 && <span className="text-ink-3/60">└</span>}
      <span className={clsx('truncate', !entry.name && 'text-ink-3')}>{entry.name || '未命名'}</span>
      {entry.locked && <Lock className="size-3 shrink-0 text-ink-3" />}
      {pinned && <Pin className="ml-auto size-3 shrink-0 text-ink-3" aria-hidden />}
    </button>
  )
}

const SHOW_FIRST = 12

/** 地点按「属于哪里」排成树：先父后子。 */
function treeRows(entries: VEntry[]): { entry: VEntry; depth: number }[] {
  const ids = new Set(entries.map((e) => e.id))
  const children = new Map<string, VEntry[]>()
  for (const e of entries) if (e.parent && ids.has(e.parent)) children.set(e.parent, [...(children.get(e.parent) ?? []), e])
  const rows: { entry: VEntry; depth: number }[] = []
  const walk = (e: VEntry, depth: number) => {
    rows.push({ entry: e, depth })
    for (const child of children.get(e.id) ?? []) walk(child, Math.min(depth + 1, 3))
  }
  entries.filter((e) => !e.parent || !ids.has(e.parent)).forEach((e) => walk(e, 0))
  return rows
}

/** 置顶多于这么多人时，目录里提醒一句 */
const PIN_LIMIT = 5

function roleOrder(entries: VEntry[]): string[] {
  return [...ROLE_ORDER, ...new Set(entries.map((e) => e.role ?? '配角').filter((r) => !ROLE_ORDER.includes(r)))]
}

/** 右边连着排的顺序和左边目录一样：角色按定位分组，地点按树。 */
function orderEntries(category: VCategory): VEntry[] {
  if (category.name === '角色列表' && !category.custom) {
    // 和左边目录一样：置顶的在前；没人置顶的书（原型的示例书）照旧按定位排
    if (category.entries.some((e) => e.pinnedAt)) return [...pinnedFirst(category.entries), ...category.entries.filter((e) => !e.pinnedAt)]
    return roleOrder(category.entries).flatMap((role) => category.entries.filter((e) => (e.role ?? '配角') === role))
  }
  return treeRows(category.entries).map((r) => r.entry)
}

/** 一类里的条目：地点按「属于哪里」缩进；太多先只显示前面一部分。 */
function EntryList({ entries, selected, onSelect }: { entries: VEntry[]; selected: string; onSelect: (id: string) => void }) {
  const [all, setAll] = useState(false)
  const rows = treeRows(entries)
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

/** 角色目录：置顶的在最上面（后置顶的在上，名字后面一个图钉），一条细线下面是其他人。不另起小标题，免得目录多一层。
 *  置顶的人多了提醒一句。 */
function CharacterGroups({ entries, selected, onSelect }: { entries: VEntry[]; selected: string; onSelect: (id: string) => void }) {
  const pinned = pinnedFirst(entries)
  const rest = entries.filter((e) => !e.pinnedAt)
  return (
    <>
      {pinned.map((entry) => <EntryButton key={entry.id} entry={entry} pinned selected={selected} onSelect={onSelect} />)}
      {pinned.length > PIN_LIMIT && <p className="px-2.5 pt-1 pb-1 text-[11px] leading-relaxed text-seal-dark">置顶的人每写一章都带上，人多了资料会变多、冲淡这一章的重点</p>}
      {pinned.length > 0 && rest.length > 0 && <div className="mx-2.5 my-1 border-t border-dashed border-line-2" />}
      {rest.length > 0 && <EntryList entries={rest} selected={selected} onSelect={onSelect} />}
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
    if (clean && !error) onCreate(clean, style, [...new Set(fields.split(/[、,，;；\s]+/).map((f) => f.trim()).filter(Boolean))])
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
  const [query, setQuery] = useState('')
  const q = query.trim()
  const current = selected.startsWith('cat:') ? selected.slice(4) : findEntry(book, selected)?.category
  return (
    <DirectoryShell title="设定" search="找人物、地方、规矩……" query={query} onQuery={setQuery} onTitle={() => onSelect('overview')}
      addMenu={current ? [{ label: `新增${nounOf(current)}`, onClick: () => onNewEntry(current) }] : undefined}
      footer={q ? null : creating ? (
        <NewCategoryForm taken={book.categories.map((c) => c.name)} onCancel={() => setCreating(false)}
          onCreate={(name, style, fields) => { setCreating(false); onCreateCategory(name, style, fields) }} />
      ) : (
        // 和上面的类别同一种行，排在最后，不另做按钮
        <button type="button" onClick={() => setCreating(true)}
          className="mt-1.5 flex w-full items-center rounded-md py-1.5 pl-7 text-left text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
          新建一类…
        </button>
      )}>
      {q ? (
        // 找东西：只列名字对得上的
        (() => {
          const hits = book.categories.flatMap((c) => c.entries.filter((e) => e.name.includes(q)).map((e) => ({ e, c })))
          return hits.length ? hits.map(({ e, c }) => (
            <div key={e.id} className="flex items-center">
              <div className="min-w-0 flex-1"><EntryButton entry={e} selected={selected} onSelect={onSelect} /></div>
              <span className="shrink-0 pr-2 text-xs text-ink-3">{c.name}</span>
            </div>
          )) : <p className="px-2.5 py-2 text-[13px] text-ink-3">没找到「{q}」</p>
        })()
      ) : (
        <>
          {selected === 'overview' && <div className={clsx('mb-1 rounded-md px-3 py-1.5 text-sm font-medium text-ink', rowSelected)}>设定总览</div>}
          <button type="button" onClick={() => onSelect('world')}
            className={clsx('mb-1 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[15px] font-semibold transition-colors', selected === 'world' ? `${rowSelected} text-ink` : book.world ? 'text-ink hover:bg-line/50' : 'text-ink-3 hover:bg-line/50')}>
            <Globe className="size-3.5 text-ink-3" />
            世界概况
            {!book.world && <span className="ml-auto pr-0.5 text-xs text-ink-3">空</span>}
          </button>
          {book.categories.map((cat) => {
            const open = !closed.includes(cat.name)
            const catId = `cat:${cat.name}`
            return (
              <div key={cat.key} className="mt-1.5">
                {/* 往下翻时类别名停在顶上，内容再多也知道在哪一类；底色和侧栏一样，盖住滚上去的条目 */}
                <div className="sticky top-0 z-[1] bg-paper-2">
                <div className={clsx('group flex items-center rounded-md transition-colors', selected === catId ? rowSelected : 'hover:bg-line/50')}>
                  <button type="button" onClick={() => setClosed(open ? [...closed, cat.name] : closed.filter((n) => n !== cat.name))}
                    className={clsx('flex size-7 items-center justify-center text-ink-3', !cat.entries.length && 'invisible')} aria-label={open ? '收起' : '展开'}>
                    {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                  </button>
                  <button type="button" onClick={() => onSelect(catId)} className={clsx('flex-1 py-1.5 text-left text-[15px] font-semibold', selected === catId || cat.entries.length ? 'text-ink' : 'text-ink-3')}>
                    {cat.name}
                    {cat.custom && <span className="ml-1.5 text-[11px] text-ink-3">自建</span>}
                  </button>
                  <span className="pr-3 text-xs text-ink-3 tabular-nums">{cat.entries.length || '空'}</span>
                </div>
                </div>
                {open && cat.entries.length > 0 && (
                  <div className="mt-0.5 mb-1 ml-[17px] border-l border-line pl-1.5">
                    {cat.name === '角色列表' && !cat.custom ? <CharacterGroups entries={cat.entries} selected={selected} onSelect={onSelect} />
                      : <EntryList entries={cat.entries} selected={selected} onSelect={onSelect} />}
                  </div>
                )}
              </div>
            )
          })}
        </>
      )}
    </DirectoryShell>
  )
}

/** 树上显示的名字：还没起名的写「未命名」。 */
function shownTitle(node: VNode): string {
  const [prefix, name] = splitTitle(node.title)
  return node.title.includes('　') && !name.trim() ? `${prefix}　未命名` : node.title
}

/** 找大纲：名字对得上的节点，连同它上面的几层。 */
function matchingIds(node: VNode, q: string, out = new Set<string>()): boolean {
  let hit = node.kind !== '全书' && node.title.includes(q)
  for (const child of node.children ?? []) if (matchingIds(child, q, out)) hit = true
  if (hit) out.add(node.id)
  return hit
}

/** 大纲树的一行：鼠标移上去出现「+」，在这一层下面加一个。 */
function OutlineTreeView({ node, depth, selected, onSelect, open, toggle, onAdd, only }: {
  node: VNode; depth: number; selected: string; onSelect: (id: string) => void; open: string[]; toggle: (id: string) => void; onAdd: (id: string) => void; only?: Set<string>
}) {
  const { actions } = useWorkspace()
  const children = (node.children ?? []).filter((c) => !only || only.has(c.id))
  const expandable = !!children.length
  const expanded = !!only || open.includes(node.id)
  const child = actions.canAdd(node) ? childKind(node) : undefined
  // 有几章就写几章：章数没定的单元不写
  const count = node.kind === '章' ? 0 : node.range ? node.range[1] - node.range[0] + 1 : node.chapters ?? 0
  return (
    <div>
      <div className={clsx('group flex items-center rounded-md transition-colors', selected === node.id ? rowSelected : 'hover:bg-line/40')}
        style={{ paddingLeft: depth * 12 }}>
        <button type="button" onClick={() => expandable && toggle(node.id)} className={clsx('flex size-7 shrink-0 items-center justify-center text-ink-3', !expandable && 'invisible')} aria-label={expanded ? '收起' : '展开'}>
          {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
        <button type="button" onClick={() => (selected === node.id && expandable ? toggle(node.id) : onSelect(node.id))} title={node.title}
          className={clsx('min-w-0 flex-1 truncate py-[7px] pr-2 text-left',
            node.kind === '章' ? 'text-sm' : 'font-serif text-[15px] 2xl:text-base',
            node.later ? 'text-ink-3' : selected === node.id ? 'font-bold text-ink' : 'text-ink-2 group-hover:text-ink')}>
          {shownTitle(node)}
          {node.later && <span className="ml-1.5 text-xs font-normal">· 写到再定</span>}
        </button>
        {node.locked && <Lock className={clsx('mr-1.5 size-3 shrink-0 text-ink-3', child && 'group-hover:hidden')} />}
        {count > 0 && <span className={clsx('pr-3 text-xs text-ink-3 tabular-nums', child && 'group-hover:hidden')}>{count} 章</span>}
        {child && (
          <button type="button" onClick={() => onAdd(node.id)} title={`在下面加${ONE[child]}`} aria-label={`在下面加${ONE[child]}`}
            className="mr-1.5 hidden rounded p-1 text-ink-3 hover:bg-line/70 hover:text-ink group-hover:block">
            <Plus className="size-3.5" />
          </button>
        )}
      </div>
      {expandable && expanded && children.map((c) => (
        <OutlineTreeView key={c.id} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} open={open} toggle={toggle} onAdd={onAdd} only={only} />
      ))}
    </div>
  )
}

/* ---------------- 中间一页纸 ---------------- */

function Tags({ entry }: { entry: VEntry }) {
  return (
    <>
      {entry.tags.map((tag) => <span key={tag} className="rounded-full bg-seal-soft px-2.5 py-0.5 text-xs text-seal">{tag}</span>)}
      {entry.locked && <span className="flex items-center gap-1 rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2"><Lock className="size-3" />锁住，AI 不改</span>}
    </>
  )
}

interface MetaItem { label: string; value?: string; placeholder?: string; link?: () => void; onSave?: (text: string) => void; picker?: ReactNode }

function AppearsRow({ items, nav }: { items: VEntry['appears']; nav: Nav }) {
  if (!items.length) return null
  return (
    <div className="mt-8 flex flex-wrap items-center gap-2 border-t border-line pt-5 text-[13px] text-ink-3">
      <span className="mr-1">出现在</span>
      {items.map((a) => <LinkChip key={a.node} icon={<BookOpen className="size-3" />} onClick={() => nav.openNode(a.node)}>{a.label}</LinkChip>)}
    </div>
  )
}

/** 名字下面一行小字：所属、性别、年龄这类短的。 */
function MetaRow({ items, readOnly }: { items: MetaItem[]; readOnly?: boolean }) {
  if (!items.length) return null
  return (
    <div className="mt-5 flex flex-wrap items-baseline gap-x-7 gap-y-2">
      {items.map((item) => (
        <span key={item.label} className="flex items-baseline gap-2">
          <span className="text-[13px] text-ink-3">{item.label}</span>
          {item.picker ?? (item.link
            ? <button type="button" onClick={item.link} className="font-serif text-[16px] text-chief hover:underline">{item.value}</button>
            : <Editable value={item.value ?? ''} onSave={item.onSave} readOnly={readOnly} placeholder={item.placeholder ?? '写一下'} className="font-serif text-[16px] text-ink" />)}
        </span>
      ))}
    </div>
  )
}


/** 卡片上的几处改动都走这里：存哪一栏由工作台决定。 */
function useEntrySaver(entry: VEntry) {
  const { actions } = useWorkspace()
  const save = useSave()
  return (change: EntryChange) => save(actions.saveEntry(entry, change))
}

/** 关系：点名字去那个人，后面那句话可以直接改；能加能删。 */
function Relations({ book, entry, nav, readOnly }: { book: VBook; entry: VEntry; nav: Nav; readOnly?: boolean }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const [adding, setAdding] = useState(false)
  const [to, setTo] = useState('')
  const [kind, setKind] = useState('')
  const [text, setText] = useState('')
  const people = (book.categories.find((c) => c.name === '角色列表' && !c.custom)?.entries ?? []).filter((p) => p.id !== entry.id && !p.id.startsWith('draft-'))
  const add = () => {
    if (!to || !kind.trim()) return
    save(actions.addRelation(entry, to, kind.trim(), text.trim()))
    setAdding(false)
    setTo('')
    setKind('')
    setText('')
  }
  const field = 'h-9 rounded-lg border border-line-2 bg-card px-3 text-sm text-ink placeholder:text-ink-3 focus:border-ink-3 focus:outline-none'
  return (
    <section>
      <h3 className="mb-2 text-[13px] tracking-[0.15em] text-ink-3">关系</h3>
      <div className="divide-y divide-line/70">
        {(entry.relations ?? []).map((rel) => (
          <div key={rel.id ?? rel.to + rel.kind} className="group/rel flex items-baseline gap-4 py-2.5">
            <button type="button" onClick={() => nav.openEntry(rel.to)} className="w-24 shrink-0 truncate text-left font-serif text-[16px] font-bold text-ink hover:text-seal">{findEntry(book, rel.to)?.name}</button>
            <span className="shrink-0 rounded-full bg-line/70 px-2 py-px text-xs text-ink-2">{rel.kind}</span>
            <Editable value={rel.text} readOnly={readOnly} placeholder="怎么个关系，一句话" onSave={(value) => save(actions.saveRelation(entry, rel, value))}
              className="min-w-0 flex-1 text-[15px] leading-relaxed text-ink-2" />
            {!readOnly && (
              <button type="button" onClick={() => save(actions.deleteRelation(entry, rel))} aria-label="删掉这条关系" title="删掉这条关系"
                className="shrink-0 self-center rounded p-1 text-ink-3 opacity-0 transition-opacity group-hover/rel:opacity-100 hover:text-ink focus-visible:opacity-100">
                <X className="size-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>
      {!readOnly && (adding ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select value={to} onChange={(e) => setTo(e.target.value)} className={clsx(field, 'w-36', !to && 'text-ink-3')} aria-label="和谁">
            <option value="">和谁</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input value={kind} onChange={(e) => setKind(e.target.value)} maxLength={20} placeholder="什么关系：师父、仇人" className={clsx(field, 'w-40')} />
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={200} placeholder="一句话说说（可以不写）" className={clsx(field, 'min-w-0 flex-1')}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) add() }} />
          <button type="button" onClick={add} disabled={!to || !kind.trim()} className="h-9 rounded-lg bg-ink px-4 text-sm text-paper-2 hover:bg-ink-2 disabled:opacity-40">加上</button>
          <button type="button" onClick={() => setAdding(false)} className="h-9 rounded-lg px-3 text-sm text-ink-2 hover:bg-subtle">取消</button>
        </div>
      ) : (
        <button type="button" onClick={() => setAdding(true)} disabled={!people.length} title={people.length ? undefined : '先建别的人物'}
          className={clsx(smallButton, 'mt-3')}>新增关系</button>
      ))}
    </section>
  )
}

/** 新建的一条还没起名字：说一声，免得以为已经存了。 */
function DraftNote({ entry }: { entry: VEntry }) {
  if (!entry.id.startsWith('draft-')) return null
  return <p className="mt-2 text-[13px] text-ink-3">起好名字才会存下来</p>
}

/** 角色卡、金手指的一张卡：一栏到底。短字段在名字下面，长字段一段段往下，空着的也摆出来。 */
function CharacterCard({ book, entry, nav, fresh }: { book: VBook; entry: VEntry; nav: Nav; fresh: boolean }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const saveEntry = useEntrySaver(entry)
  const readOnly = entry.readonly
  const draft = entry.id.startsWith('draft-')
  const secret = entry.secret ? findEntry(book, entry.secret) : undefined
  const goldfinger = entry.goldfinger ? findEntry(book, entry.goldfinger) : undefined
  const holder = entry.holder ? findEntry(book, entry.holder) : undefined
  // 这一类有哪几栏就一次全摆出来，空着的显示一行淡字，点上去就能写
  const facts = entry.facts
  const sections = entry.sections
  const now = entry.now?.filter(([, value]) => value) ?? []
  const relations = entry.relations ?? []
  const people = entry.kind === 'character'
  const field = (key: string) => (text: string) => saveEntry({ fields: { [key]: text } })
  return (
    <section id={`entry-${entry.id}`} data-entry={entry.id} className={clsx(paperCard, 'group/card relative scroll-mt-6')}>
      {!readOnly && (
        <CardMenu locked={entry.locked} onLock={draft ? undefined : () => saveEntry({ locked: !entry.locked })}
          pinned={!!entry.pinnedAt} onPin={draft || !actions.pinEntry ? undefined : () => save(actions.pinEntry!(entry, !entry.pinnedAt))}
          onDelete={() => save(actions.deleteEntry(entry))} deleteLabel={draft ? '不要这一条了' : '删掉这一条'} />
      )}
      <PendingNote id={entry.id} />
      <div className="flex flex-wrap items-center gap-3 pr-28">
        <Editable autoFocus={fresh} value={entry.name} readOnly={readOnly} placeholder="起个名字" className={titleClass}
          onSave={(name) => { if (name.trim()) saveEntry({ name }) }} />
        <Tags entry={entry} />
        {entry.dead && <span className="rounded-full bg-ink/80 px-2.5 py-0.5 text-xs text-paper-2">已死</span>}
      </div>
      <DraftNote entry={entry} />
      {readOnly && <p className="mt-2 text-[13px] text-ink-3">这一条从「{holder?.name}」的角色卡推出来，到角色卡上去改。</p>}
      <Editable value={entry.oneLine} readOnly={readOnly} onSave={(oneLine) => saveEntry({ oneLine })} spot={`e|${entry.id}|@oneLine`} placeholder="一句话说清这是谁、这是什么" className="mt-3 font-serif text-lg leading-relaxed text-ink-2 2xl:text-xl" />
      <MetaRow readOnly={readOnly} items={[
        ...facts.map(([label, value, placeholder, key]) => ({ label, value, placeholder, onSave: field(key ?? label) })),
        ...(holder ? [{ label: '谁在用', value: holder.name, link: () => nav.openEntry(holder.id) }] : []),
      ]} />
      {now.length > 0 && (
        <div className="mt-6 rounded-xl bg-subtle px-5 py-3.5">
          <p className="text-xs text-ink-3">此刻 · 设定师每写完一章更新</p>
          <p className="mt-1.5 flex flex-wrap gap-x-6 gap-y-1 text-[15px] text-ink">
            {now.map(([label, value]) => <span key={label}><span className="mr-1.5 text-ink-3">{label}</span>{value}</span>)}
          </p>
        </div>
      )}
      {(sections.length > 0 || (people && !draft)) && (
        <div className="mt-8 space-y-8 border-t border-line pt-8">
          {sections.map((f) => (
            <Section key={f.key ?? f.label} field={f} readOnly={readOnly} onSave={field(f.key ?? f.label)} spot={`e|${entry.id}|${f.key ?? f.label}`}>
              {['身世', '来历'].includes(f.key ?? f.label) && secret && <div className="mt-2"><LinkChip icon={<Lock className="size-3" />} onClick={() => nav.openEntry(secret.id)}>另有秘密：{secret.name}</LinkChip></div>}
              {(f.key ?? f.label) === '能力' && goldfinger && <div className="mt-2"><LinkChip onClick={() => nav.openEntry(goldfinger.id)}>金手指：{goldfinger.name}</LinkChip></div>}
            </Section>
          ))}
          {people && !draft && (!readOnly || relations.length > 0) && <Relations book={book} entry={entry} nav={nav} readOnly={readOnly} />}
        </div>
      )}
      <AppearsRow items={entry.appears} nav={nav} />
    </section>
  )
}

/** 段落类和阶梯的一张卡：一个名字加一段话（或一级一级）。 */
function PlainCard({ book, entry, category, nav, fresh }: { book: VBook; entry: VEntry; category?: VCategory; nav: Nav; fresh: boolean }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const saveEntry = useEntrySaver(entry)
  const parent = entry.parent ? findEntry(book, entry.parent) : undefined
  const example = category?.example
  const draft = entry.id.startsWith('draft-')
  const levels = entry.levels ?? []
  const [newLevel, setNewLevel] = useState(-1)
  const onlyContent = entry.sections.length === 1 && (entry.sections[0].key ?? entry.sections[0].label) === '内容'
  const setLevel = (i: number, part: 'name' | 'text', value: string) => saveEntry({ levels: levels.map((l, j) => (j === i ? { ...l, [part]: value } : l)) })
  return (
    <section id={`entry-${entry.id}`} data-entry={entry.id} className={clsx(paperCard, 'group/card relative scroll-mt-6')}>
      <CardMenu locked={entry.locked} onLock={draft ? undefined : () => saveEntry({ locked: !entry.locked })}
        onDelete={() => save(actions.deleteEntry(entry))} deleteLabel={draft ? '不要这一条了' : '删掉这一条'} />
      <PendingNote id={entry.id} />
      <div className="flex flex-wrap items-center gap-3 pr-20">
        <Editable autoFocus={fresh} value={entry.name} placeholder={example ? `起个名字，比如「${example.name}」` : '起个名字'} className={titleClass}
          onSave={(name) => { if (name.trim()) saveEntry({ name }) }} />
        <Tags entry={entry} />
      </div>
      <DraftNote entry={entry} />
      <MetaRow items={[
        ...(parent ? [{ label: '属于', value: parent.name, link: () => nav.openEntry(parent.id) }] : []),
        ...entry.facts.map(([label, value, placeholder, key]) => ({ label, value, placeholder, onSave: (text: string) => saveEntry({ fields: { [key ?? label]: text } }) })),
      ]} />
      <div className="mt-8 space-y-8 border-t border-line pt-8">
        {entry.kind === 'ladder' ? (
          <>
            <Prose value={entry.overview ?? ''} onSave={(overview) => saveEntry({ overview })} spot={`e|${entry.id}|@overview`} placeholder="总的说一句：怎么往上升、越级多难、有什么代价" />
            <ol>
              {levels.map((level, i) => (
                <li key={i} className="group/level relative flex gap-5 pb-7">
                  <span className="absolute top-9 bottom-0 left-[17px] w-px bg-line-2" />
                  <span className="relative flex size-9 shrink-0 items-center justify-center rounded-full border border-line-2 bg-card font-serif text-[15px] text-ink-2">{i + 1}</span>
                  <div className="min-w-0 flex-1 pt-1">
                    <Editable autoFocus={i === newLevel} value={level.name} onSave={(v) => setLevel(i, 'name', v)} placeholder="这一级叫什么" className="font-serif text-lg font-bold" />
                    <Editable value={level.text} onSave={(v) => setLevel(i, 'text', v)} spot={`l|${entry.id}|${i}`} placeholder="这一级能做到什么，先空着也行" className="mt-1 font-serif text-[17px] leading-[1.9] text-ink-2" />
                  </div>
                  <button type="button" onClick={() => saveEntry({ levels: levels.filter((_, j) => j !== i) })} aria-label="删掉这一级" title="删掉这一级"
                    className="mt-1.5 h-fit shrink-0 rounded p-1 text-ink-3 opacity-0 transition-opacity group-hover/level:opacity-100 hover:text-ink focus-visible:opacity-100">
                    <X className="size-4" />
                  </button>
                </li>
              ))}
              {/* 加一级：就是阶梯上虚线画的下一级 */}
              <li>
                <button type="button" onClick={() => { setNewLevel(levels.length); saveEntry({ levels: [...levels, { name: '', text: '' }] }) }}
                  className="group flex items-center gap-5 text-left">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full border border-dashed border-line-2 text-ink-3 transition-colors group-hover:border-ink-3 group-hover:text-ink">
                    <Plus className="size-4" />
                  </span>
                  <span className="font-serif text-[17px] text-ink-3 transition-colors group-hover:text-ink">再往上加一级</span>
                </button>
              </li>
            </ol>
          </>
        ) : onlyContent ? (
          <Prose value={entry.sections[0].text} onSave={(text) => saveEntry({ fields: { 内容: text } })} spot={`e|${entry.id}|内容`} placeholder={example ? `比如：\n${example.text}` : '写这一条的内容，可以一条条列'} />
        ) : (
          entry.sections.map((f) => <Section key={f.key ?? f.label} field={f} onSave={(text) => saveEntry({ fields: { [f.key ?? f.label]: text } })} spot={`e|${entry.id}|${f.key ?? f.label}`} />)
        )}
      </div>
      <AppearsRow items={entry.appears} nav={nav} />
    </section>
  )
}

function WorldPage({ book }: { book: VBook }) {
  const { actions } = useWorkspace()
  const save = useSave()
  return (
    <Sheet narrow>
      <Crumb items={['设定']} />
      <h1 className="font-serif text-[34px] font-bold 2xl:text-[38px]">世界概况</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-3">整个世界一段话说清：什么时代、超凡的力量公开还是藏着、钱用什么、普通人过得怎么样。一本书只有这一篇。</p>
      <div className="mt-8 border-t border-line pt-8">
        <Prose value={book.world} onSave={(text) => save(actions.saveWorld(text))} spot="w" placeholder={'比如：\n九天大陆，以武为尊，宗门、世家、王朝并立。钱用灵石，灵石也是修炼资源。凡人活不过百岁，武者靠境界续命。'} />
      </div>
    </Sheet>
  )
}

type AskResult = { name: string; text?: string; item?: DraftItem; taken?: boolean; dropped?: boolean }
type AskMemory = { want: string; state: 'ask' | 'writing' | 'done'; results: AskResult[]; note: string; error: string }
/** 写出来的候选先记在这里：切到别的类再回来，还在 */
const askMemory = new Map<string, AskMemory>()

/** 一条候选：和自己写的卡片一样，名字、名字下面的小字、正文一栏一栏。 */
function DraftPreview({ item, template }: { item: DraftItem; template: CardTemplate }) {
  // 人物多一格开局的实力与地位，收下后在「此刻」里
  const now = item.values['实力与地位'] && !template.facts.some((f) => f.key === '实力与地位') ? [{ key: '实力与地位', label: '实力与地位' }] : []
  const facts = [...template.facts, ...now].filter((f) => item.values[f.key])
  const sections = template.sections.filter((f) => item.values[f.key])
  return (
    <>
      <p className="font-serif text-[17px] font-bold text-ink">{item.name}</p>
      {facts.length > 0 && (
        <p className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
          {facts.map((f) => <span key={f.key}><span className="mr-1.5 text-ink-3">{f.label}</span><span className="text-ink-2">{item.values[f.key]}</span></span>)}
        </p>
      )}
      {item.values['总说明'] && <p className="mt-1.5 font-serif text-[15px] leading-[1.9] whitespace-pre-line text-ink-2">{item.values['总说明']}</p>}
      {item.levels.length > 0 && (
        <ol className="mt-2 space-y-1 font-serif text-[15px] leading-[1.8] text-ink-2">
          {item.levels.map((level, i) => <li key={i}><span className="mr-2 text-ink-3">{i + 1}</span><span className="font-bold text-ink">{level.name}</span>{level.text && `：${level.text}`}</li>)}
        </ol>
      )}
      {sections.map((f) => (
        <div key={f.key} className="mt-2.5">
          {!(sections.length === 1 && f.key === '内容') && <p className="text-xs tracking-[0.15em] text-ink-3">{f.label}</p>}
          <p className="mt-0.5 font-serif text-[15px] leading-[1.9] whitespace-pre-line text-ink-2">{item.values[f.key]}</p>
        </div>
      ))}
    </>
  )
}

/** 让编辑部写几条：先说想要什么，写出来的每一条和自己写的一样，挑着收下。 */
function AskPanel({ book, category, onAccept, onClose }: { book: VBook; category: VCategory; onAccept: (items: { name: string; text: string }[]) => void; onClose: () => void }) {
  const { actions, report } = useWorkspace()
  const key = `${book.id}:${category.key}`
  const template = templateOf(book, category)
  const [memory, setMemory] = useState<AskMemory>(() => askMemory.get(key) ?? { want: '', state: 'ask', results: [], note: '', error: '' })
  const update = (change: Partial<AskMemory>) => setMemory((m) => {
    const next = { ...m, ...change }
    askMemory.set(key, next)
    return next
  })
  const { want, state, results, note, error } = memory
  const write = () => {
    update({ state: 'writing', error: '' })
    if (!actions.draft) {
      setTimeout(() => update({ results: fakeResults(category, want), state: 'done' }), 1200)
      return
    }
    actions.draft(category, template, want.trim())
      .then((reply) => update({ results: reply.entries.map((item) => ({ name: item.name, item })), note: reply.note, state: 'done' }))
      .catch((err: unknown) => update({ state: 'ask', error: errorText(err) }))
  }
  const mark = (picked: AskResult[], change: Partial<AskResult>) => update({ results: results.map((r) => (picked.includes(r) ? { ...r, ...change } : r)) })
  const take = (picked: AskResult[]) => {
    mark(picked, { taken: true })
    const real = picked.filter((r) => r.item)
    if (!real.length) {
      onAccept(picked.map((r) => ({ name: r.name, text: r.text ?? '' })))
      return
    }
    // 收下一条就是新增一条，来源记成从候选里收下的
    for (const r of real) {
      actions.createEntry(category, draftToEntry(category, template, r.item!), { fromCandidate: true }).catch((err: unknown) => {
        report(err)
        update({ results: results.map((x) => (x.name === r.name ? { ...x, taken: false } : x)) })
      })
    }
  }
  const left = results.filter((r) => !r.taken && !r.dropped)
  return (
    <div className="rounded-2xl border border-line bg-subtle p-5">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-full bg-lore font-serif text-xs text-on-role">设</span>
        <p className="text-[15px] text-ink">想让编辑部在「{category.name}」里写点什么？</p>
        <button type="button" onClick={onClose} className="ml-auto text-[13px] text-ink-3 hover:text-ink">收起</button>
      </div>
      {state !== 'done' && (
        <>
          <textarea value={want} onChange={(e) => update({ want: e.target.value })} rows={2} disabled={state === 'writing'}
            placeholder="说说你想要什么，比如：写三条跟寿命有关的规矩，要有代价。不写也行，编辑部按简介和已有的设定来。"
            className="w-full resize-none rounded-xl border border-line-2 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
          {error && <p className="mt-2 text-[13px] text-seal">没写成：{error}</p>}
          <div className="mt-3 flex items-center justify-between gap-4">
            <p className="text-xs text-ink-3">写出来的每一条和你自己新增的一样，你挑着收下；不收的不会放进书里。</p>
            <button type="button" onClick={write} disabled={state === 'writing'}
              className="h-9 shrink-0 rounded-lg bg-ink px-5 text-sm text-paper-2 transition-colors hover:bg-ink-2 disabled:opacity-60">
              {state === 'writing' ? '编辑部在写…' : '写'}
            </button>
          </div>
        </>
      )}
      {state === 'done' && (
        <div className="space-y-3">
          {!results.length && <p className="text-[14px] text-ink-2">这一批写的都和书里已有的重名了，再写一批试试。</p>}
          {results.map((r, i) => (
            <div key={r.name + i} className={clsx('rounded-xl border bg-card px-5 py-4 transition-opacity', r.dropped ? 'opacity-40' : 'border-line')}>
              {r.item ? <DraftPreview item={r.item} template={template} /> : (
                <>
                  <p className="font-serif text-[17px] font-bold text-ink">{r.name}</p>
                  <p className="mt-1.5 font-serif text-[15px] leading-[1.9] whitespace-pre-line text-ink-2">{r.text}</p>
                </>
              )}
              <div className="mt-3 flex gap-2 text-[13px]">
                {r.taken ? <span className="text-lore">已收下</span> : r.dropped ? <span className="text-ink-3">不要了</span> : (
                  <>
                    <button type="button" onClick={() => take([r])} className="rounded-md bg-ink px-3 py-1 text-paper-2 hover:bg-ink-2">收下</button>
                    <button type="button" onClick={() => mark([r], { dropped: true })} className="rounded-md px-3 py-1 text-ink-2 hover:bg-subtle">不要</button>
                  </>
                )}
              </div>
            </div>
          ))}
          {note && <p className="text-[13px] leading-relaxed text-ink-3">{note}</p>}
          <div className="flex items-center gap-3">
            {left.length > 1 && (
              <button type="button" onClick={() => take(left)}
                className="h-9 rounded-lg border border-line-2 bg-card px-4 text-sm text-ink hover:border-ink-3/50">剩下的全部收下</button>
            )}
            <button type="button" onClick={() => update({ state: 'ask', results: [], note: '' })} className="text-[13px] text-ink-3 hover:text-ink">都不满意，再写一批</button>
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

/** 一组栏目：每一栏能改名、上下挪、删掉；最下面能加一栏。改名在离开输入框时存，其余点了就存。 */
function FieldList({ title, note, items, counts, locked, onEdit, onCommit, addPlaceholder }: {
  title: string; note: string; items: FieldItem[]; counts: Record<string, number>; locked: string[]
  onEdit: (items: FieldItem[]) => void; onCommit: (items: FieldItem[], dropped?: string[]) => void; addPlaceholder: string
}) {
  const [draft, setDraft] = useState('')
  const [confirming, setConfirming] = useState('')
  const move = (i: number, to: number) => {
    if (to < 0 || to >= items.length) return
    const next = [...items]
    ;[next[i], next[to]] = [next[to], next[i]]
    onCommit(next)
  }
  const add = () => {
    const label = draft.trim()
    if (!label || items.some((f) => f.label === label)) return
    onCommit([...items, { key: label, label }])
    setDraft('')
  }
  return (
    <section>
      <h4 className="text-sm font-medium text-ink">{title}</h4>
      <p className="mt-0.5 mb-2.5 text-xs text-ink-3">{note}</p>
      <div className="divide-y divide-line/70 rounded-xl border border-line">
        {items.map((item, i) => {
          const used = counts[item.key] ?? 0
          const fixed = locked.includes(item.key)
          return (
            <div key={item.key} className="flex items-center gap-2 px-3 py-1.5">
              <div className="flex flex-col">
                <button type="button" onClick={() => move(i, i - 1)} disabled={i === 0} className="rounded text-ink-3 hover:text-ink disabled:opacity-25" aria-label="往上挪"><ChevronUp className="size-3.5" /></button>
                <button type="button" onClick={() => move(i, i + 1)} disabled={i === items.length - 1} className="rounded text-ink-3 hover:text-ink disabled:opacity-25" aria-label="往下挪"><ChevronDown className="size-3.5" /></button>
              </div>
              <input value={item.label} disabled={fixed} maxLength={12}
                onChange={(e) => onEdit(items.map((f) => (f.key === item.key ? { ...f, label: e.target.value } : f)))}
                onBlur={() => onCommit(items)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) e.currentTarget.blur() }}
                className="h-8 min-w-0 flex-1 rounded-md bg-transparent px-2 font-serif text-[15px] text-ink hover:bg-subtle focus:bg-subtle focus:outline-none disabled:text-ink-2" />
              <span className="w-16 shrink-0 text-right text-xs text-ink-3 tabular-nums">{used ? `${used} 条写了` : ''}</span>
              {fixed ? <span className="w-20 shrink-0 text-right text-xs text-ink-3">按它分组</span> : (
                <button type="button"
                  onClick={() => {
                    if (used && confirming !== item.key) return setConfirming(item.key)
                    setConfirming('')
                    onCommit(items.filter((f) => f.key !== item.key), [item.key])
                  }}
                  className={clsx('w-20 shrink-0 rounded-md px-2 py-1 text-right text-xs transition-colors', confirming === item.key ? 'text-seal' : 'text-ink-3 hover:text-ink')}>
                  {confirming === item.key ? '再点一次删' : '删掉'}
                </button>
              )}
            </div>
          )
        })}
        <div className="flex items-center gap-2 px-3 py-2">
          <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={12} placeholder={addPlaceholder}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) add() }}
            className="h-8 min-w-0 flex-1 bg-transparent px-1 text-[15px] text-ink placeholder:text-ink-3 focus:outline-none" />
          <button type="button" onClick={add} disabled={!draft.trim()} className={clsx(smallButton, 'h-7 px-3')}>加上</button>
        </div>
      </div>
    </section>
  )
}

/** 这本书这一类有哪几栏：自己增删、改名、挪顺序，对这一类每一条都生效。 */
function CardTemplateEditor({ category, template, counts, onClose }: {
  category: VCategory; template: CardTemplate; counts: Record<string, number>; onClose: () => void
}) {
  const { actions } = useWorkspace()
  const save = useSave()
  const people = category.name === '角色列表' && !category.custom
  const [draft, setDraft] = useState(template)
  const synced = useRef(JSON.stringify(template))
  // 存好以后服务器给回来的栏目（改名的栏目 key 会跟着换）
  useEffect(() => {
    const text = JSON.stringify(template)
    if (text !== synced.current) {
      synced.current = text
      setDraft(template)
    }
  }, [template])
  const commit = (next: CardTemplate, dropped: string[] = []) => {
    // 名字删空了就用回原来的
    const fix = (items: FieldItem[]) => items.map((f) => ({ ...f, label: f.label.trim() || f.key }))
    const clean = { facts: fix(next.facts), sections: fix(next.sections) }
    setDraft(clean)
    if (JSON.stringify(clean) === synced.current && !dropped.length) return
    synced.current = JSON.stringify(clean)
    save(actions.saveTemplate(category, clean, dropped))
  }
  return (
    <div className="rounded-2xl border border-line bg-card p-6 shadow-[var(--shadow-paper)]">
      <div className="mb-1 flex items-center gap-3">
        <p className="text-[15px] font-medium text-ink">{people ? '这本书的角色卡有哪几栏' : `这本书的「${category.name}」每一条有哪几栏`}</p>
        <button type="button" onClick={() => save(actions.resetTemplate(category))} className="ml-auto text-[13px] text-ink-3 hover:text-ink">恢复默认</button>
        <button type="button" onClick={onClose} className="text-[13px] text-ink-3 hover:text-ink">收起</button>
      </div>
      <p className="mb-5 text-[13px] leading-relaxed text-ink-3">改了对这本书这一类的每一条都生效；改名不丢已经写的内容。删掉的栏目，写了的内容会一起删掉。只剩一栏「内容」时，卡片上就是名字加一段话。</p>
      <div className="grid gap-6 md:grid-cols-2">
        <FieldList title="名字下面的小字" note="短的，一两个词能说完的" items={draft.facts} counts={counts} locked={[]}
          onEdit={(facts) => setDraft({ ...draft, facts })} onCommit={(facts, dropped) => commit({ ...draft, facts }, dropped)}
          addPlaceholder={people ? '加一栏，比如：武器、坐骑、职业' : '加一栏，比如：品阶、产地'} />
        <FieldList title="正文栏目" note="要写一段话的" items={draft.sections} counts={counts} locked={[]}
          onEdit={(sections) => setDraft({ ...draft, sections })} onCommit={(sections, dropped) => commit({ ...draft, sections }, dropped)}
          addPlaceholder={people ? '加一栏，比如：口头禅、名场面' : '加一栏，比如：用法、来历'} />
      </div>
      {people && <p className="mt-4 text-xs text-ink-3">「此刻」那几栏（实力与地位、在哪、处境、眼下想要）由设定师每写完一章更新，不在这里改；开局的实力与地位，编辑部帮写、补齐人物时会先写上。</p>}
    </div>
  )
}

/** 一类的设定连成一页：每条一张白卡片往下排；点左边滚过去，往下滚左边跟着选中。 */
function CategoryStream({ book, category, next, nav, fresh, scrollReq, onSpy, onNewEntry, onAccept, pageRef, cardKey }: {
  book: VBook; category: VCategory; next?: VCategory; nav: Nav; fresh: string
  scrollReq: ScrollReq | null; onSpy: (id: string) => void; onNewEntry: () => void
  onAccept: (items: { name: string; text: string }[]) => void; pageRef: React.RefObject<HTMLElement | null>
  /** 新建的一条存好以后换了 id，卡片还用原来的 key，正在打的字不丢 */
  cardKey: (id: string) => string
}) {
  const [asking, setAsking] = useState(false)
  const [editing, setEditing] = useState(false)
  const pauseUntil = useRef(0)
  const spy = useRef(onSpy)
  spy.current = onSpy
  const ladder = isLadder(category)

  // 点了左边的某一条：滚到那张卡；点的是类别就回到顶上
  useEffect(() => {
    const root = pageRef.current
    if (!root || !scrollReq) return
    pauseUntil.current = Date.now() + (scrollReq.smooth ? 900 : 200)
    const card = document.getElementById(`entry-${scrollReq.id}`)
    if (card) card.scrollIntoView({ behavior: scrollReq.smooth ? 'smooth' : 'auto', block: 'start' })
    else root.scrollTo({ top: 0, behavior: scrollReq.smooth ? 'smooth' : 'auto' })
  }, [scrollReq, pageRef])

  // 自己往下滚：哪张卡到了屏幕上方三分之一，左边就选中它；滚到底选最后一张
  useEffect(() => {
    const root = pageRef.current
    if (!root) return
    let frame = 0
    const check = () => {
      frame = 0
      if (Date.now() < pauseUntil.current) return
      const cards = [...root.querySelectorAll<HTMLElement>('[data-entry]')]
      if (!cards.length) return
      const line = root.getBoundingClientRect().top + root.clientHeight * 0.3
      let current = `cat:${category.name}`
      for (const card of cards) {
        if (card.getBoundingClientRect().top <= line) current = card.dataset.entry!
        else break
      }
      if (root.scrollTop + root.clientHeight >= root.scrollHeight - 4) current = cards[cards.length - 1].dataset.entry!
      spy.current(current)
    }
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(check) }
    root.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      root.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(frame)
    }
  }, [category.name, pageRef])

  const counts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const e of category.entries) {
      for (const f of e.facts) if (f[1]) out[f[3] ?? f[0]] = (out[f[3] ?? f[0]] ?? 0) + 1
      for (const s of e.sections) if (s.text) out[s.key ?? s.label] = (out[s.key ?? s.label] ?? 0) + 1
    }
    return out
  }, [category.entries])

  return (
    <div className="mx-auto w-full max-w-[880px] px-8 pt-10 pb-[40vh] 2xl:max-w-[940px] 2xl:pt-12">
      <header className="mb-8 px-2">
        <Crumb items={['设定']} />
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <h1 className="font-serif text-[32px] font-bold 2xl:text-[36px]">
              {category.name}
              {category.entries.length > 0 && <span className="ml-3 font-sans text-base font-normal text-ink-3">{category.entries.length} 条</span>}
            </h1>
            <p className="mt-2 text-[15px] leading-relaxed text-ink-3">{category.about}</p>
          </div>
          <div className="flex shrink-0 gap-2">
            {!ladder && (
              <button type="button" onClick={() => setEditing(!editing)} className={clsx('h-9 rounded-lg px-3 text-sm transition-colors', editing ? 'bg-line/60 text-ink' : 'text-ink-3 hover:text-ink')}>
                调整栏目
              </button>
            )}
            <AskButton onClick={() => setAsking(!asking)}>编辑部帮写</AskButton>
            <button type="button" onClick={onNewEntry} className="h-9 rounded-lg bg-ink px-4 text-sm text-paper-2 transition-colors hover:bg-ink-2">
              新增{nounOf(category.name)}
            </button>
          </div>
        </div>
        {!ladder && editing && <div className="mt-5"><CardTemplateEditor category={category} template={templateOf(book, category)} counts={counts} onClose={() => setEditing(false)} /></div>}
        {asking && <div className="mt-5"><AskPanel book={book} category={category} onAccept={onAccept} onClose={() => setAsking(false)} /></div>}
      </header>

      <div className="space-y-6">
        {orderEntries(category).map((entry) => (entry.kind === 'character' || entry.kind === 'goldfinger'
          ? <CharacterCard key={cardKey(entry.id)} book={book} entry={entry} nav={nav} fresh={fresh === entry.id} />
          : <PlainCard key={cardKey(entry.id)} book={book} entry={entry} category={category} nav={nav} fresh={fresh === entry.id} />))}
        {!category.entries.length && category.example && (
          <div className="rounded-xl border border-dashed border-line-2 px-12 py-10">
            <p className="mb-3 text-xs tracking-wider text-ink-3">比如这样写一条</p>
            <p className="font-serif text-[26px] font-bold text-ink-3">{category.example.name}</p>
            <p className="mt-4 font-serif text-[17px] leading-[1.95] whitespace-pre-line text-ink-3">{category.example.text}</p>
          </div>
        )}
      </div>

      {next && (
        <button type="button" onClick={() => nav.openEntry(`cat:${next.name}`)}
          className="mt-10 ml-auto flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
          下一类：{next.name}<ChevronRight className="size-4" />
        </button>
      )}
    </div>
  )
}

/** 设定总览：空书点完「下一步」先看到这里；有内容的书点目录上的「设定」也到这里。 */
function SettingsOverview({ book, nav, onSelect }: { book: VBook; nav: Nav; onSelect: (id: string) => void }) {
  const { actions } = useWorkspace()
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
      {!total && !actions.live && (
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
          <button key={cat.key} type="button" onClick={() => onSelect(cat.entries[0]?.id ?? `cat:${cat.name}`)}
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

/** 一篇、一卷、一个单元、一章 */
const ONE: Record<VNode['kind'], string> = { 全书: '全书', 篇: '一篇', 卷: '一卷', 单元: '一个单元', 章: '一章' }

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

/** 节点的名字：前缀（第一卷）程序排，后面的名字作者起。 */
function NodeTitle({ node, fresh }: { node: VNode; fresh: boolean }) {
  const { actions } = useWorkspace()
  const save = useSave()
  if (node.kind === '全书') return <h1 className={titleClass}>全书</h1>
  const [prefix, name] = splitTitle(node.title)
  if (!node.title.includes('　')) return <h1 className={titleClass}>{prefix}</h1>
  return (
    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3">
      <span className={clsx(titleClass, 'shrink-0')}>{prefix}</span>
      <Editable value={name} autoFocus={fresh} readOnly={!actions.canEdit(node, 'name')} placeholder={`给${ONE[node.kind]}起个名字`} className={clsx(titleClass, 'min-w-24')}
        onSave={(text) => { if (node.kind !== '章' || text.trim()) save(actions.saveNode(node, { name: text.trim() })) }} />
    </div>
  )
}

/** 章数：单元和没拆单元的卷可以自己定，空着就是还没定（有几章算几章，写到这里编辑部按剧情定）。 */
function CountField({ node }: { node: VNode }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const have = node.children?.length ?? 0
  const range = node.range ? `第 ${node.range[0]}–${node.range[1]} 章` : ''
  const commit = () => {
    setEditing(false)
    const value = text.trim() ? Math.max(0, Math.floor(Number(text))) : 0
    if (!Number.isNaN(value) && value !== (node.count ?? 0)) save(actions.saveNode(node, { chapters: value }))
  }
  if (editing) {
    return (
      <span className="flex items-baseline gap-2">
        <input autoFocus type="number" min={have} max={node.kind === '单元' ? 50 : 1000} value={text} onChange={(e) => setText(e.target.value)}
          onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          placeholder="还没定" className="h-8 w-24 rounded-md border border-line-2 bg-card px-2 text-[15px] text-ink focus:border-ink-3 focus:outline-none" />
        <span className="text-[13px] text-ink-3">章；空着就是还没定，写到这里编辑部按剧情定</span>
      </span>
    )
  }
  return (
    <button type="button" onClick={() => { setText(node.count ? String(node.count) : ''); setEditing(true) }}
      className="-mx-1.5 rounded-md px-1.5 text-[15px] text-ink transition-colors hover:bg-subtle" title="点一下自己定章数">
      {node.count ? `${node.count} 章` : have ? `${have} 章（章数还没定，有几章算几章）` : '还没定'}
      {range && <span className="ml-2 text-ink-3">{range}</span>}
    </button>
  )
}

/** 编辑部帮写这一段：说一句想要什么（不说也行），直接写进去，不满意点撤销。正在写的那一段记在这里，换页回来还看得到。 */
const writingNodes = new Set<string>()

function WriteHelp({ node }: { node: VNode }) {
  const { actions, notify } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [request, setRequest] = useState('')
  const [writing, setWriting] = useState(() => writingNodes.has(node.id))
  if (!actions.writeNode || !actions.canWrite?.(node)) return null
  const what = ({ 章: '这一章的章纲', 全书: '结局', 篇: '这一篇', 卷: '这一卷', 单元: '这个单元' } as Record<string, string>)[node.kind] ?? '这一段'
  const empty = node.sections ? node.sections.every((f) => !f.text.trim()) : !node.text.trim()
  const go = () => {
    const id = node.id
    writingNodes.add(id)
    setWriting(true)
    setOpen(false)
    actions.writeNode!(node, request.trim())
      .then((reply) => {
        setRequest('')
        notify?.(`编辑部写好了${what}${reply.note ? `：${reply.note}` : ''}`, () => actions.saveNode(node, reply.before))
      })
      .catch((error: unknown) => notify?.(`没写成：${errorText(error)}`))
      .finally(() => {
        writingNodes.delete(id)
        setWriting(false)
      })
  }
  if (writing) return <p className="flex items-center gap-2 text-[13px] text-chief"><span aria-hidden className="size-2 shrink-0 rounded-full bg-chief motion-safe:animate-pulse" />主编在写{what}，一般半分钟上下，写好直接换上…</p>
  if (!open) return <div><AskButton onClick={() => setOpen(true)}>{empty ? `编辑部帮写${what}` : `编辑部帮改写${what}`}</AskButton></div>
  return (
    <div className="rounded-2xl border border-line bg-subtle p-5">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-full bg-chief font-serif text-xs text-on-role">主</span>
        <p className="text-[15px] text-ink">想让{what}写成什么样？</p>
        <button type="button" onClick={() => setOpen(false)} className="ml-auto text-[13px] text-ink-3 hover:text-ink">收起</button>
      </div>
      <textarea autoFocus value={request} onChange={(e) => setRequest(e.target.value)} rows={2}
        placeholder={empty ? '比如：主角在这里第一次亮出金手指，要憋屈一阵再爆。不写也行，编辑部照前后的大纲和设定来。' : '比如：节奏快一点，结尾留个钩子。不写也行；你写过的意思都会留着，在上面补全写顺。'}
        className="w-full resize-none rounded-xl border border-line-2 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
      <div className="mt-3 flex items-center justify-between gap-4">
        <p className="text-xs text-ink-3">{node.kind === '章' || node.kind === '全书' ? '' : '名字你起过的就不换，'}写好直接换上；不满意，底下点撤销就换回原来的。</p>
        <button type="button" onClick={go} className="h-9 shrink-0 rounded-lg bg-ink px-5 text-sm text-paper-2 transition-colors hover:bg-ink-2">写</button>
      </div>
    </div>
  )
}

function OutlinePage({ book, outline, id, nav, onAdd, onInsert, onMove, fresh, writing }: {
  book: VBook; outline: VNode; id: string; nav: Nav; onAdd: (id: string) => void
  onInsert: (node: VNode, where: 'before' | 'after') => void; onMove: (node: VNode, direction: 'up' | 'down') => void; fresh: boolean
  /** 写作：这一页上有要拍板的就放拍板卡；写过的章能去读正文 */
  writing?: WritingControl
}) {
  const { actions } = useWorkspace()
  const save = useSave()
  const path = findNode(outline, id) ?? [outline]
  const node = path[path.length - 1]
  const child = childKind(node)
  const canAdd = actions.canAdd(node)
  const meta: { label: string; value: ReactNode }[] = []
  const editableCount = node.count !== undefined && actions.canEdit(node, 'name') && (node.kind === '单元' || node.kind === '卷')
  // 章号已经在章的标题里，不再列章数
  if (editableCount) meta.push({ label: '章数', value: <CountField node={node} /> })
  else if (node.kind !== '章') {
    // 下面还有单元章数没定：照实说，不让人以为整卷的章数已经定死
    const open = undecidedParts(node)
    const later = open.length ? `${open.length > 2 ? `还有 ${open.length} 个单元` : open.map((n) => splitTitle(n.title)[1] || splitTitle(n.title)[0]).join('、')}章数还没定，写到那里按剧情定` : ''
    const have = node.range ? `已有 ${node.range[1] - node.range[0] + 1} 章 · 第 ${node.range[0]}–${node.range[1]} 章` : ''
    if (have || later) meta.push({ label: '章数', value: [open.length ? have : have.replace('已有 ', ''), later].filter(Boolean).join('；') })
    else if (node.kind === '卷' || node.kind === '单元') meta.push({ label: '章数', value: '还没定' })
  }
  if (node.progress && node.progress !== '已规划') meta.push({ label: '写到', value: node.progress })
  if (writing && node.kind === '章' && node.body && node.body.status !== 'planned') {
    meta.push({
      label: '正文',
      value: <button type="button" onClick={() => nav.openChapter(node.id)} className="text-chief hover:underline">{node.body.status === 'done' ? `${node.body.words.toLocaleString()} 字 · 去读` : '写手在写 · 去看'}</button>,
    })
  }
  const split = useSplit(node)
  const status = writing?.status
  const gate = status?.state === 'waiting' && status.gate && gateTarget(status.gate).node === node.id ? status.gate : undefined
  const one = ONE[node.kind]
  const arrange = actions.canArrange(node) ? [
    { label: `在前面插${one}`, onClick: () => onInsert(node, 'before') },
    { label: `在后面插${one}`, onClick: () => onInsert(node, 'after') },
    { label: '上移', onClick: () => onMove(node, 'up') },
    { label: '下移', onClick: () => onMove(node, 'down') },
  ] : []
  return (
    <Sheet narrow>
      {node.ref && <PendingNote id={node.ref.id} />}
      {(actions.canDelete(node) || arrange.length > 0) && (
        <CardMenu items={arrange} onDelete={actions.canDelete(node) ? () => {
          nav.openNode(path.at(-2)?.id ?? 'book')
          save(actions.deleteNode(node))
        } : undefined} deleteLabel={`删掉这${one.slice(1)}`} />
      )}
      <Crumb items={['大纲', ...path.slice(0, -1).map(shownTitle)]} />
      <div className="flex flex-wrap items-center gap-3 pr-8">
        <NodeTitle node={node} fresh={fresh} />
        {node.later && <span className="rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2">写到再定</span>}
        {node.locked && <span className="flex items-center gap-1 rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2"><Lock className="size-3" />锁住，AI 规划时不改</span>}
      </div>
      {meta.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-x-7 gap-y-2">
          {meta.map((m) => <span key={m.label} className="flex items-baseline gap-2"><span className="text-[13px] text-ink-3">{m.label}</span><span className="text-[15px] text-ink">{m.value}</span></span>)}
        </div>
      )}
      <div className="mt-8 space-y-8 border-t border-line pt-8">
        {gate && writing && <GateCard gate={gate} writing={writing} nav={nav} />}
        {node.sections
          ? node.sections.map((field) => (
            <Section key={field.label} field={field} readOnly={!actions.canEdit(node, 'text')}
              onSave={(text) => save(actions.saveNode(node, { sections: { [field.label]: text } }))} />
          ))
          : <Prose value={node.text} readOnly={!actions.canEdit(node, 'text')} spot={`n|${node.id}`} placeholder={NODE_PLACEHOLDER[node.kind]}
            onSave={(text) => save(actions.saveNode(node, { text }))} />}
        <WriteHelp node={node} />
        {child && (canAdd || !!node.children?.length) && (
          <section>
            <h3 className="mb-1 text-[13px] tracking-[0.15em] text-ink-3">下面的{child}{node.children?.length ? ` · ${node.children.length} 个` : ''}</h3>
            {KIND_NOTE[child] && <p className="mb-2 text-xs text-ink-3">{KIND_NOTE[child]}</p>}
            {!!node.children?.length && (
              <div className="divide-y divide-line border-y border-line">
                {node.children.map((c) => (
                  <button key={c.id} type="button" onClick={() => nav.openNode(c.id)} className="group flex w-full items-baseline gap-5 py-3.5 text-left">
                    <span className={clsx('w-44 shrink-0 truncate font-serif text-[16px] font-bold group-hover:text-seal', c.later ? 'text-ink-3' : 'text-ink')}>{shownTitle(c)}</span>
                    <span className="line-clamp-1 flex-1 text-[14px] text-ink-3">{(c.text || c.sections?.[0]?.text || '').split('\n')[0] || '还没写'}</span>
                    {c.range && c.kind !== '章' && <span className="text-xs text-ink-3 tabular-nums">{c.range[1] - c.range[0] + 1} 章</span>}
                  </button>
                ))}
              </div>
            )}
            <div className="mt-4 flex flex-wrap gap-3">
              {canAdd && (
                <button type="button" onClick={() => onAdd(node.id)} className="h-9 rounded-lg bg-ink px-4 text-sm text-paper-2 transition-colors hover:bg-ink-2">
                  新增{child}
                </button>
              )}
              {split.available && split.state.step === 'idle' && <AskButton onClick={split.open}>{split.label}</AskButton>}
            </div>
            <SplitPanel node={node} split={split} />
          </section>
        )}
      </div>
      {node.uses.length > 0 && (
        <div className="mt-8 flex flex-wrap items-center gap-2 border-t border-line pt-5 text-[13px] text-ink-3">
          <span className="mr-1">用到的设定</span>
          {node.uses.map((entryId) => {
            const entry = findEntry(book, entryId)
            return entry && <LinkChip key={entryId} onClick={() => nav.openEntry(entryId)}>{entry.name}</LinkChip>
          })}
        </div>
      )}
    </Sheet>
  )
}

/** 篇幅：打字时只改输入框，离开才存。存好以后书上的篇幅变了，换一个新的输入框。 */
function LengthField({ book, onSave }: { book: VBook; onSave: (length: number | null) => void }) {
  const [text, setText] = useState(book.length ? String(book.length) : '')
  return (
    <LengthInput text={text} chapterWords={book.chapterWords} onChange={(next) => setText(next)}
      onBlur={() => {
        const value = text ? Number(text) : null
        if (value !== (book.length ?? null)) onSave(value)
      }} />
  )
}

function BlurbPage({ book }: { book: VBook }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const meta = useBookMeta()
  return (
    <div className="flex min-h-full items-center justify-center px-6 py-10">
      <div className="w-full max-w-[780px] rounded-2xl border border-line bg-card shadow-[var(--shadow-lift)]">
        <div className="px-12 py-10">
          <Editable value={book.title} placeholder="书名" className="font-serif text-[34px] font-bold"
            onSave={(title) => save(actions.saveBook({ title: title.trim() }))} />
          <p className="mt-7 mb-2.5 text-sm text-ink-3">简介</p>
          <Editable multiline boxed value={book.blurb} spot="b" placeholder="写给读者看的那段话" className="rounded-xl bg-paper/45 px-5 py-4 font-serif text-[17px] leading-[1.95]"
            onSave={(blurb) => save(actions.saveBook({ blurb }))} />
          <div className="mt-5 divide-y divide-line border-y border-line">
            <Row label="类别">
              <CategoryPicker meta={meta} value={{ channel: book.channel as '男频' | '女频' | '', genre: book.genre }}
                onChange={(next) => save(actions.saveBook({ channel: next.channel, genre: next.genre }))} />
            </Row>
            <Row label="标签">
              <TagPicker meta={meta} channel={book.channel as '男频' | '女频' | ''} value={book.tags} onChange={(tags) => save(actions.saveBook({ tags }))} />
            </Row>
            <Row label="篇幅">
              <LengthField key={book.length ?? 'none'} book={book} onSave={(length) => save(actions.saveBook({ length }))} />
            </Row>
          </div>
          <p className="mt-5 text-[13px] text-ink-3">点哪改哪，改了就存。</p>
        </div>
      </div>
    </div>
  )
}

function countKinds(node: VNode, counts: Record<string, number> = {}): Record<string, number> {
  counts[node.kind] = (counts[node.kind] ?? 0) + 1
  if (node.kind === '章' && node.body?.status === 'done') {
    counts.written = (counts.written ?? 0) + 1
    counts.words = (counts.words ?? 0) + node.body.words
  }
  for (const child of node.children ?? []) countKinds(child, counts)
  return counts
}

/** 简介页左边那一栏：这本书的样子，和设定、大纲、正文各写了多少，点了过去。和别的页同宽，换页签时顶栏不跳。 */
function BookColumn({ book, outline, onTab, manuscript }: { book: VBook; outline: VNode; onTab: (tab: Tab) => void; manuscript: boolean }) {
  const facts = [book.genre, ...book.tags].filter(Boolean).join(' · ')
  const chapters = book.length ? Math.round((book.length * 10000) / book.chapterWords) : null
  const entries = book.categories.reduce((n, c) => n + c.entries.length, (book.world ? 1 : 0))
  const counts = countKinds(outline)
  const plan = [counts['篇'] && `${counts['篇']} 篇`, counts['卷'] && `${counts['卷']} 卷`, counts['章'] && `${counts['章']} 章`].filter(Boolean).join(' · ')
  const written = counts.written ? `已写 ${counts.written} 章 · ${counts.words >= 10000 ? `${(counts.words / 10000).toFixed(1)} 万字` : `${counts.words.toLocaleString()} 字`}` : '还没开写'
  const rows: [Tab, string, boolean][] = [['设定', entries ? `${entries} 条` : '还空着', true], ['大纲', plan || '还空着', true], ['正文', written, manuscript]]
  return (
    <SideColumn>
      <div className="flex h-14 items-end px-5 pb-3">
        <span className="text-xs tracking-[0.25em] text-ink-3">本书</span>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pb-20">
        <div className="flex flex-col items-center px-4 pt-5 pb-7 text-center">
          <BookCover title={book.title} seed={book.id === 'sample' ? '开新书' : book.id} size="md" className="shadow-[0_18px_28px_-16px_rgb(40_25_10/0.55)]" />
          <p className="mt-5 max-w-full truncate font-serif text-lg font-bold">{book.title || '未命名'}</p>
          <p className="mt-1 text-[13px] text-ink-3">{facts || '还没分类'}</p>
          {chapters && <p className="mt-0.5 text-[13px] text-ink-3">{book.length} 万字 · 约 {chapters} 章</p>}
        </div>
        <div className="border-t border-line pt-2">
          {rows.map(([tab, note, enabled]) => (
            <button key={tab} type="button" disabled={!enabled} onClick={() => onTab(tab)} title={enabled ? `去${tab}` : '开写以后才有'}
              className="flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm transition-colors enabled:hover:bg-line/50 disabled:cursor-not-allowed">
              <span className={enabled ? 'text-ink-2' : 'text-ink-3/60'}>{tab}</span>
              <span className="ml-auto truncate text-xs text-ink-3 tabular-nums">{note}</span>
            </button>
          ))}
        </div>
      </div>
    </SideColumn>
  )
}

/* ---------------- 编辑部 ---------------- */

/** 按窗口自身宽度收起工具文字，而非整页宽度；拖窄或放大界面时标题与按钮都不折行。 */
function ChatHeader({ dock, setDock, onDragStart, tools }: { dock: Dock; setDock: (dock: Dock) => void; onDragStart?: (e: ReactPointerEvent) => void; tools?: ReactNode }) {
  return (
    <div data-testid="editorial-header" className="@container/editorial-header relative shrink-0 border-b border-line">
      <div onPointerDown={onDragStart} className={clsx('flex h-14 items-center gap-2 px-3 @min-[500px]/editorial-header:gap-2.5 @min-[500px]/editorial-header:px-4', onDragStart && 'cursor-grab active:cursor-grabbing')}>
        <div aria-hidden="true" className="hidden shrink-0 -space-x-1.5 @min-[400px]/editorial-header:flex">
          {Object.keys(ROLE_STYLE).map((role) => (
            <span key={role} className={clsx('flex size-8 items-center justify-center rounded-full font-serif text-[13px] ring-2 ring-paper', ROLE_STYLE[role])} title={role}>{role[0]}</span>
          ))}
        </div>
        <span data-testid="editorial-title" className="shrink-0 whitespace-nowrap text-[15px] font-medium">编辑部</span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5 whitespace-nowrap">
          {tools}
          {dock === 'float' ? (
            <button type="button" onClick={() => setDock('side')} className="rounded-md p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" title="贴到右边" aria-label="贴到右边"><PanelRight className="size-4" /></button>
          ) : (
            <button type="button" onClick={() => setDock('float')} className="rounded-md p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" title="浮起来" aria-label="浮起来"><PictureInPicture2 className="size-4" /></button>
          )}
          <button type="button" onClick={() => setDock('ball')} className="rounded-md p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" title="收起" aria-label="收起"><Minus className="size-4" /></button>
        </div>
      </div>
    </div>
  )
}

function FloatingEditorial({ setDock, children, size, tools }: { setDock: (dock: Dock) => void; children: ReactNode; size: { width: number; height: number }; tools?: ReactNode }) {
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
      const z = zoomOf(ref.current)
      const w = ref.current.offsetWidth * z
      const h = ref.current.offsetHeight * z
      setPos({
        x: Math.min(Math.max(8, e.clientX - drag.current.dx), window.innerWidth - w - 8) / z,
        y: Math.min(Math.max(64 * z, e.clientY - drag.current.dy), window.innerHeight - h - 8) / z,
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
        data-testid="editorial-floating"
        className="fixed z-40 flex flex-col overflow-hidden rounded-2xl border border-line bg-paper shadow-[0_24px_60px_-20px_rgb(40_25_10/0.45),0_2px_6px_rgb(40_25_10/0.08)]"
        style={{ ...(pos ? { left: pos.x, top: pos.y } : { right: 16, bottom: 24 }), width: size.width, height: size.height, resize: 'both', minWidth: 'min(320px, calc(100vw / var(--desk-zoom) / var(--desk-scale) - 32px))', minHeight: 360, maxWidth: 'min(820px, calc(100vw / var(--desk-zoom) / var(--desk-scale) - 32px))', maxHeight: 'calc(85vh / var(--desk-zoom) / var(--desk-scale))' }}>
        <ChatHeader dock="float" setDock={setDock} onDragStart={start} tools={tools} />
        {children}
      </div>
    </>
  )
}

const SIDE_KEY = 'zhibi-prototype-chat-width'

function savedSideWidth(fallback: number): number {
  try {
    return Number(localStorage.getItem(SIDE_KEY)) || fallback
  } catch {
    return fallback
  }
}

/** 贴在右边的编辑部：左边缘可以拖宽拖窄，记住上次的宽度。 */
function DockedEditorial({ setDock, children, width, setWidth, tools }: { setDock: (dock: Dock) => void; children: ReactNode; width: number; setWidth: (width: number) => void; tools?: ReactNode }) {
  const ref = useRef<HTMLElement>(null)
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    if (!dragging) return
    const move = (e: PointerEvent) => {
      const z = zoomOf(ref.current)
      setWidth(Math.min(Math.max(320, (window.innerWidth - e.clientX) / z), Math.min(820, (window.innerWidth * 0.55) / z)))
    }
    const up = () => setDragging(false)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [dragging, setWidth])
  useEffect(() => {
    if (dragging) return
    try {
      localStorage.setItem(SIDE_KEY, String(Math.round(width)))
    } catch { /* 存不了就只管这一次 */ }
  }, [dragging, width])
  return (
    <aside ref={ref} data-testid="editorial-docked" className="relative flex shrink-0 flex-col border-l border-line bg-paper" style={{ width }}>
      <div onPointerDown={(e) => { e.preventDefault(); setDragging(true) }} title="拖动调宽窄"
        className={clsx('absolute inset-y-0 -left-1.5 z-10 w-3 cursor-col-resize after:absolute after:inset-y-0 after:left-1.5 after:w-0.5 after:transition-colors', dragging ? 'after:bg-chief/60' : 'hover:after:bg-chief/40')} />
      {dragging && <div className="fixed inset-0 z-50 cursor-col-resize" />}
      <ChatHeader dock="side" setDock={setDock} tools={tools} />
      {children}
    </aside>
  )
}

/* ---------------- 选中文字后冒出的小按钮 ---------------- */

/** 选中的字在哪：已经换算成页面里的位置；z 是那时候整页放大了几倍 */
type Picked = { x: number; top: number; bottom: number; z: number; spot?: string; start: number; end: number; text: string }

/** 选中的字在这一栏里从第几个字起：同样的字出现好几次时，挑离光标最近的那一处。 */
function locate(host: HTMLElement, range: Range, picked: string): [number, number] | null {
  const value = readText(host)
  const before = document.createRange()
  before.selectNodeContents(host)
  before.setEnd(range.startContainer, range.startOffset)
  const guess = before.toString().length
  let best = -1
  for (let at = value.indexOf(picked); at >= 0; at = value.indexOf(picked, at + 1)) {
    if (best < 0 || Math.abs(at - guess) < Math.abs(best - guess)) best = at
  }
  return best < 0 ? null : [best, best + picked.length]
}

/** 选中一栏里的几个字，旁边冒出三个按钮：改这一句（先说怎么改）、给我几个写法（挑一个换上）、写细一点。改好可以撤销。 */
function SelectionActions({ pageRef, onToast, onUndo }: {
  pageRef: React.RefObject<HTMLElement | null>; onToast: (text: string) => void; onUndo: (text: string, versionId?: string | null) => void
}) {
  const { actions } = useWorkspace()
  const live = !!actions.rewrite
  const [at, setAt] = useState<Picked | null>(null)
  const [step, setStep] = useState<'menu' | 'ask' | 'busy' | 'options'>('menu')
  const [instruction, setInstruction] = useState('')
  const [candidate, setCandidate] = useState<NonNullable<RewriteOutcome['candidate']> | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const stepRef = useRef(step)
  useEffect(() => { stepRef.current = step }, [step])
  const close = useCallback(() => {
    setAt(null)
    setStep('menu')
    setInstruction('')
    setCandidate(null)
  }, [])
  useEffect(() => {
    const up = (e: MouseEvent) => setTimeout(() => {
      // 正在说怎么改、在改、在挑写法：别处点一下不打断，点到外面由 mousedown 收起
      if (boxRef.current?.contains(e.target as Node) || stepRef.current !== 'menu') return
      const sel = window.getSelection()
      const text = sel?.toString() ?? ''
      if (!sel || sel.isCollapsed || !text.trim() || !pageRef.current?.contains(sel.anchorNode)) return setAt(null)
      const range = sel.getRangeAt(0)
      const rect = range.getBoundingClientRect()
      const common = range.commonAncestorContainer
      const host = (common instanceof Element ? common : common.parentElement)?.closest<HTMLElement>('[data-spot]')
      const z = zoomOf(pageRef.current)
      const where = { x: (rect.left + rect.width / 2) / z, top: rect.top / z, bottom: rect.bottom / z, z, text }
      if (!live) return setAt({ ...where, start: 0, end: 0 })
      // 只认一栏里的字：跨了几栏、或者这一处编辑部改不了，就不冒按钮
      const found = host && locate(host, range, text)
      if (!host || !found) return setAt(null)
      setAt({ ...where, spot: host.dataset.spot, start: found[0], end: found[1] })
    }, 0)
    const down = (e: MouseEvent) => {
      if (stepRef.current !== 'menu' && stepRef.current !== 'busy' && !boxRef.current?.contains(e.target as Node)) close()
    }
    const hide = () => { if (stepRef.current === 'menu') setAt(null) }
    document.addEventListener('mouseup', up)
    document.addEventListener('mousedown', down)
    const page = pageRef.current
    page?.addEventListener('scroll', hide)
    return () => {
      document.removeEventListener('mouseup', up)
      document.removeEventListener('mousedown', down)
      page?.removeEventListener('scroll', hide)
    }
  }, [pageRef, live, close])
  if (!at) return null

  const run = async (mode: RewriteMode) => {
    if (!at.spot || !actions.rewrite || (mode === 'instruction' && !instruction.trim())) return
    // 正在改的那一栏先存下来，编辑部按存好的字改
    const active = document.activeElement
    if (active instanceof HTMLElement && active.closest('[data-spot]')) active.blur()
    setStep('busy')
    try {
      const outcome = await actions.rewrite(at.spot, at.start, at.end, mode, instruction.trim(), at.text)
      if (outcome.candidate) {
        setCandidate(outcome.candidate)
        setStep('options')
        return
      }
      close()
      window.getSelection()?.removeAllRanges()
      onUndo(mode === 'expand' ? '写细了' : '照你说的改好了', outcome.revertVersionId)
    } catch (error) {
      setStep(mode === 'instruction' ? 'ask' : 'menu')
      onToast(`编辑部没改成：${errorText(error)}`)
    }
  }
  const choose = async (index: number) => {
    if (!candidate || !actions.chooseOption) return
    setStep('busy')
    try {
      const versionId = await actions.chooseOption(candidate.id, index)
      close()
      window.getSelection()?.removeAllRanges()
      onUndo('换上了', versionId)
    } catch (error) {
      setStep('options')
      onToast(`没换上：${errorText(error)}`)
    }
  }
  const labels = ['改这一句', '给我几个写法', '写细一点']
  const menuButton = 'rounded-lg px-2.5 py-1 text-[13px] text-ink-2 transition-colors hover:bg-subtle hover:text-ink'
  const panel = 'rounded-xl border border-line bg-card shadow-[var(--shadow-lift)]'
  // 宽的面板放在选中的字下面，别跑出屏幕
  const left = Math.min(Math.max(at.x, 240), window.innerWidth / at.z - 240)
  return (
    <div ref={boxRef} className="fixed z-50 -translate-x-1/2"
      style={step === 'menu' ? { left: at.x, top: at.top - 46 } : { left, top: Math.min(at.bottom + 10, window.innerHeight / at.z - 120) }}
      onMouseDown={(e) => { if (step === 'menu') e.preventDefault() }}>
      {step === 'menu' && (
        <div className={clsx(panel, 'flex items-center gap-0.5 p-1')}>
          <span className="ml-1 flex size-6 items-center justify-center rounded-full bg-lore font-serif text-[11px] text-on-role">设</span>
          {labels.map((label, i) => (
            <button key={label} type="button" className={menuButton} onClick={() => {
              if (!live) {
                setAt(null)
                onToast(`原型：「${label}」会让编辑部只改你选中的这几个字，改好在原地给你挑`)
              } else if (i === 0) setStep('ask')
              else void run(i === 1 ? 'options' : 'expand')
            }}>
              {label}
            </button>
          ))}
        </div>
      )}
      {step === 'ask' && (
        <div className={clsx(panel, 'w-[380px] p-3')}>
          <p className="mb-2 line-clamp-2 text-[13px] text-ink-3">改「{at.text}」</p>
          <input autoFocus value={instruction} onChange={(e) => setInstruction(e.target.value)} maxLength={200}
            placeholder="想怎么改？比如：更狠一点、换个说法、加个代价"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) void run('instruction')
              if (e.key === 'Escape') close()
            }}
            className="h-9 w-full rounded-lg border border-line-2 bg-card px-3 text-sm text-ink placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
          <div className="mt-2.5 flex justify-end gap-2">
            <button type="button" onClick={close} className="h-8 rounded-lg px-3 text-[13px] text-ink-2 hover:bg-subtle">取消</button>
            <button type="button" onClick={() => void run('instruction')} disabled={!instruction.trim()}
              className="h-8 rounded-lg bg-ink px-4 text-[13px] text-paper-2 hover:bg-ink-2 disabled:opacity-40">改</button>
          </div>
        </div>
      )}
      {step === 'busy' && <div className={clsx(panel, 'px-4 py-2 text-[13px] text-ink-2')}>编辑部在改…</div>}
      {step === 'options' && candidate && (
        <div className={clsx(panel, 'max-h-[60vh] w-[440px] overflow-y-auto p-3')}>
          <p className="mb-2 text-[13px] text-ink-3">挑一个换上「{at.text.length > 20 ? `${at.text.slice(0, 20)}…` : at.text}」</p>
          <div className="space-y-2">
            {candidate.options.map((option, i) => (
              <div key={option.label} className="rounded-lg border border-line px-3.5 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-line/70 px-2 py-px text-xs text-ink-2">{option.label}</span>
                  <button type="button" onClick={() => void choose(i)} className="ml-auto rounded-md bg-ink px-3 py-1 text-[13px] text-paper-2 hover:bg-ink-2">用这个</button>
                </div>
                <p className="mt-1.5 font-serif text-[15px] leading-[1.85] whitespace-pre-line text-ink">{option.text}</p>
              </div>
            ))}
          </div>
          <button type="button" onClick={close} className="mt-2 text-[13px] text-ink-3 hover:text-ink">都不要</button>
        </div>
      )}
    </div>
  )
}

/* ---------------- 整页 ---------------- */

function firstSelection(book: VBook): string {
  const characters = book.categories.find((c) => c.name === '角色列表')?.entries ?? []
  const lead = pinnedFirst(characters)[0] ?? characters.find((c) => c.role === '主角') ?? characters[0]
  return lead?.id ?? (book.categories.find((c) => c.entries.length)?.entries[0]?.id ?? 'overview')
}

/** 自建类别一句话说清每条写什么。 */
function customAbout(style: CategoryStyle, fields: string[]): string {
  if (style === 'card') return fields.length ? `每条有这几栏：${fields.join('、')}。` : '每条有哪几栏，自己定。'
  if (style === 'ladder') return '一级一级往上排，每级一个名称加一段介绍。'
  return '一个名字加一段话。'
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

export interface WorkspaceProps {
  book: VBook
  actions: WorkspaceActions
  /** 顶栏右边：原型放换书的按钮，真书放系统设置 */
  right: ReactNode
  /** 左边一栏最下面固定的一块：真书放存档、本书设置 */
  sideFooter?: ReactNode
  /** 编辑部窗口里放什么 */
  chat: ReactNode
  /** 编辑部窗口顶上再放的按钮（真书：新对话、以前的对话） */
  chatTools?: ReactNode
  /** 收起成小球时右上角的数字；不给就只是一个红点 */
  chatBadge?: number
  /** 收起成小球时小球左边再说一声（真书：有待处理时「N 条待处理」） */
  chatBallNote?: ReactNode
  /** 外面要打开编辑部（比如点了某条消息）：每次加一 */
  openChat?: number
  /** 顶栏下面的一行提醒 */
  notice?: ReactNode
  /** 正文还没做：有正文时先链到旧版 */
  manuscriptHref?: string
  /** 外面（比如聊天里点「去看看」）要打开书里的某一条：工作台把打开的办法放进来 */
  openRef?: React.MutableRefObject<((type: string, id: string) => void) | null>
  /** 作者正在看哪一页：群聊发话时带上 */
  viewingRef?: React.MutableRefObject<(() => ChatViewing | null) | null>
  /** 写作：开写、停下、拍板。给了就有正文页签；真书还没接，先不给 */
  writing?: WritingControl
  /** 一打开先看哪一页：原型的链接能直接带到正文某一章、大纲某一段 */
  start?: { tab?: Tab; node?: string; chapter?: string }
}

export function Workspace({ book: base, actions, right, sideFooter, chat, chatTools, chatBadge, chatBallNote, openChat, notice, manuscriptHref, openRef, viewingRef, writing, start }: WorkspaceProps) {
  // 新增了还没起名字的条目：只在这一页，起了名字才存
  const [drafts, setDrafts] = useState<VEntry[]>([])
  const draftsRef = useRef(drafts)
  useLayoutEffect(() => { draftsRef.current = drafts }, [drafts])
  // 草稿存好以后换成了真 id：卡片还用草稿的 key
  const [aliases, setAliases] = useState<Record<string, string>>({})
  const creating = useRef(new Map<string, EntryChange[]>())

  const book = useMemo<VBook>(() => ({
    ...base,
    categories: base.categories.map((c) => ({
      ...c,
      entries: [...c.entries, ...drafts.filter((d) => d.category === c.name)].map((e) => applyTemplate(e, templateOf(base, c))),
    })),
  }), [base, drafts])

  const firstChild = base.outline.children?.[0]
  const firstNode = start?.node && findNode(base.outline, start.node) ? start.node : firstChild?.children?.[0]?.id ?? firstChild?.id ?? 'book'
  const defaultPosition = useMemo<WorkspaceReadingPosition>(() => ({
    tab: start?.tab === '正文' && !writing ? '设定' : start?.tab ?? '设定',
    entry: firstSelection(base),
    node: firstNode,
    chapter: start?.chapter && findNode(base.outline, start.chapter) ? start.chapter : 'home',
    open: ['book', ...(findNode(base.outline, firstNode) ?? []).map(item => item.id)],
  }), [base, firstNode, start, writing])
  const [initialPosition] = useState(() => readWorkspaceReadingPosition(base, defaultPosition, { live: actions.live, manuscript: !!writing, explicitStart: !!start }))
  const [tab, setTab] = useState<Tab>(initialPosition.tab)
  const [entry, setEntry] = useState(initialPosition.entry)
  const [fresh, setFresh] = useState('')
  const [node, setNode] = useState(initialPosition.node)
  const [freshNode, setFreshNode] = useState('')
  // 章号跟着位置走：插在第 1 章前面的新章还是 c1，要让大纲页重新来一遍
  const [nodeNonce, setNodeNonce] = useState(0)
  const [open, setOpen] = useState(initialPosition.open)
  const [outlineQuery, setOutlineQuery] = useState('')
  // 正文里看的是哪一章；home 是正文首页（开写）
  const [chapter, setChapter] = useState(initialPosition.chapter)
  const [dock, setDock] = useState<Dock>(() => readEditorialDock(actions.live))
  // 贴边时编辑部多宽：记住上次拖的宽度；顶栏的四个入口要让开它
  const [sideWidth, setSideWidth] = useState(() => savedSideWidth(actions.live ? 520 : 460))
  const [columnWidth, setColumnWidth] = useColumnWidth()
  const column = useMemo(() => ({ width: columnWidth, setWidth: setColumnWidth }), [columnWidth, setColumnWidth])
  const [toast, setToast] = useState('')
  // 一打开就滚到选中的那一条
  const [scrollReq, setScrollReq] = useState<ScrollReq | null>(() => ({ id: entry, smooth: false, n: 0 }))
  const pageRef = useRef<HTMLElement>(null)

  useEffect(() => {
    writeWorkspaceReadingPosition(base, { tab, entry, node, chapter, open }, defaultPosition, { live: actions.live, manuscript: !!writing })
  }, [actions.live, base, chapter, defaultPosition, entry, node, open, tab, writing])

  useEffect(() => { writeEditorialDock(dock, actions.live) }, [dock, actions.live])

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 3600)
    return () => clearTimeout(timer)
  }, [toast])
  useEffect(() => {
    if (openChat) setDock((d) => (d === 'ball' ? 'float' : d))
  }, [openChat])
  // 换到正文页签：从最上面看起
  useEffect(() => {
    if (tab === '正文') pageRef.current?.scrollTo({ top: 0 })
  }, [tab, chapter])

  const report = useCallback((error: unknown) => setToast(`没存上：${errorText(error)}`), [])
  // 编辑部刚改了一处：底下一条「改好了 · 撤销」，过一会儿自己收起
  const [undo, setUndo] = useState<{ text: string; versionId?: string; restore?: () => Promise<void> } | null>(null)
  useEffect(() => {
    if (!undo) return
    const timer = setTimeout(() => setUndo(null), 15000)
    return () => clearTimeout(timer)
  }, [undo])
  const onUndo = useCallback((text: string, how?: string | (() => Promise<void>) | null) => {
    if (typeof how === 'function') setUndo({ text, restore: how })
    else if (how) setUndo({ text, versionId: how })
    else setToast(text)
  }, [])

  // 新建的一条：起名字之前改的都记在草稿上；起了名字就建到书里
  const tools = useMemo(() => {
    const finish = async (draft: VEntry) => {
      const category = book.categories.find((c) => c.name === draft.category)
      if (!category || creating.current.has(draft.id)) return
      creating.current.set(draft.id, [])
      try {
        const id = await actions.createEntry(category, draft)
        const later = creating.current.get(draft.id) ?? []
        setAliases((a) => ({ ...a, [id]: a[draft.id] ?? draft.id }))
        setDrafts((ds) => ds.filter((d) => d.id !== draft.id))
        setEntry((now) => (now === draft.id ? id : now))
        setFresh((now) => (now === draft.id ? '' : now))
        // 建的时候又改了几处：建好以后补上
        for (const change of later) await actions.saveEntry({ ...draft, id }, change)
      } catch (error) {
        report(error)
      } finally {
        creating.current.delete(draft.id)
      }
    }
    const wrapped: WorkspaceActions = {
      ...actions,
      saveEntry: async (target, change) => {
        if (!target.id.startsWith('draft-')) return actions.saveEntry(target, change)
        const queued = creating.current.get(target.id)
        if (queued) {
          queued.push(change)
          return
        }
        let next = draftsRef.current.find((d) => d.id === target.id) ?? target
        if (change.fields) next = withFields(next, change.fields)
        if (change.name !== undefined) next = { ...next, name: change.name }
        if (change.oneLine !== undefined) next = { ...next, oneLine: change.oneLine }
        if (change.overview !== undefined) next = { ...next, overview: change.overview }
        if (change.levels !== undefined) next = { ...next, levels: change.levels }
        const updated = next
        setDrafts((ds) => ds.map((d) => (d.id === updated.id ? updated : d)))
        draftsRef.current = draftsRef.current.map((d) => (d.id === updated.id ? updated : d))
        if (updated.name.trim()) await finish(updated)
      },
      deleteEntry: async (target) => {
        if (target.id.startsWith('draft-')) setDrafts((ds) => ds.filter((d) => d.id !== target.id))
        else await actions.deleteEntry(target)
      },
    }
    return { actions: wrapped, report, notify: onUndo }
  }, [actions, book.categories, report, onUndo])

  const nav: Nav = {
    openEntry: (id) => {
      const same = tab === '设定' && categoryOf(id) === categoryOf(entry)
      setTab('设定')
      setEntry(id)
      setFresh('')
      setScrollReq({ id, smooth: same && !!categoryOf(id), n: Date.now() })
      if (!categoryOf(id)) pageRef.current?.scrollTo({ top: 0 })
    },
    openNode: (id) => {
      setTab('大纲')
      setNode(id)
      setFreshNode('')
      const path = findNode(base.outline, id)
      if (path) setOpen((list) => [...new Set([...list, ...path.slice(0, -1).map((n) => n.id)])])
      pageRef.current?.scrollTo({ top: 0 })
    },
    openChapter: (id) => {
      if (!writing) return
      setTab('正文')
      setChapter(id)
      pageRef.current?.scrollTo({ top: 0 })
    },
    toast: setToast,
  }
  useEffect(() => {
    if (!openRef) return
    openRef.current = (type, id) => {
      if (type === 'character' || type === 'entry') nav.openEntry(id)
      else if (type === 'segment') nav.openNode(`a:${id}`)
      else if (type === 'volume') nav.openNode(`v:${id}`)
      else if (type === 'unit') nav.openNode(`u:${id}`)
      else if (type === 'chapter') nav.openNode(`c${id}`)
      else if (type === 'book') nav.openNode('book')
      else if (type === 'concept') setTab('简介')
      else if (type === 'node') nav.openNode(id)
      else if (type === 'manuscript') nav.openChapter(id)
    }
  })
  useEffect(() => {
    if (!viewingRef) return
    viewingRef.current = () => {
      if (tab === '简介') return { target_type: 'concept', target_id: base.id, label: '简介' }
      if (tab === '正文') {
        const here = findNode(base.outline, chapter)?.at(-1)
        return here?.ref ? { target_type: here.ref.type, target_id: here.ref.id, label: `正文 · ${here.title.replace('　', ' ')}` } : null
      }
      if (tab === '大纲') {
        const path = findNode(base.outline, node)
        const here = path?.at(-1)
        if (!here?.ref) return null
        const names = path!.slice(1).map(shownTitle)
        return { target_type: here.ref.type, target_id: here.ref.id, label: `大纲 · ${names.length ? names.join(' / ') : '全书（结局）'}` }
      }
      const picked = findEntry(base, entry)
      if (!picked || picked.id.startsWith('draft-')) return null
      return { target_type: picked.kind === 'character' ? 'character' : 'entry', target_id: picked.id, label: `设定 · ${picked.category} · ${picked.name}` }
    }
  })

  const categoryName = categoryOf(entry)
  const categoryIndex = book.categories.findIndex((c) => c.name === categoryName)
  const category = categoryName ? book.categories[categoryIndex] ?? emptyCategory(categoryName) : undefined

  function categoryOf(id: string): string {
    if (id.startsWith('cat:')) return id.slice(4)
    return entryIn(book, drafts, id)?.category ?? ''
  }

  const newEntry = (name: string) => {
    const cat = book.categories.find((c) => c.name === name)
    if (!cat) return
    const blank = blankEntry(cat)
    setDrafts((ds) => [...ds, blank])
    setTab('设定')
    setEntry(blank.id)
    setFresh(blank.id)
    setScrollReq({ id: blank.id, smooth: true, n: Date.now() })
  }
  // 原型里编辑部写的几条收下来
  const accept = (name: string, items: { name: string; text: string }[]) => {
    const cat = book.categories.find((c) => c.name === name) ?? emptyCategory(name)
    for (const item of items) {
      const blank = blankEntry(cat)
      const filled = blank.kind === 'paragraph' ? withFields({ ...blank, name: item.name }, { 内容: item.text }) : { ...blank, name: item.name, oneLine: item.text }
      void tools.actions.createEntry(cat, applyTemplate(filled, templateOf(book, cat))).catch(report)
    }
  }
  const addNode = (parentId: string) => {
    const parent = findNode(base.outline, parentId)?.at(-1)
    if (!parent || !tools.actions.canAdd(parent)) return
    tools.actions.addNode(parent).then((id) => {
      if (!id) return
      setOpen((list) => [...new Set([...list, parentId])])
      setNode(id)
      setFreshNode(id)
      setTab('大纲')
    }).catch(report)
  }
  const insertNode = (sibling: VNode, where: 'before' | 'after') => {
    tools.actions.insertNode(sibling, where).then((id) => {
      if (!id) return
      setNode(id)
      setFreshNode(id)
      setNodeNonce((n) => n + 1)
    }).catch(report)
  }
  const moveNode = (target: VNode, direction: 'up' | 'down') => {
    tools.actions.moveNode(target, direction).then((id) => { if (id) setNode(id) }).catch(report)
  }
  const selectedNode = findNode(base.outline, node)?.at(-1)
  const outlineAdd = [
    ...(actions.canAdd(base.outline) ? [{ label: `新建${ONE[childKind(base.outline) ?? '篇']}`, onClick: () => addNode('book') }] : []),
    ...(selectedNode && selectedNode.id !== 'book' && actions.canAdd(selectedNode) && childKind(selectedNode) ? [{ label: `在「${shownTitle(selectedNode).trim()}」下面加${ONE[childKind(selectedNode)!]}`, onClick: () => addNode(selectedNode.id) }] : []),
  ]
  const outlineOnly = useMemo(() => {
    const q = outlineQuery.trim()
    if (!q) return undefined
    const ids = new Set<string>()
    matchingIds(base.outline, q, ids)
    return ids
  }, [base.outline, outlineQuery])
  const live = actions.live
  const chatSize = { width: 520, height: 640 }

  return (
    <ActionsContext.Provider value={tools}>
      <ColumnWidthContext.Provider value={column}>
      <SideFooterContext.Provider value={sideFooter ?? null}>
      <div className="desk-zoom flex flex-col bg-paper text-ink">
        <TopBar book={book} tab={tab} onTab={setTab} right={right} manuscriptHref={manuscriptHref} manuscript={!!writing}
          leftOffset={columnWidth} rightOffset={dock === 'side' ? sideWidth : 0} />
        {notice}
        {writing && <WritingStrip writing={writing} nav={nav} />}
        <div className="flex min-h-0 flex-1">
          {tab === '简介' && <BookColumn book={book} outline={base.outline} onTab={setTab} manuscript={!!writing} />}
          {tab === '设定' && (
            <SettingsDirectory book={book} selected={entry} onSelect={nav.openEntry} onNewEntry={newEntry}
              onCreateCategory={(name, style, fields) => {
                tools.actions.createCategory(name, style, fields, customAbout(style, fields)).then(() => nav.openEntry(`cat:${name}`)).catch(report)
              }} />
          )}
          {tab === '大纲' && (
            <DirectoryShell title="大纲" search="找篇、卷、单元、章……" query={outlineQuery} onQuery={setOutlineQuery} addMenu={outlineAdd}>
              <OutlineTreeView node={base.outline} depth={0} selected={node} onSelect={nav.openNode} open={open} onAdd={addNode} only={outlineOnly}
                toggle={(id) => setOpen(open.includes(id) ? open.filter((x) => x !== id) : [...open, id])} />
              {outlineOnly && outlineOnly.size === 0 && <p className="px-2.5 py-2 text-[13px] text-ink-3">没找到「{outlineQuery.trim()}」</p>}
            </DirectoryShell>
          )}
          {tab === '正文' && writing && (
            <ManuscriptDirectory book={book} selected={chapter} onSelect={nav.openChapter} writing={writing}
              onExport={() => (live ? window.open(`/api/books/${base.id}/export.txt`, '_blank') : setToast('原型：会把写好的章按卷、按章导出成一个 TXT 文件'))} />
          )}
          <main ref={pageRef} className="scroll-thin min-w-0 flex-1 overflow-y-auto">
            {tab === '简介' && <BlurbPage book={book} />}
            {tab === '设定' && (
              entry === 'world' ? <WorldPage book={book} />
                : category ? (
                  <CategoryStream key={category.key} book={book} category={category} next={book.categories[categoryIndex + 1]} nav={nav} fresh={fresh}
                    scrollReq={scrollReq} pageRef={pageRef} onSpy={(id) => setEntry((now) => (now === id ? now : id))}
                    cardKey={(id) => aliases[id] ?? id}
                    onNewEntry={() => newEntry(category.name)} onAccept={(items) => accept(category.name, items)} />
                )
                  : <SettingsOverview book={book} nav={nav} onSelect={nav.openEntry} />
            )}
            {tab === '大纲' && <OutlinePage key={`${node}:${nodeNonce}`} book={book} outline={base.outline} id={node} nav={nav} onAdd={addNode} onInsert={insertNode} onMove={moveNode} fresh={freshNode === node} writing={writing} />}
            {tab === '正文' && writing && (chapter === 'home'
              ? <ManuscriptHome book={book} writing={writing} nav={nav} />
              : <ChapterPage key={chapter} book={book} id={chapter} writing={writing} nav={nav} />)}
          </main>
          {dock === 'side' && <DockedEditorial setDock={setDock} width={sideWidth} setWidth={setSideWidth} tools={chatTools}>{chat}</DockedEditorial>}
        </div>

        {dock === 'float' && <FloatingEditorial setDock={setDock} size={chatSize} tools={chatTools}>{chat}</FloatingEditorial>}
        {dock === 'ball' && chatBallNote && <div className="fixed right-24 bottom-[36px] z-40">{chatBallNote}</div>}
        {dock === 'ball' && (
          <button type="button" onClick={() => setDock('float')} title="编辑部"
            className="press fixed right-6 bottom-6 z-40 flex size-14 items-center justify-center rounded-full bg-chief font-serif text-xl text-on-role shadow-[0_14px_30px_-10px_rgb(40_50_90/0.6)] transition-transform hover:-translate-y-0.5">
            编
            {writing?.status.state === 'working' && <span aria-hidden className="absolute -inset-1 rounded-full border-2 border-chief/25 border-t-chief motion-safe:animate-spin" />}
            {chatBadge === undefined
              ? <span className="absolute top-1 right-1 size-3 rounded-full bg-seal ring-2 ring-paper" />
              : chatBadge > 0 && <span className="absolute -top-0.5 -right-0.5 flex min-w-5 items-center justify-center rounded-full bg-seal px-1 text-[11px] leading-5 text-on-role ring-2 ring-paper">{chatBadge > 99 ? '99+' : chatBadge}</span>}
          </button>
        )}

        <SelectionActions pageRef={pageRef} onToast={setToast} onUndo={onUndo} />
        {undo && (
          <div className="fixed bottom-8 left-1/2 z-50 flex max-w-[min(640px,90vw)] -translate-x-1/2 items-center gap-3 rounded-full bg-ink px-5 py-2.5 text-[13px] text-paper-2 shadow-[var(--shadow-lift)]">
            <span className="line-clamp-2">{undo.text}</span>
            <button type="button" className="shrink-0 whitespace-nowrap underline underline-offset-4 hover:text-white" onClick={() => {
              const { versionId, restore } = undo
              setUndo(null)
              const back = restore ? restore() : versionId ? actions.revert?.(versionId) : undefined
              back?.then(() => setToast('撤销了，换回了原来的')).catch(report)
            }}>撤销</button>
          </div>
        )}
        {toast && !undo && (
          <div className="fixed bottom-8 left-1/2 z-50 flex max-w-[min(640px,90vw)] -translate-x-1/2 items-center gap-2 rounded-full bg-ink px-5 py-2.5 text-[13px] text-paper-2 shadow-[var(--shadow-lift)]">
            {toast}
          </div>
        )}
      </div>
      </SideFooterContext.Provider>
      </ColumnWidthContext.Provider>
    </ActionsContext.Provider>
  )
}

