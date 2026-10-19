/** 工作台里各页共用的小部件：点上去就能改的字、小菜单、左边目录的壳、中间那一页纸。 */

import clsx from 'clsx'
import { ChevronDown, Lock, LockOpen, MoreHorizontal, Pin, Search, Sparkles, Trash2, X } from 'lucide-react'
import { type ReactNode, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { COLUMN_KEY, COLUMN_MAX, COLUMN_MIN, ColumnWidthContext, zoomOf } from './column'
import type { VField } from './model'
import { menuItem, paperCard, readText } from './styles'

/* ---------------- 小部件 ---------------- */

/** 可以直接改的字：点上去就能改，不用先点「编辑」；离开就存；空着时显示该写什么。Esc 撤回这次改的。 */
export function Editable({ value, onSave, className, multiline, boxed, placeholder, autoFocus, readOnly, spot }: {
  value: string; onSave?: (text: string) => void; className?: string; multiline?: boolean; boxed?: boolean; placeholder?: string; autoFocus?: boolean; readOnly?: boolean
  /** 这一栏在书里是哪一处：选中里面的字能让编辑部改（写法见 liveActions 的 resolveSpot） */
  spot?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const saved = useRef(value)
  // 外面的值变了（存好了、别处改了）：不在改的时候才换上，正在打的字不动
  useLayoutEffect(() => {
    const el = ref.current
    saved.current = value
    if (el && document.activeElement !== el && readText(el) !== value) el.innerText = value
  }, [value])
  useEffect(() => {
    if (autoFocus) ref.current?.focus()
  }, [autoFocus])
  const editable = !!onSave && !readOnly
  return (
    <div
      ref={ref}
      contentEditable={editable ? 'plaintext-only' : false}
      suppressContentEditableWarning
      spellCheck={false}
      role={editable ? 'textbox' : undefined}
      aria-multiline={editable ? multiline : undefined}
      aria-label={editable ? placeholder : undefined}
      data-placeholder={placeholder}
      data-spot={spot}
      onInput={(e) => { if (!e.currentTarget.textContent) e.currentTarget.innerHTML = '' }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.currentTarget.innerText = saved.current
          e.currentTarget.blur()
        } else if (e.key === 'Enter' && !multiline && !e.nativeEvent.isComposing) {
          e.preventDefault()
          e.currentTarget.blur()
        }
      }}
      onBlur={(e) => {
        const text = readText(e.currentTarget)
        if (!e.currentTarget.textContent) e.currentTarget.innerHTML = ''
        if (onSave && text !== saved.current) {
          saved.current = text
          onSave(text)
        }
      }}
      className={clsx(
        'outline-none transition-colors',
        editable && (boxed ? 'focus:ring-1 focus:ring-line-2' : '-mx-2 rounded-md px-2 hover:bg-subtle focus:bg-subtle'),
        !editable && !boxed && '-mx-2 px-2',
        multiline && 'whitespace-pre-line',
        placeholder && 'empty:before:text-ink-3/60 empty:before:content-[attr(data-placeholder)]',
        className,
      )}
    />
  )
}

const LONG = 260

/** 一段长文字：可以直接改；太长先折起来，点进去改就展开。 */
export function Prose({ value, onSave, placeholder, autoFocus, readOnly, spot }: { value: string; onSave?: (text: string) => void; placeholder?: string; autoFocus?: boolean; readOnly?: boolean; spot?: string }) {
  const long = value.length > LONG
  const [open, setOpen] = useState(false)
  return (
    <>
      <div className={clsx('relative', long && !open && 'max-h-[11.5em] overflow-hidden')} onFocus={() => setOpen(true)}>
        <Editable multiline autoFocus={autoFocus} value={value} onSave={onSave} readOnly={readOnly} spot={spot} placeholder={placeholder ?? '还没写'} className="font-serif text-[17px] leading-[1.95] text-ink 2xl:text-lg" />
        {long && !open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-card to-transparent" />}
      </div>
      {long && (
        <button type="button" onClick={() => setOpen(!open)} className="mt-1 text-[13px] text-chief hover:underline">
          {open ? '收起' : `展开全文（${value.length} 字）`}
        </button>
      )}
    </>
  )
}

/** 正文里的一栏：小标题加一段字。 */
export function Section({ field, onSave, readOnly, children, spot }: { field: VField; onSave?: (text: string) => void; readOnly?: boolean; children?: ReactNode; spot?: string }) {
  return (
    <section>
      <h3 className="mb-2 text-[13px] tracking-[0.15em] text-ink-3">{field.label}</h3>
      <Prose value={field.text} onSave={onSave} readOnly={readOnly} placeholder={field.placeholder} spot={spot} />
      {children}
    </section>
  )
}

export function LinkChip({ icon, children, onClick }: { icon?: ReactNode; children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-subtle px-3 py-1 text-[13px] text-ink-2 transition-colors hover:bg-line/60 hover:text-ink">
      {icon}<span className="truncate">{children}</span>
    </button>
  )
}

export function AskButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="h-9 rounded-lg border border-line-2 bg-card px-4 text-sm text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink">
      {children}
    </button>
  )
}

