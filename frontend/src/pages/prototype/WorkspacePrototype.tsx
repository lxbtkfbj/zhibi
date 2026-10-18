import clsx from 'clsx'
import { ArrowLeft, ArrowUp, ChevronDown, ChevronRight, Inbox, Lock, Minus, PanelRight, PictureInPicture2, Plus, Settings } from 'lucide-react'
import { type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookCover } from '../../components/BookCover'
import { BOOK, CATEGORIES, CHAT, OUTLINE, PENDING, type SampleEntry, type SampleNode } from './sampleBook'

type Tab = '简介' | '设定' | '大纲'
type Dock = 'ball' | 'float' | 'side'

const ROLE_STYLE: Record<string, string> = {
  主编: 'bg-chief text-on-role',
  设定师: 'bg-lore text-on-role',
  写手: 'bg-writer text-on-role',
  审稿: 'bg-reviewer text-on-role',
}

/** 可以直接改的字：点上去就是输入框，不用先点「编辑」。 */
function Editable({ children, className, multiline, boxed }: { children: ReactNode; className?: string; multiline?: boolean; boxed?: boolean }) {
  return (
    <div
      contentEditable
      suppressContentEditableWarning
      spellCheck={false}
      className={clsx('outline-none transition-colors', boxed ? 'focus:ring-1 focus:ring-line-2' : '-mx-2 rounded-md px-2 hover:bg-subtle focus:bg-subtle', multiline && 'whitespace-pre-line', className)}
    >
      {children}
    </div>
  )
}

/* ---------------- 顶栏 ---------------- */

