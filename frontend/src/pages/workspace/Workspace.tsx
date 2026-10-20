import clsx from 'clsx'
import { ChevronDown, ChevronUp, Inbox, Minus, PanelRight, PictureInPicture2 } from 'lucide-react'
import { type PointerEvent as ReactPointerEvent, type ReactNode, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { ChatViewing } from '../../api/types'
import { readEditorialDock, writeEditorialDock, type EditorialDock as Dock } from '../../lib/editorialDock'
import { teardownWorkspaceActions } from '../../lib/teardownWorkspace'
import { DeskTop, DeskDirectory } from './desk-v2/Chrome'
import { DeskIntro, DeskSettings } from './desk-v2/SettingsPages'
import { DeskOutline } from './desk-v2/OutlinePages'
import { DeskManuscript } from './desk-v2/ManuscriptPages'
import { clearTeardownEntry, readWorkspaceReadingPosition, teardownEntryTab, writeWorkspaceReadingPosition, type WorkspaceReadingPosition } from '../../lib/workspaceReadingPosition'
import { BookContext } from '../book/context'
import { ActionsContext, type DraftItem, type EntryChange, type RewriteMode, type RewriteOutcome, type WorkspaceActions, blankEntry, childKind, draftToEntry, useSave, useWorkspace, withFields } from './actions'
import { applyTemplate, cn, emptyCategory, findEntry, findNode, splitTitle, templateOf, type CardTemplate, type FieldItem, type VBook, type VCategory, type VEntry, type VNode } from './model'
import { PENDING } from './sampleBook'
import { type WritingControl } from './writing'
import { ColumnWidthContext, SideFooterContext, useColumnWidth, zoomOf } from './column'
import { readText, smallButton } from './styles'

export type Tab = '简介' | '设定' | '大纲' | '正文'

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

/** 树上显示的名字：还没起名的写「未命名」。 */
function shownTitle(node: VNode): string {
  const [prefix, name] = splitTitle(node.title)
  return node.title.includes('　') && !name.trim() ? `${prefix}　未命名` : node.title
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
export function AskPanel({ book, category, onAccept, onClose }: { book: VBook; category: VCategory; onAccept: (items: { name: string; text: string }[]) => void; onClose: () => void }) {
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
export function CardTemplateEditor({ category, template, counts, onClose }: {
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

/* ---------------- 大纲 ---------------- */

/** 一篇、一卷、一个单元、一章 */
const ONE: Record<VNode['kind'], string> = { 全书: '全书', 篇: '一篇', 卷: '一卷', 单元: '一个单元', 章: '一章' }

/** 章数：单元和没拆单元的卷可以自己定，空着就是还没定（有几章算几章，写到这里编辑部按剧情定）。 */
export function CountField({ node }: { node: VNode }) {
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

export function WriteHelp({ node }: { node: VNode }) {
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
  if (!open) return <div><button type="button" className="btn seal-line" onClick={() => setOpen(true)}>{empty ? `编辑部帮写${what}` : `编辑部帮改写${what}`}</button></div>
  return (
    <div className="rounded-2xl border border-line bg-subtle p-5">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-full bg-chief font-serif text-xs text-on-role">主</span>
        <p className="text-[15px] text-ink">想让{what}写成什么样？</p>
        <button type="button" onClick={() => setOpen(false)} className="btn seal-line ml-auto">收起</button>
      </div>
      <textarea autoFocus value={request} onChange={(e) => setRequest(e.target.value)} rows={2}
        placeholder={empty ? '比如：主角在这里第一次亮出金手指，要憋屈一阵再爆。不写也行，编辑部照前后的大纲和设定来。' : '比如：节奏快一点，结尾留个钩子。不写也行；你写过的意思都会留着，在上面补全写顺。'}
        className="w-full resize-none rounded-xl border border-line-2 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
      <div className="mt-3 flex items-center justify-between gap-4">
        <p className="text-xs text-ink-3">{node.kind === '章' || node.kind === '全书' ? '' : '名字你起过的就不换，'}写好直接换上；不满意，底下点撤销就换回原来的。</p>
        <button type="button" onClick={go} className="btn solid shrink-0">写</button>
      </div>
    </div>
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
        className="desk-legacy fixed z-40 flex flex-col overflow-hidden rounded-2xl border border-line bg-paper shadow-[0_24px_60px_-20px_rgb(40_25_10/0.45),0_2px_6px_rgb(40_25_10/0.08)]"
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
    <aside ref={ref} data-testid="editorial-docked" className="desk-legacy relative flex shrink-0 flex-col border-l border-line bg-paper" style={{ width }}>
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
  const rawOffset = Number(host.dataset.spotOffset ?? 0)
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0
  return best < 0 ? null : [best + offset, best + picked.length + offset]
}

/** 选中一栏里的几个字，旁边冒出三个按钮：改这一句（先说怎么改）、给我几个写法（挑一个换上）、写细一点。改好可以撤销。 */
function SelectionActions({ pageRef, onToast, onUndo, teardown }: {
  pageRef: React.RefObject<HTMLElement | null>; onToast: (text: string) => void; onUndo: (text: string, versionId?: string | null) => void; teardown?: boolean
}) {
  const { actions } = useWorkspace()
  const bookContext = useContext(BookContext)
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
      style={step === 'menu' ? { left: teardown ? Math.min(Math.max(at.x, 80), window.innerWidth / at.z - 80) : at.x, top: teardown ? Math.max(70, Math.min(at.top - 46, window.innerHeight / at.z - 52)) : at.top - 46 } : { left, top: Math.min(at.bottom + 10, window.innerHeight / at.z - 120) }}
      onMouseDown={(e) => { if (step === 'menu') e.preventDefault() }}>
      {step === 'menu' && (
        <div className={clsx(panel, 'flex items-center gap-0.5 p-1')}>
          <span className="ml-1 flex size-6 items-center justify-center rounded-full bg-lore font-serif text-[11px] text-on-role">{teardown ? '编' : '设'}</span>
          {teardown && bookContext && <button type="button" className={menuButton} onClick={() => {
            bookContext.askChief({ text: at.text, where: bookContext.viewing?.()?.label ?? '原文里选中的一句' })
            bookContext.showChat?.()
            close()
            window.getSelection()?.removeAllRanges()
          }}>问问主编</button>}
          {!teardown && labels.map((label, i) => (
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

export function Workspace({ book: base, actions: rawActions, right, sideFooter, chat, chatTools, chatBadge, chatBallNote, openChat, notice, openRef, viewingRef, writing, start }: WorkspaceProps) {
  const teardown = base.source === 'teardown'
  const actions = useMemo(() => teardownWorkspaceActions(base.source, rawActions), [base.source, rawActions])
  const location = useLocation()
  const navigate = useNavigate()
  const entryTab = teardownEntryTab(base.source, location.state)
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
    tab: start?.tab === '正文' && !writing ? '设定' : start?.tab ?? (teardown ? '正文' : '设定'),
    entry: 'overview',
    node: firstNode,
    chapter: start?.chapter && findNode(base.outline, start.chapter) ? start.chapter : 'home',
    open: ['book', ...(findNode(base.outline, firstNode) ?? []).map(item => item.id)],
  }), [base, firstNode, start, writing, teardown])
  const [initialPosition] = useState(() => readWorkspaceReadingPosition(base, entryTab && !start ? { ...defaultPosition, tab: entryTab } : defaultPosition, { live: actions.live, manuscript: !!writing, explicitStart: !!start || entryTab !== undefined }))
  const [tab, setTab] = useState<Tab>(initialPosition.tab)
  const [entry, setEntry] = useState(initialPosition.entry)
  const [fresh, setFresh] = useState('')
  const [node, setNode] = useState(initialPosition.node)
  const [freshNode, setFreshNode] = useState('')
  // 章号跟着位置走：插在第 1 章前面的新章还是 c1，要让大纲页重新来一遍
  const [nodeNonce, setNodeNonce] = useState(0)
  const [open, setOpen] = useState(initialPosition.open)
  // 正文里看的是哪一章；home 是正文首页（开写）
  const [chapter, setChapter] = useState(initialPosition.chapter)
  const [searchWord, setSearchWord] = useState('')
  const [searchToken, setSearchToken] = useState(0)
  const [dock, setDock] = useState<Dock>(() => readEditorialDock(actions.live))
  // 贴边时编辑部多宽：记住上次拖的宽度；顶栏的四个入口要让开它
  const [sideWidth, setSideWidth] = useState(() => savedSideWidth(actions.live ? 520 : 460))
  const [columnWidth, setColumnWidth] = useColumnWidth()
  const column = useMemo(() => ({ width: columnWidth, setWidth: setColumnWidth }), [columnWidth, setColumnWidth])
  const [toast, setToast] = useState('')
  const pageRef = useRef<HTMLElement>(null)

  useEffect(() => {
    writeWorkspaceReadingPosition(base, { tab, entry, node, chapter, open }, defaultPosition, { live: actions.live, manuscript: !!writing })
  }, [actions.live, base, chapter, defaultPosition, entry, node, open, tab, writing])

  useEffect(() => {
    if (entryTab === undefined) return
    // 消费入口标记，不多加一条历史；之后刷新、返回按当前页签和章节恢复。
    void navigate({ pathname: location.pathname, search: location.search, hash: location.hash }, { replace: true, state: clearTeardownEntry(location.state) })
  }, [entryTab, location.hash, location.pathname, location.search, location.state, navigate])

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
      setTab('设定')
      setEntry(id)
      setFresh('')
      pageRef.current?.scrollTo({ top: 0 })
    },
    openNode: (id) => {
      setTab('大纲')
      setNode(id)
      setFreshNode('')
      const path = findNode(base.outline, id)
      if (path) setOpen(path.filter(n => n.kind !== '章').map(n => n.id))
      pageRef.current?.scrollTo({ top: 0 })
    },
    openChapter: (id) => {
      if (!writing) return
      setSearchWord('')
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

  const newEntry = (name: string) => {
    const cat = book.categories.find((c) => c.name === name)
    if (!cat) return
    const blank = blankEntry(cat)
    setDrafts((ds) => [...ds, blank])
    setTab('设定')
    setEntry(blank.id)
    setFresh(blank.id)
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
  const chatSize = { width: 520, height: 640 }
  useLayoutEffect(() => {
    const fit = () => {
      const root = pageRef.current?.closest<HTMLElement>('.desk-v2')
      const here = findNode(book.outline, node)?.at(-1)
      const chapterPage = tab === '大纲' && here?.kind === '章' && (!teardown || here.teardown?.read)
      root?.style.setProperty('--s', chapterPage ? Math.min(1.2, Math.max(.9, ((pageRef.current?.clientHeight ?? 698) - 48) / 650)).toFixed(3) : '1')
    }
    fit()
    const observer = new ResizeObserver(fit)
    if (pageRef.current) observer.observe(pageRef.current)
    window.addEventListener('resize', fit)
    return () => { observer.disconnect(); window.removeEventListener('resize', fit) }
  }, [tab, node, book.outline, teardown])


  return (
    <ActionsContext.Provider value={tools}>
      <ColumnWidthContext.Provider value={column}>
      <SideFooterContext.Provider value={sideFooter ?? null}>
      <div className="desk-v2 desk-v2-theme desk-zoom">
        <DeskTop book={book} tab={tab} onTab={setTab} right={right} writing={writing} />
        {notice}
        <div className={`body${tab === '简介' ? ' wide' : ''}`} style={dock === 'side' ? { gridTemplateColumns: tab === '简介' ? `1fr ${sideWidth}px` : `300px 1fr ${sideWidth}px` } : undefined}>
          {tab === '简介' && <aside className="toc" />}
          {tab !== '简介' && <DeskDirectory key={tab} book={book} tab={tab} selected={tab === '设定' ? entry : tab === '正文' ? chapter : node} open={open}
            onSelect={tab === '设定' ? nav.openEntry : tab === '正文' ? nav.openChapter : nav.openNode}
            onToggle={id => setOpen(list => list.includes(id) ? list.filter(x => x !== id) : [...list, id])}
            footer={sideFooter} onNewEntry={newEntry} onSearchSelect={(id, word) => { nav.openChapter(id); setSearchWord(word); setSearchToken(n => n + 1) }}
            outlineTools={<div className="tools">{outlineAdd.map(item => <button type="button" className="btn seal-line" key={item.label} onClick={item.onClick}>{item.label}</button>)}</div>} />}
          <main ref={pageRef} className="desk">
            {tab === '简介' && <DeskIntro book={book} nav={nav} />}
            {tab === '设定' && <DeskSettings key={aliases[entry] ?? entry} book={book} selected={entry} nav={nav} fresh={fresh === entry} onNewEntry={newEntry} onAccept={accept} cardKey={id => aliases[id] ?? id} />}
            {tab === '大纲' && <DeskOutline key={`${node}:${nodeNonce}`} book={book} id={node} nav={nav} onAdd={addNode} onInsert={insertNode} onMove={moveNode} fresh={freshNode === node} writing={writing} />}
            {tab === '正文' && <DeskManuscript key={chapter} book={book} id={chapter} writing={writing} nav={nav} searchWord={searchWord} searchToken={searchToken} />}
          </main>
          {dock === 'side' && <DockedEditorial setDock={setDock} width={sideWidth} setWidth={setSideWidth} tools={chatTools}>{chat}</DockedEditorial>}
        </div>

        {dock === 'float' && <FloatingEditorial setDock={setDock} size={chatSize} tools={chatTools}>{chat}</FloatingEditorial>}
        {dock === 'ball' && chatBallNote && <div className="fixed right-24 bottom-[36px] z-40">{chatBallNote}</div>}
        {dock === 'ball' && (
          <div role="button" tabIndex={0} onClick={() => setDock('float')} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setDock('float') } }} title="编辑部"
            className="ball">
            编
            {!teardown && writing?.status.state === 'working' && <span aria-hidden className="absolute -inset-1 rounded-full border-2 border-chief/25 border-t-chief motion-safe:animate-spin" />}
            {chatBadge === undefined
              ? <span className="absolute top-1 right-1 size-3 rounded-full bg-seal ring-2 ring-paper" />
              : chatBadge > 0 && <span className="absolute -top-0.5 -right-0.5 flex min-w-5 items-center justify-center rounded-full bg-seal px-1 text-[11px] leading-5 text-on-role ring-2 ring-paper">{chatBadge > 99 ? '99+' : chatBadge}</span>}
          </div>
        )}

        <div className="desk-legacy" style={{ display: 'contents' }}><SelectionActions pageRef={pageRef} onToast={setToast} onUndo={onUndo} teardown={teardown} /></div>
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