/** 点一下弹出的小菜单：点外面或按 Esc 收起。 */
export function Menu({ trigger, children, align = 'right', className }: { trigger: (open: boolean, toggle: () => void) => ReactNode; children: (close: () => void) => ReactNode; align?: 'left' | 'right'; className?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('mousedown', down)
      document.removeEventListener('keydown', key)
    }
  }, [open])
  return (
    <div ref={ref} className={clsx('relative', className)}>
      {trigger(open, () => setOpen(!open))}
      {open && (
        <div className={clsx('absolute top-[calc(100%+4px)] z-30 min-w-44 rounded-xl border border-line bg-card p-1 shadow-[var(--shadow-lift)]', align === 'right' ? 'right-0' : 'left-0')}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

/** 设定卡片右上角：补齐、锁住、删掉三个小图标，鼠标移到卡上才出来（锁住的一直显示锁）。删要点两次。 */
function CardIcons({ locked, onLock, onDelete, deleteLabel, onFill, pinned, onPin }: {
  locked?: boolean; onLock?: () => void; onDelete?: () => void; deleteLabel: string; onFill?: () => void; pinned?: boolean; onPin?: () => void
}) {
  const [sure, setSure] = useState(false)
  const icon = 'flex size-8 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-line/60 hover:text-ink'
  const hidden = 'opacity-0 transition-opacity group-hover/card:opacity-100 focus-visible:opacity-100'
  return (
    <div className="absolute top-5 right-5 z-10 flex items-center gap-0.5" onMouseLeave={() => setSure(false)}>
      {onPin && (
        <button type="button" onClick={onPin} aria-pressed={pinned}
          title={pinned ? '置顶了：排在目录最上面，编辑部每写一章都带上他；点一下取消' : '置顶：排在目录最上面，编辑部每写一章都带上他'}
          aria-label={pinned ? '取消置顶' : '置顶'} className={clsx(icon, pinned ? 'text-chief' : hidden)}>
          <Pin className={clsx('size-4', pinned && 'fill-current')} />
        </button>
      )}
      {onFill && (
        <button type="button" onClick={onFill} title="让编辑部补齐空着的栏目" aria-label="让编辑部补齐空着的栏目" className={clsx(icon, hidden)}>
          <Sparkles className="size-4" />
        </button>
      )}
      {onLock && (
        <button type="button" onClick={onLock} title={locked ? '锁住了，AI 不改；点一下解锁' : '锁住，AI 不改'} aria-label={locked ? '解锁' : '锁住'}
          className={clsx(icon, locked ? 'text-ink-2' : hidden)}>
          {locked ? <Lock className="size-4" /> : <LockOpen className="size-4" />}
        </button>
      )}
      {onDelete && (
        <button type="button" onClick={() => { if (!sure) return setSure(true); setSure(false); onDelete() }}
          title={sure ? '再点一次，真删了' : deleteLabel} aria-label={sure ? '再点一次，真删了' : deleteLabel}
          className={clsx(icon, sure ? 'w-auto gap-1 bg-seal-soft px-2 text-[13px] text-seal hover:bg-seal-soft hover:text-seal' : hidden)}>
          <Trash2 className="size-4" />{sure && '再点一次删掉'}
        </button>
      )}
    </div>
  )
}

/** 卡片右上角：设定卡片是三个小图标；大纲、正文那种有好几项的，是一个「⋯」小菜单。删要点两次。 */
export function CardMenu({ locked, onLock, onDelete, deleteLabel = '删掉这一条', onFill, items = [], pinned, onPin }: {
  locked?: boolean; onLock?: () => void; onDelete?: () => void; deleteLabel?: string; onFill?: () => void
  /** 角色卡：置顶 */
  pinned?: boolean; onPin?: () => void
  /** 再多几项：大纲上的在前面插、在后面插、上移、下移 */
  items?: { label: string; onClick: () => void }[]
}) {
  const [sure, setSure] = useState(false)
  if (!items.length) return <CardIcons locked={locked} onLock={onLock} onDelete={onDelete} deleteLabel={deleteLabel} onFill={onFill} pinned={pinned} onPin={onPin} />
  return (
    <div className="absolute top-5 right-5 z-10">
    <Menu
      trigger={(open, toggle) => (
        <button type="button" onClick={() => { setSure(false); toggle() }} aria-label="更多" title="更多"
          className={clsx('rounded-md p-1.5 text-ink-3 transition-opacity hover:bg-line/60 hover:text-ink', open ? 'opacity-100' : 'opacity-0 group-hover/card:opacity-100 focus-visible:opacity-100')}>
          <MoreHorizontal className="size-4" />
        </button>
      )}>
      {(close) => (
        <>
          {items.map((item) => <button key={item.label} type="button" className={menuItem} onClick={() => { close(); item.onClick() }}>{item.label}</button>)}
          {onFill && <button type="button" className={menuItem} onClick={() => { close(); onFill() }}>让编辑部补齐空着的栏目</button>}
          {onLock && <button type="button" className={menuItem} onClick={() => { close(); onLock() }}>{locked ? '解锁，AI 可以改' : '锁住，AI 不改'}</button>}
          {onDelete && (
            <button type="button" className={clsx(menuItem, sure && 'text-seal hover:text-seal')}
              onClick={() => { if (!sure) return setSure(true); close(); onDelete() }}>
              {sure ? '再点一次，真删了' : deleteLabel}
            </button>
          )}
        </>
      )}
    </Menu>
    </div>
  )
}

/* ---------------- 左边目录 ---------------- */

/** 左边一栏的壳：每一页（简介、设定、大纲、正文）同一个宽度，右边缘能拖。 */
export function SideColumn({ children }: { children: ReactNode }) {
  const { width, setWidth } = useContext(ColumnWidthContext)
  const ref = useRef<HTMLElement>(null)
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    if (!dragging) return
    const move = (e: PointerEvent) => {
      const el = ref.current
      if (!el) return
      const z = zoomOf(el)
      const left = el.getBoundingClientRect().left
      setWidth(Math.round(Math.min(Math.max(COLUMN_MIN, (e.clientX - left) / z), COLUMN_MAX)))
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
      localStorage.setItem(COLUMN_KEY, String(width))
    } catch { /* 存不了就只管这一次 */ }
  }, [dragging, width])
  return (
    <aside ref={ref} className="relative flex shrink-0 flex-col border-r border-line bg-paper-2" style={{ width }}>
      {children}
      <div onPointerDown={(e) => { e.preventDefault(); setDragging(true) }} title="拖动调宽窄"
        className={clsx('absolute inset-y-0 -right-1.5 z-10 w-3 cursor-col-resize after:absolute after:inset-y-0 after:left-1.5 after:w-0.5 after:transition-colors', dragging ? 'after:bg-chief/60' : 'hover:after:bg-chief/40')} />
      {dragging && <div className="fixed inset-0 z-50 cursor-col-resize" />}
    </aside>
  )
}

/** 目录顶上「新增」：只有一件事就直接做，有几件才弹一个小菜单。 */
function AddAction({ items }: { items: { label: string; onClick: () => void }[] }) {
  const style = 'flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs text-ink-3 transition-colors hover:bg-line/60 hover:text-ink'
  if (items.length === 1) return <button type="button" onClick={items[0].onClick} className={style}>{items[0].label}</button>
  return (
    <Menu trigger={(_, toggle) => (
      <button type="button" onClick={toggle} className={style}>新建<ChevronDown className="size-3" /></button>
    )}>
      {(close) => items.map((item) => (
        <button key={item.label} type="button" onClick={() => { close(); item.onClick() }} className={menuItem}>{item.label}</button>
      ))}
    </Menu>
  )
}

export function DirectoryShell({ title, search, query, onQuery, onTitle, children, footer, addMenu }: {
  title: string; search: string; query: string; onQuery: (query: string) => void; onTitle?: () => void
  children: ReactNode; footer?: ReactNode; addMenu?: { label: string; onClick: () => void }[]
}) {
  return (
    <SideColumn>
      <div className="flex h-14 items-end justify-between px-5 pb-3">
        <button type="button" onClick={onTitle} className="text-xs tracking-[0.25em] text-ink-3 hover:text-ink">{title}</button>
        {!!addMenu?.length && <AddAction items={addMenu} />}
      </div>
      <label className="mx-4 mb-3 flex h-9 items-center gap-2 rounded-lg border border-line bg-card/70 px-3 text-sm text-ink-3 focus-within:border-line-2">
        <Search className="size-4 shrink-0" />
        <input value={query} onChange={(e) => onQuery(e.target.value)} placeholder={search} className="min-w-0 flex-1 bg-transparent text-ink placeholder:text-ink-3 focus:outline-none" />
        {query && <button type="button" onClick={() => onQuery('')} aria-label="清掉" className="text-ink-3 hover:text-ink"><X className="size-3.5" /></button>}
      </label>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pb-20">
        {children}
        {footer}
      </div>
    </SideColumn>
  )
}

/* ---------------- 中间一页纸 ---------------- */

export function Sheet({ children, narrow }: { children: ReactNode; narrow?: boolean }) {
  return (
    <div className={clsx('mx-auto w-full px-8 py-10 2xl:py-12', narrow ? 'max-w-[880px] 2xl:max-w-[940px]' : 'max-w-[1080px] 2xl:max-w-[1180px]')}>
      <article className={clsx(paperCard, 'group/card relative')}>{children}</article>
    </div>
  )
}

export function Crumb({ items }: { items: string[] }) {
  return <p className="mb-4 text-[13px] tracking-wider text-ink-3">{items.join('  /  ')}</p>
}