function TopBar({ tab, onTab }: { tab: Tab; onTab: (tab: Tab) => void }) {
  const [inbox, setInbox] = useState(false)
  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-paper px-4">
      <Link to="/" className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
        <ArrowLeft className="size-4" />
        书房
      </Link>
      <span className="h-5 w-px bg-line-2" />
      <BookCover title={BOOK.title} seed="开新书" size="xs" />
      <span className="font-serif text-[17px] font-bold tracking-wide">{BOOK.title}</span>

      <nav className="ml-8 flex h-full items-stretch">
        {(['简介', '设定', '大纲'] as const).map((key) => (
          <button key={key} type="button" onClick={() => onTab(key)}
            className={clsx('relative px-4 text-[15px] transition-colors', tab === key ? 'font-medium text-ink' : 'text-ink-3 hover:text-ink')}>
            {key}
            {tab === key && <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-seal" />}
          </button>
        ))}
        <span className="flex cursor-not-allowed items-center px-4 text-[15px] text-ink-3/50" title="开写以后才有">正文</span>
      </nav>

      <div className="ml-auto flex items-center gap-1">
        <div className="relative">
          <button type="button" onClick={() => setInbox(!inbox)} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-ink-2 transition-colors hover:bg-line/50 hover:text-ink">
            <Inbox className="size-4" />
            待处理
            <span className="flex min-w-5 items-center justify-center rounded-full bg-seal px-1.5 text-[11px] leading-5 text-on-role">{PENDING.length}</span>
          </button>
          {inbox && (
            <div className="absolute top-[calc(100%+6px)] right-0 w-80 rounded-xl border border-line bg-card p-2 shadow-[var(--shadow-lift)]">
              {PENDING.map((item) => (
                <div key={item.id} className="rounded-lg px-3 py-2.5 hover:bg-subtle">
                  <p className="text-[13px] leading-relaxed text-ink">{item.text}</p>
                  <div className="mt-1.5 flex gap-3 text-xs">
                    <button type="button" className="text-chief hover:underline">去看看</button>
                    <button type="button" className="text-ink-3 hover:text-ink">不用</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <button type="button" className="rounded-lg p-2 text-ink-3 transition-colors hover:bg-line/50 hover:text-ink" aria-label="本书设置" title="本书设置">
          <Settings className="size-4" />
        </button>
      </div>
    </header>
  )
}

/* ---------------- 左边目录 ---------------- */

function DirectoryShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <aside className="flex w-[17.5rem] shrink-0 flex-col border-r border-line bg-paper-2">
      <div className="flex items-center justify-between px-5 pt-5 pb-2">
        <span className="text-xs tracking-[0.25em] text-ink-3">{title}</span>
        <button type="button" className="rounded-md p-1 text-ink-3 transition-colors hover:bg-line/60 hover:text-ink" aria-label="新建" title="新建">
          <Plus className="size-4" />
        </button>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pb-6">{children}</div>
    </aside>
  )
}

function SettingsDirectory({ selected, onSelect }: { selected: string; onSelect: (id: string) => void }) {
  const [closed, setClosed] = useState<string[]>([])
  return (
    <DirectoryShell title="设定">
      {CATEGORIES.map((cat) => {
        const open = !closed.includes(cat.name)
        return (
          <div key={cat.name} className="mt-1">
            <button type="button" onClick={() => setClosed(open ? [...closed, cat.name] : closed.filter((n) => n !== cat.name))}
              className={clsx('flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-[13px] transition-colors hover:bg-line/50', selected === `cat:${cat.name}` ? 'text-ink' : 'text-ink-2')}>
              {open ? <ChevronDown className="size-3.5 text-ink-3" /> : <ChevronRight className="size-3.5 text-ink-3" />}
              <span onClick={(e) => { if (!cat.entries.length) { e.stopPropagation(); onSelect(`cat:${cat.name}`) } }}>{cat.name}</span>
              <span className="ml-auto text-xs text-ink-3 tabular-nums">{cat.entries.length || ''}</span>
            </button>
            {open && (
              <div className="mt-0.5 mb-1 ml-[15px] border-l border-line pl-2">
                {cat.entries.map((entry) => (
                  <button key={entry.id} type="button" onClick={() => onSelect(entry.id)}
                    className={clsx('flex w-full items-center gap-1.5 rounded-md px-2.5 py-1.5 text-left font-serif text-[15px] transition-colors',
                      selected === entry.id ? 'bg-card font-bold text-ink shadow-[0_1px_2px_rgb(60_40_20/0.08)]' : 'text-ink-2 hover:bg-line/40 hover:text-ink')}>
                    <span className="truncate">{entry.name}</span>
                    {entry.locked && <Lock className="size-3 shrink-0 text-ink-3" />}
                  </button>
                ))}
                {!cat.entries.length && (
                  <button type="button" onClick={() => onSelect(`cat:${cat.name}`)}
                    className={clsx('w-full rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors', selected === `cat:${cat.name}` ? 'bg-card text-ink-2' : 'text-ink-3 hover:bg-line/40')}>
                    还没有
                  </button>
                )}
              </div>
            )}
          </div>
        )
      })}
    </DirectoryShell>
  )
}

function OutlineTree({ node, depth, selected, onSelect, open, toggle }: { node: SampleNode; depth: number; selected: string; onSelect: (id: string) => void; open: string[]; toggle: (id: string) => void }) {
  const expandable = !!node.children?.length
  const expanded = open.includes(node.id)
  return (
    <div>
      <div className={clsx('group flex items-center rounded-md transition-colors', selected === node.id ? 'bg-card shadow-[0_1px_2px_rgb(60_40_20/0.08)]' : 'hover:bg-line/40')}
        style={{ paddingLeft: depth * 12 }}>
        <button type="button" onClick={() => expandable && toggle(node.id)} className={clsx('flex size-6 shrink-0 items-center justify-center text-ink-3', !expandable && 'invisible')} aria-label={expanded ? '收起' : '展开'}>
          {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
        <button type="button" onClick={() => onSelect(node.id)}
          className={clsx('min-w-0 flex-1 truncate py-1.5 pr-2 text-left',
            node.kind === '章' ? 'text-[13px]' : 'font-serif text-[15px]',
            node.later ? 'text-ink-3' : selected === node.id ? 'font-bold text-ink' : 'text-ink-2 group-hover:text-ink')}>
          {node.title}
          {node.later && <span className="ml-1.5 text-xs font-normal">· 写到再定</span>}
        </button>
        {node.chapters && <span className="pr-2 text-xs text-ink-3 tabular-nums">{node.chapters} 章</span>}
      </div>
      {expandable && expanded && node.children!.map((child) => (
        <OutlineTree key={child.id} node={child} depth={depth + 1} selected={selected} onSelect={onSelect} open={open} toggle={toggle} />
      ))}
    </div>
  )
}

/* ---------------- 中间一页纸 ---------------- */

function Sheet({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[760px] px-6 py-10">
      <article className="min-h-[calc(100dvh-10rem)] rounded-lg border border-line bg-manuscript px-14 py-12 shadow-[var(--shadow-paper)]">{children}</article>
    </div>
  )
}

function Crumb({ items }: { items: string[] }) {
  return <p className="mb-4 text-xs tracking-wider text-ink-3">{items.join('  /  ')}</p>
}

function EntryPage({ category, entry }: { category: string; entry: SampleEntry }) {
  return (
    <Sheet>
      <Crumb items={['设定', category]} />
      <div className="flex flex-wrap items-center gap-3">
        <Editable className="font-serif text-[32px] leading-tight font-bold">{entry.name}</Editable>
        {entry.tags?.map((tag) => (
          <span key={tag} className="rounded-full bg-seal-soft px-2.5 py-0.5 text-xs text-seal">{tag}</span>
        ))}
        {entry.locked && <span className="flex items-center gap-1 rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2"><Lock className="size-3" />锁住</span>}
      </div>
      <Editable className="mt-3 font-serif text-[17px] leading-relaxed text-ink-2">{entry.oneLine}</Editable>

      {entry.fields && (
        <dl className="mt-8 border-t border-line">
          {entry.fields.map((field) => (
            <div key={field.label} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-4 border-b border-line/70 py-3.5">
              <dt className="pt-0.5 text-[13px] text-ink-3">{field.label}</dt>
              <dd><Editable multiline className="font-serif text-[16px] leading-[1.9] text-ink">{field.text}</Editable></dd>
            </div>
          ))}
        </dl>
      )}

      {entry.ladder && (
        <ol className="mt-8 space-y-0">
          {entry.ladder.map((level, i) => (
            <li key={level.name} className="relative flex gap-5 pb-6 last:pb-0">
              {i < entry.ladder!.length - 1 && <span className="absolute top-8 bottom-0 left-[15px] w-px bg-line-2" />}
              <span className="relative flex size-8 shrink-0 items-center justify-center rounded-full border border-line-2 bg-card font-serif text-sm text-ink-2">{i + 1}</span>
              <div className="min-w-0 pt-0.5">
                <Editable className="font-serif text-[18px] font-bold">{level.name}</Editable>
                <Editable className="mt-0.5 font-serif text-[16px] leading-[1.9] text-ink-2">{level.text}</Editable>
              </div>
            </li>
          ))}
        </ol>
      )}

      {entry.paragraph && (
        <Editable multiline className="mt-8 border-t border-line pt-6 font-serif text-[16px] leading-[2] text-ink">{entry.paragraph}</Editable>
      )}

      {entry.now && (
        <div className="mt-10 rounded-xl bg-subtle px-5 py-4">
          <p className="mb-2 text-xs tracking-wider text-ink-3">此刻 · 设定师每写完一章更新</p>
          <p className="flex flex-wrap gap-x-5 gap-y-1 text-[14px] text-ink-2">
            {entry.now.map((item) => <span key={item}>{item}</span>)}
          </p>
        </div>
      )}
    </Sheet>
  )
}

function EmptyCategoryPage({ name, hint, onToast }: { name: string; hint: string; onToast: (text: string) => void }) {
  return (
    <Sheet>
      <Crumb items={['设定', name]} />
      <h1 className="font-serif text-[32px] font-bold">{name}</h1>
      <p className="mt-3 font-serif text-[17px] leading-relaxed text-ink-2">放{hint}。用得上的写，用不上的不建。</p>
      <div className="mt-12 flex flex-col items-center rounded-2xl border border-dashed border-line-2 px-8 py-14 text-center">
        <p className="text-[15px] text-ink-2">这一类还没有写。</p>
        <p className="mt-1 text-[13px] text-ink-3">可以自己写，也可以让编辑部按简介先补几条，你写过的不会动。</p>
        <div className="mt-6 flex gap-3">
          <button type="button" className="h-10 rounded-lg border border-line-2 bg-card px-5 text-sm text-ink transition-colors hover:border-ink-3/50">自己写一条</button>
          <button type="button" onClick={() => onToast('原型：点了以后编辑部开始写，写好的条目一条条出现在左边目录里')}
            className="flex h-10 items-center gap-2 rounded-lg bg-ink px-5 text-sm text-paper-2 transition-colors hover:bg-ink-2">
            <span className="flex size-5 items-center justify-center rounded-full bg-chief font-serif text-[11px] text-on-role">编</span>
            让编辑部补几条
          </button>
        </div>
      </div>
    </Sheet>
  )
}

function findNode(node: SampleNode, id: string, path: SampleNode[] = []): SampleNode[] | null {
  if (node.id === id) return [...path, node]
  for (const child of node.children ?? []) {
    const found = findNode(child, id, [...path, node])
    if (found) return found
  }
  return null
}

function OutlinePage({ id, onSelect }: { id: string; onSelect: (id: string) => void }) {
  const path = findNode(OUTLINE, id) ?? [OUTLINE]
  const node = path[path.length - 1]
  return (
    <Sheet>
      <Crumb items={['大纲', ...path.slice(0, -1).map((n) => n.title)]} />
      <div className="flex items-baseline gap-3">
        <Editable className="font-serif text-[32px] leading-tight font-bold">{node.title}</Editable>
        {node.chapters && <span className="text-sm text-ink-3">{node.chapters} 章</span>}
        {node.later && <span className="rounded-full bg-line/70 px-2.5 py-0.5 text-xs text-ink-2">写到再定</span>}
      </div>
      <Editable multiline className={clsx('mt-6 font-serif text-[17px] leading-[2]', node.later ? 'text-ink-3' : 'text-ink')}>{node.text}</Editable>

      {!!node.children?.length && (
        <section className="mt-12">
          <p className="mb-3 text-xs tracking-wider text-ink-3">下面一层</p>
          <div className="divide-y divide-line border-y border-line">
            {node.children.map((child) => (
              <button key={child.id} type="button" onClick={() => onSelect(child.id)} className="group flex w-full items-baseline gap-4 py-3.5 text-left">
                <span className={clsx('w-48 shrink-0 font-serif text-[15px] font-bold group-hover:text-seal', child.later ? 'text-ink-3' : 'text-ink')}>{child.title}</span>
                <span className="line-clamp-1 flex-1 text-[14px] text-ink-3">{child.text.split('\n')[0]}</span>
                {child.chapters && <span className="text-xs text-ink-3 tabular-nums">{child.chapters} 章</span>}
              </button>
            ))}
          </div>
        </section>
      )}
    </Sheet>
  )
}

function BlurbPage() {
  return (
    <div className="flex min-h-full items-center justify-center px-6 py-10">
      <div className="grid w-full max-w-[940px] rounded-2xl border border-line bg-card shadow-[var(--shadow-lift)] md:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="hidden flex-col items-center justify-center rounded-l-2xl border-r border-line bg-paper-2 px-8 py-12 md:flex">
          <BookCover title={BOOK.title} seed="开新书" size="lg" className="shadow-[0_22px_34px_-18px_rgb(40_25_10/0.55)]" />
          <p className="mt-7 font-serif text-xl font-bold">{BOOK.title}</p>
          <p className="mt-1.5 text-[13px] text-ink-3">{[BOOK.genre, ...BOOK.tags].join(' · ')}</p>
          <p className="mt-0.5 text-[13px] text-ink-3">{BOOK.length} 万字 · 约 {BOOK.chapters} 章</p>
        </aside>
        <div className="px-12 py-10">
          <Editable className="font-serif text-[32px] font-bold">{BOOK.title}</Editable>
          <p className="mt-7 mb-2.5 text-sm text-ink-3">简介</p>
          <Editable multiline boxed className="rounded-xl bg-paper/45 px-5 py-4 font-serif text-[16px] leading-[1.95]">{BOOK.blurb}</Editable>
          <div className="mt-5 divide-y divide-line border-y border-line text-sm">
            {[
              ['类别', `${BOOK.channel} · ${BOOK.genre}`],
              ['标签', BOOK.tags.join('、')],
              ['篇幅', `${BOOK.length} 万字 · 约 ${BOOK.chapters} 章`],
            ].map(([label, value]) => (
              <div key={label} className="grid grid-cols-[64px_minmax(0,1fr)] gap-4 py-3.5">
                <span className="text-ink-3">{label}</span>
                <span className="text-ink">{value}</span>
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
    pageRef.current?.addEventListener('scroll', hide)
    const page = pageRef.current
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

export function WorkspacePrototype() {
  const [tab, setTab] = useState<Tab>('设定')
  const [entry, setEntry] = useState('chenmo')
  const [node, setNode] = useState('v1')
  const [open, setOpen] = useState(['book', 'part1', 'v1', 'u1'])
  const [dock, setDock] = useState<Dock>('ball')
  const [toast, setToast] = useState('')
  const pageRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 3200)
    return () => clearTimeout(timer)
  }, [toast])

  const selectNode = (id: string) => {
    setNode(id)
    const path = findNode(OUTLINE, id)
    if (path) setOpen((list) => [...new Set([...list, ...path.slice(0, -1).map((n) => n.id)])])
    pageRef.current?.scrollTo({ top: 0 })
  }
  const selectEntry = (id: string) => {
    setEntry(id)
    pageRef.current?.scrollTo({ top: 0 })
  }

  const category = entry.startsWith('cat:') ? CATEGORIES.find((c) => `cat:${c.name}` === entry) : CATEGORIES.find((c) => c.entries.some((e) => e.id === entry))
  const current = category?.entries.find((e) => e.id === entry)

  return (
    <div className="flex h-dvh flex-col bg-paper text-ink">
      <TopBar tab={tab} onTab={setTab} />
      <div className="flex min-h-0 flex-1">
        {tab === '设定' && <SettingsDirectory selected={entry} onSelect={selectEntry} />}
        {tab === '大纲' && (
          <DirectoryShell title="大纲">
            <OutlineTree node={OUTLINE} depth={0} selected={node} onSelect={selectNode} open={open} toggle={(id) => setOpen(open.includes(id) ? open.filter((x) => x !== id) : [...open, id])} />
          </DirectoryShell>
        )}
        <main ref={pageRef} className="scroll-thin min-w-0 flex-1 overflow-y-auto">
          {tab === '简介' && <BlurbPage />}
          {tab === '设定' && category && (current ? <EntryPage category={category.name} entry={current} /> : <EmptyCategoryPage name={category.name} hint={category.hint} onToast={setToast} />)}
          {tab === '大纲' && <OutlinePage id={node} onSelect={selectNode} />}
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
        <div className="fixed bottom-8 left-1/2 z-50 -translate-x-1/2 rounded-full bg-ink px-5 py-2.5 text-[13px] text-paper-2 shadow-[var(--shadow-lift)]">{toast}</div>
      )}
      <div className="pointer-events-none fixed bottom-4 left-4 z-10 rounded-full bg-writer-soft px-3 py-1 text-xs text-writer">原型 · 内容都是假的，只看样子</div>
    </div>
  )
}
