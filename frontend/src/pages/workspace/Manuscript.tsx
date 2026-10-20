/** 正文：左边目录按卷、单元排章；中间一页纸读正文、改正文；开写、停下、拍板。拍板的卡片长在要看的那一页上。 */

import clsx from 'clsx'
import { ChevronDown, ChevronLeft, ChevronRight, PenLine } from 'lucide-react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { searchBookText, type TextSearchResult } from '../../api/textSearch'
import { readTeardownReading, readingArrow, readingChapterNumber, teardownDefaultVolume, textMatches, writeTeardownReading } from '../../lib/teardownReading'
import { useSave, useWorkspace } from './actions'
import { chapterNodes, cn, countWords, findEntry, findNode, splitTitle, type VBook, type VGate, type VNode, type WritePlan, type WritingGates } from './model'
import { CardMenu, DirectoryShell, Editable, LinkChip, Sheet } from './widgets'
import { rowSelected, smallButton, titleClass } from './styles'
import { type ChapterDetail, GATE_LABELS, type WritingControl, chapterLabel, gateTarget, placeOf, readyToWrite, stuckRule, upcomingSteps, writePlans } from './writing'

/** 正文这几页要跳去的地方 */
export interface ManuscriptNav {
  openChapter: (id: string) => void
  openNode: (id: string) => void
  openEntry: (id: string) => void
  toast: (text: string) => void
}

const primaryButton = 'h-9 rounded-lg bg-ink px-5 text-sm text-paper-2 transition-colors hover:bg-ink-2 disabled:opacity-40'
const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

/** 存成一个 TXT 文件下载 */
function download(name: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = name.replace(/[<>:"/\\|?*]/g, '_')
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 等后台做完：带回的那句话、或者出的错，在页面底下说一声 */
function say(nav: ManuscriptNav, task: Promise<string | void>): void {
  task.then((text) => { if (text) nav.toast(text) }).catch((error: unknown) => nav.toast(errorText(error)))
}

/** 试读的卡片挂在前 3 章上，别的挂在它自己那一页。 */
function gateOn(gate: VGate | undefined, id: string, root: VNode): boolean {
  if (!gate) return false
  if (gate.kind === 'trial') return chapterNodes(root).slice(0, 3).some((c) => c.id === id)
  return gate.node === id
}

/* ---------------- 顶栏下面的写作条 ---------------- */

/** 编辑部在写、在等你、停下了：顶栏下面一条，点了能过去看。空闲时不显示。 */
export function WritingStrip({ writing, nav }: { writing: WritingControl; nav: ManuscriptNav }) {
  const s = writing.status
  if (s.state === 'idle') return null
  const link = 'font-medium underline-offset-2 hover:underline'
  const button = 'h-7 rounded-md border border-line-2 bg-card px-3 text-[13px] text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink'
  const tone = s.state === 'working' ? 'bg-chief-soft/70 text-chief' : s.state === 'waiting' || s.state === 'failed' ? 'bg-seal-soft/60 text-seal-dark' : 'bg-subtle text-ink-2'
  const dot = s.state === 'working' ? 'bg-chief motion-safe:animate-pulse' : s.state === 'waiting' || s.state === 'failed' ? 'bg-seal' : 'bg-ink-3/60'
  const go = s.gate ? gateTarget(s.gate) : {}
  let text: ReactNode = s.note
  let actions: ReactNode = null
  if (s.state === 'working') {
    text = <>{s.doing}{s.live !== undefined && <span className="tabular-nums"> · 已写 {countWords(s.live)} 字</span>}{s.stopping && ' · 写完这一章就停'}</>
    actions = (
      <>
        {s.chapter && <button type="button" className={link} onClick={() => nav.openChapter(s.chapter!)}>去看</button>}
        {!s.stopping && <button type="button" className={button} onClick={() => say(nav, writing.stop())}>停下</button>}
      </>
    )
  } else if (s.state === 'waiting' && s.gate) {
    text = `${s.gate.kind === 'stuck' ? '要你定夺' : '等你拍板'}：${s.gate.title}`
    actions = (
      <>
        <button type="button" className={link} onClick={() => (go.chapter ? nav.openChapter(go.chapter) : nav.openNode(go.node!))}>去看</button>
        <button type="button" className={button} onClick={() => say(nav, writing.stop())}>停下</button>
      </>
    )
  } else if (s.state === 'stopped' || s.state === 'failed') {
    text = s.state === 'failed' ? <>出错停下了：{s.error} {s.note}</> : s.note
    actions = <button type="button" className={button} onClick={() => say(nav, writing.resume())}>接着写</button>
  } else if (s.state === 'finished') {
    actions = <button type="button" className={button} onClick={() => writing.dismiss()}>好</button>
  }
  return (
    <div role="status" className={clsx('flex shrink-0 items-center justify-center gap-3 border-b border-line px-4 py-2 text-[13px]', tone)}>
      <span aria-hidden className={clsx('size-2 shrink-0 rounded-full', dot)} />
      <span className="min-w-0 truncate">{text}</span>
      {actions}
    </div>
  )
}

/* ---------------- 拍板 ---------------- */

const APPROVE: Record<VGate['kind'], string> = { trial: '读完了，接着写', stuck: '就用这一版', volume: '就这样，开写', chapters: '就这样，开写', segment: '就这样，往下写' }
const REVISE: Record<VGate['kind'], string> = { trial: '说说哪里不对', stuck: '告诉写手怎么改', volume: '让主编改', chapters: '让主编改', segment: '让主编改' }
const REVISE_HINT: Record<VGate['kind'], string> = {
  trial: '比如：对话太多，节奏再快一点；主角说话再狠一些。说了以后，之后每一章都照这个写',
  stuck: '比如：搜身那段改成赵长河其实翻过袖子，是陈默提前把东西藏在了嘴里',
  volume: '比如：单元三放宽到 5 章；讲经堂加一个能说话的女弟子',
  chapters: '比如：第 7 章考核写得太顺，加一处陈默差点暴露的地方',
  segment: '比如：第二篇先别进内门，在外门再苟一卷',
}
/** 这一种以后不用问我：关掉对应的开关 */
const GATE_OFF: Partial<Record<VGate['kind'], [keyof WritingGates, string]>> = {
  segment: ['segment', '以后每一篇都不用问我'],
  volume: ['volume', '以后每一卷都不用问我'],
  chapters: ['chapters', '以后章纲不用给我看'],
}

/** 等作者拍板的卡片：放在要看的那一页最上面。 */
export function GateCard({ gate, writing, nav, where }: { gate: VGate; writing: WritingControl; nav: ManuscriptNav; where?: string }) {
  const [asking, setAsking] = useState(false)
  const [text, setText] = useState('')
  const off = GATE_OFF[gate.kind]
  const who = gate.kind === 'stuck' ? '写手' : gate.kind === 'trial' ? '编辑部' : '主编'
  const send = () => {
    say(nav, writing.revise(text))
    setText('')
    setAsking(false)
  }
  return (
    <div className="mb-9 rounded-xl border border-seal/25 bg-seal-soft/45 px-6 py-5">
      <p className="flex items-center gap-2 text-[13px] tracking-wider text-seal-dark">
        <span aria-hidden className="size-2 rounded-full bg-seal" />
        {gate.kind === 'stuck' ? '要你定夺' : '等你拍板'} · {gate.title}{where && <span className="text-ink-3">· {where}</span>}
      </p>
      <p className="mt-2.5 text-[15px] leading-relaxed text-ink">{gate.hint}</p>
      {gate.detail && (
        <div className="mt-3.5 rounded-lg border border-line bg-card px-5 py-4">
          {gate.detail.title && <p className="font-serif text-[17px] font-bold text-ink">{gate.detail.title}</p>}
          {gate.detail.text && <p className="mt-1.5 font-serif text-[15px] leading-[1.9] whitespace-pre-line text-ink-2">{gate.detail.text}</p>}
          {!!gate.detail.items?.length && (
            <ul className="mt-2.5 space-y-1 border-t border-line pt-2.5 text-[14px] leading-relaxed text-ink-2">
              {gate.detail.items.map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
        </div>
      )}
      {!!gate.issues?.length && (
        <ul className="mt-3 space-y-1.5 text-[14px] leading-relaxed text-ink-2">
          {gate.issues.map((issue) => <li key={issue} className="flex gap-2.5"><span className="mt-0.5 shrink-0 text-xs text-reviewer">审稿</span>{issue}</li>)}
        </ul>
      )}
      {gate.revising ? (
        <p className="mt-4 flex items-center gap-2 text-[13px] text-chief"><span aria-hidden className="size-2 shrink-0 rounded-full bg-chief motion-safe:animate-pulse" />主编在照你说的改，一般半分钟上下，改好了直接换上…</p>
      ) : asking ? (
        <div className="mt-4">
          <textarea autoFocus value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder={REVISE_HINT[gate.kind]}
            className="w-full resize-none rounded-xl border border-line-2 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
          <div className="mt-2.5 flex items-center justify-end gap-2">
            <button type="button" onClick={() => setAsking(false)} className="h-9 rounded-lg px-3 text-sm text-ink-2 hover:bg-card/70">取消</button>
            <button type="button" onClick={send} disabled={!text.trim()} className={primaryButton}>交给{who}</button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="button" className={primaryButton} onClick={() => say(nav, writing.approve())}>{APPROVE[gate.kind]}</button>
          <button type="button" className={clsx(smallButton, 'h-9 px-4 text-sm')} onClick={() => setAsking(true)}>{REVISE[gate.kind]}</button>
          {off && <button type="button" className="ml-auto text-[13px] text-ink-3 hover:text-ink" onClick={() => say(nav, writing.setGate(off[0], false))}>{off[1]}</button>}
        </div>
      )}
    </div>
  )
}

/* ---------------- 左边目录 ---------------- */

interface Group { volume: VNode; units: { unit?: VNode; chapters: VNode[] }[] }

/** 按卷分组，卷里按单元；还没出章纲的单元不列。 */
function groupsOf(root: VNode): Group[] {
  const groups: Group[] = []
  const walk = (node: VNode) => {
    if (node.kind === '卷') {
      const loose = (node.children ?? []).filter((c) => c.kind === '章')
      const units: Group['units'] = (node.children ?? []).filter((c) => c.kind === '单元' && c.children?.length).map((unit) => ({ unit, chapters: unit.children ?? [] }))
      if (loose.length) units.unshift({ unit: undefined, chapters: loose })
      if (units.length) groups.push({ volume: node, units })
      return
    }
    node.children?.forEach(walk)
  }
  walk(root)
  return groups
}

function ChapterRow({ node, selected, mark, onSelect }: { node: VNode; selected: boolean; mark?: 'writing' | 'gate'; onSelect: () => void }) {
  const planned = (node.body?.status ?? 'planned') === 'planned' && mark !== 'writing'
  return (
    <button type="button" onClick={onSelect} title={node.title}
      className={clsx('flex w-full items-center gap-2 rounded-md py-[7px] pr-2.5 pl-2.5 text-left font-serif text-[15px] transition-colors 2xl:text-base',
        selected ? `${rowSelected} font-bold text-ink` : planned ? 'text-ink-3 hover:bg-line/40 hover:text-ink-2' : 'text-ink-2 hover:bg-line/40 hover:text-ink')}>
      <span className="truncate">{node.title.replace('　', ' ')}</span>
      {mark === 'writing' && <span aria-label="正在写" className="ml-auto size-2 shrink-0 rounded-full bg-writer motion-safe:animate-pulse" />}
      {mark === 'gate' && <span aria-label="等你看" className="ml-auto size-2 shrink-0 rounded-full bg-seal" />}
    </button>
  )
}

export function ManuscriptDirectory({ book, selected, onSelect, onSearchSelect, onExport, writing }: { book: VBook; selected: string; onSelect: (id: string) => void; onSearchSelect?: (id: string, word: string) => void; onExport: () => void; writing: WritingControl }) {
  const { actions } = useWorkspace()
  const [query, setQuery] = useState('')
  const [searchRun, setSearchRun] = useState(0)
  const [search, setSearch] = useState<{ query: string; data?: TextSearchResult; error?: string }>()
  const immediateSearch = useRef(false)
  const teardown = book.source === 'teardown'
  const groups = groupsOf(book.outline)
  const chapters = chapterNodes(book.outline)
  const done = chapters.filter((c) => c.body?.status === 'done')
  const status = writing.status
  const gate = status.state === 'waiting' ? status.gate : undefined
  // 默认只展开眼下在写的那一卷，和选中的那一章所在的卷
  const current = chapters.find((c) => c.body?.status !== 'done') ?? chapters.at(-1)
  const here = (id?: string) => (id ? placeOf(book.outline, id).volume?.id : undefined)
  const [open, setOpen] = useState<string[]>(() => (teardown ? [teardownDefaultVolume(book)] : [here(selected), here(current?.id)]).filter((v): v is string => !!v))
  const markOf = (id: string): 'writing' | 'gate' | undefined => teardown ? undefined : (status.chapter === id ? 'writing' : gateOn(gate, id, book.outline) ? 'gate' : undefined)
  const q = query.trim()
  useEffect(() => {
    if (!q || !actions.live) return
    const controller = new AbortController()
    const delay = immediateSearch.current ? 0 : 400
    immediateSearch.current = false
    const timer = setTimeout(() => {
      searchBookText(book.id, q, controller.signal)
        .then(data => { if (!controller.signal.aborted) setSearch({ query: q, data }) })
        .catch((error: unknown) => { if (!controller.signal.aborted) setSearch({ query: q, error: errorText(error) }) })
    }, delay)
    return () => { clearTimeout(timer); controller.abort() }
  }, [actions.live, book.id, q, searchRun])
  const found = search?.query === q ? search : undefined
  return (
    <div className="contents" onKeyDownCapture={(event) => {
      if (event.key === 'Enter' && !event.nativeEvent.isComposing && event.target instanceof HTMLInputElement) {
        event.preventDefault()
        immediateSearch.current = true
        setSearchRun(run => run + 1)
      }
    }}>
    <DirectoryShell title="正文" search="找章节、搜原文……" query={query} onQuery={setQuery} onTitle={() => onSelect('home')}
      footer={!q && done.length > 0 && (
        <button type="button" onClick={onExport} className={clsx(smallButton, 'mt-4 w-full bg-card/70')}>导出全书 TXT</button>
      )}>
      {q ? (
        <>{(() => {
          const hits = chapters.filter((c) => c.title.includes(q))
          return hits.length
            ? hits.map((c) => <ChapterRow key={c.id} node={c} selected={selected === c.id} mark={markOf(c.id)} onSelect={() => onSelect(c.id)} />)
            : <p className="px-2.5 py-2 text-[13px] text-ink-3">没找到「{q}」</p>
        })()}
          {actions.live && <section className="mt-4 border-t border-line pt-3" aria-label="原文搜索结果">
            {found?.error ? <p role="alert" className="px-2.5 py-2 text-[13px] text-seal-dark">{found.error}</p>
              : found?.data ? <>
                <p className="px-2.5 py-2 text-[13px] leading-relaxed text-ink-3">{found.data.chapters ? `原文里有「${q}」的章（${found.data.chapters} 章）` : `${teardown ? '原文' : '正文'}里没有「${q}」`}</p>
                {found.data.results.map(hit => {
                  const chapter = chapters.find(c => readingChapterNumber(c) === hit.index)
                  if (!chapter) return null
                  return <button key={hit.index} type="button" onClick={() => onSearchSelect ? onSearchSelect(chapter.id, q) : onSelect(chapter.id)}
                    className={clsx('mb-1 block w-full rounded-md px-2.5 py-2 text-left hover:bg-line/40', selected === chapter.id && rowSelected)}>
                    <span className="block text-[14px] text-ink-2">第 {hit.index} 章{hit.title && ` ${hit.title}`} · {hit.times} 次</span>
                    <span className="mt-1 line-clamp-2 block text-[12px] leading-relaxed text-ink-3">{textMatches(hit.near, q).map((part, i) => part.match ? <mark key={i} className="rounded-sm bg-seal/15 text-seal-dark">{part.text}</mark> : part.text)}</span>
                  </button>
                })}
              </> : <p className="px-2.5 py-2 text-[13px] text-ink-3">正在搜原文……</p>}
          </section>}
        </>
      ) : (
        <>
          <button type="button" onClick={() => onSelect('home')}
            className={clsx('mb-1 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors', selected === 'home' ? `${rowSelected} font-medium text-ink` : 'text-ink-2 hover:bg-line/50')}>
            <PenLine className="size-3.5 text-ink-3" />
            {teardown ? '正文首页' : done.length ? '接着写' : '开写'}
            <span className="ml-auto pr-0.5 text-xs text-ink-3 tabular-nums">{teardown ? `已导入 ${chapters.length} 章` : done.length ? `已写 ${done.length} 章` : '还没写'}</span>
          </button>
          {!groups.length && !teardown && <p className="px-2.5 py-3 text-[13px] leading-relaxed text-ink-3">还没有章。开写以后，章纲和写好的章按卷排在这里。</p>}
          {groups.map(({ volume, units }) => {
            const all = units.flatMap((u) => u.chapters)
            const expanded = open.includes(volume.id) || all.some((c) => c.id === selected)
            const written = all.filter((c) => c.body?.status === 'done').length
            return (
              <div key={volume.id} className="mt-1.5">
                <button type="button" onClick={() => setOpen(expanded ? open.filter((x) => x !== volume.id) : [...open, volume.id])}
                  className="flex w-full items-center rounded-md text-left transition-colors hover:bg-line/50">
                  <span className="flex size-7 items-center justify-center text-ink-3">{expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}</span>
                  <span className="min-w-0 flex-1 truncate py-1.5 text-sm text-ink-2">{volume.title.replace('　', ' ')}</span>
                  <span className="pr-3 text-xs text-ink-3 tabular-nums">{written}/{all.length}</span>
                </button>
                {expanded && (
                  <div className="mt-0.5 mb-1 ml-[17px] border-l border-line pl-1.5">
                    {units.map(({ unit, chapters: list }) => (
                      <div key={unit?.id ?? 'loose'}>
                        {unit && <p className="truncate px-2.5 pt-2 pb-1 text-xs text-ink-3">{unit.title.replace('　', ' ')}</p>}
                        {list.map((c) => <ChapterRow key={c.id} node={c} selected={selected === c.id} mark={markOf(c.id)} onSelect={() => onSelect(c.id)} />)}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </>
      )}
    </DirectoryShell>
    </div>
  )
}

/* ---------------- 开写 ---------------- */

/** 停在哪由你定：四个开关，写到那里停下来请你看。 */
function GateToggles({ writing, nav }: { writing: WritingControl; nav: ManuscriptNav }) {
  return (
    <section>
      <h3 className="mb-1.5 text-[13px] tracking-[0.15em] text-ink-3">停在哪由你定</h3>
      <p className="mb-3 text-[13px] text-ink-3">勾上的地方，编辑部写到那里会停下来请你看；不勾的，编辑部自己定，定了在群聊里说一声。</p>
      <div className="divide-y divide-line border-y border-line">
        {GATE_LABELS.map((g) => (
          <label key={g.key} className="flex cursor-pointer items-start gap-3 py-3">
            <input type="checkbox" checked={writing.gates[g.key]} onChange={(e) => say(nav, writing.setGate(g.key, e.target.checked))}
              className="mt-1 size-4 shrink-0 accent-[var(--color-ink)]" />
            <span className="text-[15px] text-ink">
              {g.label}
              {g.note && <span className="mt-0.5 block text-[13px] text-ink-3">{g.note}</span>}
            </span>
          </label>
        ))}
      </div>
      <p className="mt-2.5 text-[13px] text-ink-3">{stuckRule(writing.rewrites)}</p>
    </section>
  )
}

/** 正文首页：写了多少、开写（或接着写）、停在哪由你定。 */
export function ManuscriptHome({ book, writing, nav }: { book: VBook; writing: WritingControl; nav: ManuscriptNav }) {
  const chapters = chapterNodes(book.outline)
  const done = chapters.filter((c) => c.body?.status === 'done')
  const words = done.reduce((sum, c) => sum + (c.body?.words ?? 0), 0)
  const next = chapters.find((c) => c.body?.status !== 'done')
  const where = next ? placeOf(book.outline, next.id) : {}
  const plans = writePlans(book.outline)
  const [plan, setPlan] = useState<WritePlan>(done.length < 3 && writing.gates.trial && !writing.trialDone ? '3' : 'unit')
  const picked = plans.find((p) => p.key === plan) ?? plans[0]
  const missing = readyToWrite(book.outline)
  const s = writing.status
  const busy = s.state === 'working' || s.state === 'waiting'
  if (book.source === 'teardown') {
    const saved = readTeardownReading(book.id)
    const resume = saved ? chapters.find(chapter => readingChapterNumber(chapter) === saved.chapter) : undefined
    const first = chapters[0]
    return <Sheet narrow>
      <h1 className={titleClass}>正文</h1>
      <p className="mt-4 text-[15px] text-ink-2">已导入 {book.teardown?.chapters ?? chapters.length} 章 · 还没开拆</p>
      {first && <button type="button" className={clsx(primaryButton, 'mt-8 h-auto min-h-11 px-7 py-3 text-left text-base')} onClick={() => nav.openChapter((resume ?? first).id)}>
        {resume ? `接着读第 ${readingChapterNumber(resume)} 章《${splitTitle(resume.title)[1] || `第 ${readingChapterNumber(resume)} 章`}》` : '从第 1 章读起'}
      </button>}
    </Sheet>
  }
  return (
    <Sheet narrow>
      <h1 className={titleClass}>{done.length ? '接着写' : '开写'}</h1>
      <p className="mt-4 text-[15px] text-ink-2">
        {done.length
          ? <>已写 {done.length} 章 · {words.toLocaleString()} 字{next && where.volume && <> · 写到 {[where.volume, where.unit].filter(Boolean).map((n) => n!.title.replace('　', ' ')).join(' / ')}</>}</>
          : busy ? '第一章还在写，写完一章这里记一章。' : '还没开写。点了开写，编辑部照大纲一层层往下拆，再一章章写正文。'}
      </p>
      <div className="mt-8 border-t border-line pt-8">
        {missing ? (
          <div>
            <p className="text-[15px] leading-relaxed text-ink-2">{missing}</p>
            <button type="button" className={clsx(primaryButton, 'mt-4')} onClick={() => nav.openNode(book.outline.children?.[0]?.id ?? 'book')}>去大纲</button>
          </div>
        ) : busy ? (
          <div>
            <p className="text-[15px] leading-relaxed text-ink-2">
              {s.state === 'working' ? `编辑部正在写：${s.doing ?? ''}。` : `编辑部在等你拍板：${s.gate?.title ?? ''}。`}
              这一轮写完或停下以后，才能开新的一轮。
            </p>
            {!s.stopping && (
              <button type="button" className="mt-4 h-9 rounded-lg border border-line-2 bg-card px-5 text-sm text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink"
                onClick={() => say(nav, writing.stop())}>停下这一轮</button>
            )}
          </div>
        ) : s.state === 'stopped' || s.state === 'failed' ? (
          <div>
            <p className="text-[15px] leading-relaxed text-ink-2">{s.state === 'failed' ? `出错停下了：${s.error} ` : ''}{s.note}</p>
            <button type="button" className={clsx(primaryButton, 'mt-4')} onClick={() => say(nav, writing.resume())}>接着写</button>
          </div>
        ) : (
          <div>
            <h3 className="mb-3 text-[13px] tracking-[0.15em] text-ink-3">这一轮写多少</h3>
            <div className="flex flex-wrap gap-2">
              {plans.map((p) => (
                <button key={p.key} type="button" aria-pressed={plan === p.key} onClick={() => setPlan(p.key)}
                  className={clsx('h-9 rounded-lg border px-4 text-sm transition-colors', plan === p.key ? 'border-ink bg-ink text-paper-2' : 'border-line-2 bg-card text-ink-2 hover:border-ink-3/50 hover:text-ink')}>
                  {p.label}
                </button>
              ))}
            </div>
            <p className="mt-2.5 text-[13px] text-ink-3">{picked.hint}</p>
            {writing.blocked
              ? <p className="mt-5 text-[14px] text-ink-3">{writing.blocked}</p>
              : <button type="button" className={clsx(primaryButton, 'mt-5 h-10 px-7')} onClick={() => say(nav, writing.start(plan))}>{done.length ? '接着写' : '开写'}</button>}
            <h3 className="mt-9 mb-2.5 text-[13px] tracking-[0.15em] text-ink-3">开写以后会这样走</h3>
            <ol className="list-decimal space-y-1.5 pl-5 text-[15px] leading-relaxed text-ink-2 marker:text-ink-3">
              {upcomingSteps(book.outline, writing.gates, writing.trialDone, writing.rewrites).map((step) => <li key={step}>{step}</li>)}
            </ol>
          </div>
        )}
      </div>
      <div className="mt-9 border-t border-line pt-8">
        <GateToggles writing={writing} nav={nav} />
      </div>
    </Sheet>
  )
}

/* ---------------- 一章 ---------------- */

/** 「第3章」写成「第三章」，放在标题上面 */
function chapterNumberLabel(prefix: string): string {
  const n = Number(/第(\d+)章/.exec(prefix)?.[1])
  return n ? `第${cn(n)}章` : prefix
}

const paragraphsOf = (text: string) => text.split('\n').map((p) => p.replace(/^[\s　]+/, '').trim()).filter(Boolean)
const escapeHtml = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const toHtml = (text: string, word = '') => paragraphsOf(text).map((p) => `<p>${textMatches(p, word).map(part => part.match ? `<mark data-text-match class="rounded-sm bg-seal/15 text-seal-dark">${escapeHtml(part.text)}</mark>` : escapeHtml(part.text)).join('')}</p>`).join('')

/** 正文：点哪改哪，离开就存，Esc 撤回这次改的。页面上一段一个块，存的时候一段一行。 */
function ChapterText({ text, onSave, readOnly, spot, searchWord = '', searchToken }: { text: string; onSave?: (text: string) => void; readOnly?: boolean; spot?: string; searchWord?: string; searchToken?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const saved = useRef(text)
  const highlight = useRef('')
  // 外面的字变了：不在改的时候才换上
  useLayoutEffect(() => {
    const el = ref.current
    saved.current = text
    if (el && (highlight.current !== searchWord || (document.activeElement !== el && paragraphsOf(el.innerText).join('\n') !== paragraphsOf(text).join('\n')))) el.innerHTML = toHtml(text, searchWord)
    highlight.current = searchWord
    if (searchWord) {
      const frame = requestAnimationFrame(() => el?.querySelector('[data-text-match]')?.scrollIntoView({ block: 'center' }))
      return () => cancelAnimationFrame(frame)
    }
  }, [text, searchWord, searchToken])
  const editable = !!onSave && !readOnly
  return (
    <div ref={ref} contentEditable={editable} suppressContentEditableWarning spellCheck={false}
      role={editable ? 'textbox' : undefined} aria-multiline={editable || undefined} aria-label={editable ? '正文' : undefined} data-spot={spot}
      // 回车另起一段，粘贴只要字
      onFocus={() => { if (editable) document.execCommand('defaultParagraphSeparator', false, 'p') }}
      onPaste={(e) => {
        if (!editable) return
        e.preventDefault()
        document.execCommand('insertText', false, e.clipboardData.getData('text/plain'))
      }}
      onKeyDown={(e) => {
        if (!editable || e.key !== 'Escape') return
        e.currentTarget.innerHTML = toHtml(saved.current)
        e.currentTarget.blur()
      }}
      onBlur={(e) => {
        const value = paragraphsOf(e.currentTarget.innerText).join('\n')
        if (editable && onSave && value !== paragraphsOf(saved.current).join('\n')) {
          saved.current = value
          onSave(value)
        }
      }}
      className="chapter-prose outline-none" />
  )
}

/** 写手正在写：字一句句冒出来，最后一句后面跟着光标。 */
function LiveText({ text }: { text: string }) {
  const paragraphs = paragraphsOf(text)
  return (
    <div aria-live="polite" className="chapter-prose">
      {paragraphs.length ? paragraphs.map((p, i) => (
        <p key={i}><span className={clsx(i === paragraphs.length - 1 && 'caret')}>{p}</span></p>
      )) : <p className="caret" />}
    </div>
  )
}

/** 一块能折起来的资料：章纲、设定的变化、审稿。 */
function Fold({ title, count, defaultOpen = false, children }: { title: string; count?: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 py-2.5 text-left text-[13px] tracking-[0.15em] text-ink-3 hover:text-ink">
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        {title}
        {count && <span className="tracking-normal">· {count}</span>}
      </button>
      {open && <div className="pb-4 pl-5.5">{children}</div>}
    </section>
  )
}

/** 按意见重写这一章。 */
function RewritePanel({ node, later, onCancel, onGo }: { node: VNode; later: number; onCancel: () => void; onGo: (request: string) => void }) {
  const [request, setRequest] = useState('')
  return (
    <div className="mb-9 rounded-2xl border border-line bg-subtle p-5">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-full bg-writer font-serif text-xs text-on-role">写</span>
        <p className="text-[15px] text-ink">想让{chapterLabel(node)}怎么改？</p>
      </div>
      <textarea autoFocus value={request} onChange={(e) => setRequest(e.target.value)} rows={2}
        placeholder="比如：打斗再写足一点；赵长河的话再阴一些；结尾留个更大的悬念"
        className="w-full resize-none rounded-xl border border-line-2 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
      {later > 0 && <p className="mt-2.5 text-[13px] text-seal-dark">这一章后面已经写好了 {later} 章，后面的不会跟着改；改动大的话，后文可能接不上。</p>}
      <div className="mt-3 flex items-center justify-between gap-4">
        <p className="text-xs text-ink-3">写手照你说的重写，照样过审稿；这一章原来记进设定的变化，会先撤掉再重记。</p>
        <div className="flex shrink-0 gap-2">
          <button type="button" onClick={onCancel} className="h-9 rounded-lg px-3 text-sm text-ink-2 hover:bg-card/70">取消</button>
          <button type="button" onClick={() => onGo(request)} disabled={!request.trim()} className={primaryButton}>重写</button>
        </div>
      </div>
    </div>
  )
}

export function ChapterPage({ book, id, writing, nav, searchWord, searchToken }: { book: VBook; id: string; writing: WritingControl; nav: ManuscriptNav; searchWord?: string; searchToken?: number }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const path = findNode(book.outline, id) ?? []
  const node = path.at(-1)
  const [loadResult, setLoadResult] = useState<{ node: VNode; attempt: number; detail?: ChapterDetail; error?: string }>()
  const [loadAttempt, setLoadAttempt] = useState(0)
  const result = loadResult?.node === node && loadResult?.attempt === loadAttempt ? loadResult : undefined
  const loaded = result?.detail
  const loadError = result?.error
  const [rewriting, setRewriting] = useState(false)
  const [previous, setPrevious] = useState<string>()
  const teardown = book.source === 'teardown'
  const chapters = chapterNodes(book.outline)
  const at = chapters.findIndex((c) => c.id === id)
  const prev = chapters[at - 1]
  const next = chapters[at + 1]
  const chapterNumber = node ? readingChapterNumber(node) : 0
  useEffect(() => {
    if (teardown && chapterNumber > 0) writeTeardownReading(book.id, chapterNumber)
  }, [book.id, chapterNumber, teardown])
  useEffect(() => {
    if (!teardown) return
    const turn = (event: KeyboardEvent) => {
      const direction = readingArrow(event)
      const target = direction === -1 ? prev : direction === 1 ? next : undefined
      if (!target) return
      event.preventDefault()
      nav.openChapter(target.id)
    }
    window.addEventListener('keydown', turn)
    return () => window.removeEventListener('keydown', turn)
  }, [nav, next, prev, teardown])
  const body = node?.body
  // 真书点开才去读正文、审稿、设定的变化；写完、改完以后再读一遍
  const loadChapter = writing.loadChapter
  useEffect(() => {
    if (!node || body?.text !== undefined || (body?.status ?? 'planned') === 'planned' || !loadChapter) return
    let alive = true
    loadChapter(node)
      .then((detail) => { if (alive) setLoadResult({ node, attempt: loadAttempt, detail }) })
      .catch((error: unknown) => { if (alive) setLoadResult({ node, attempt: loadAttempt, error: errorText(error) }) })
    return () => { alive = false }
  }, [node, body?.text, body?.status, body?.words, loadChapter, loadAttempt])
  if (!node || node.kind !== '章') return <Sheet narrow><p className="text-ink-3">这一章找不到了。</p></Sheet>

  const { volume, unit } = placeOf(book.outline, id)
  const s = writing.status
  const live = !teardown && s.chapter === id ? s.live : undefined
  const gate = !teardown && s.state === 'waiting' && gateOn(s.gate, id, book.outline) ? s.gate : undefined
  const status = body?.status ?? 'planned'
  const text = body?.text ?? loaded?.text
  const busy = s.state === 'working' || s.state === 'waiting'
  const later = chapters.slice(at + 1).filter((c) => c.body?.status === 'done').length
  const [prefix, name] = splitTitle(node.title)
  const nextToWrite = chapters.find((c) => c.body?.status !== 'done')
  const meta = live !== undefined
    ? `写手在写 · 已写 ${countWords(live)} 字`
    : status === 'done' ? `${(body?.words ?? 0).toLocaleString()} 字`
      : status === 'writing' ? (gate?.kind === 'stuck' ? `写好了 ${(body?.words ?? 0).toLocaleString()} 字，审稿没过` : '写到一半') : '还没写'
  const review = body?.review ?? loaded?.review
  const changes = body?.changes ?? loaded?.changes
  const menu = status === 'done' && text ? [
    ...(!teardown ? [{ label: '按意见重写这一章', onClick: () => (busy ? nav.toast('编辑部手上还有活，停下或写完以后再重写') : writing.blocked ? nav.toast(writing.blocked) : setRewriting(true)) }] : []),
    ...(!teardown && writing.redigest ? [{ label: '让设定师照改过的重看一遍', onClick: () => say(nav, writing.redigest!(node)) }] : []),
    { label: '导出这一章 TXT', onClick: () => download(`${node.title.replace('　', ' ')}.txt`, `${node.title.replace('　', ' ')}\n\n${text}\n`) },
  ] : []
  const cast = node.uses.map((entryId) => findEntry(book, entryId)).filter((e) => !!e)

  return (
    <div className="mx-auto w-full px-8 py-10 2xl:py-14">
      <article className="chapter-sheet group/card relative mx-auto max-w-[45em] rounded-xl border border-line bg-manuscript px-[2.6em] pt-[2.4em] pb-[2em] shadow-[var(--shadow-paper)]">
      {menu.length > 0 && <CardMenu items={menu} />}
      <header className="text-center">
        {(volume || unit) && <p className="text-[13px] tracking-[0.2em] text-ink-3">{[volume, unit].filter(Boolean).map((n) => n!.title.replace('　', ' ')).join(' · ')}</p>}
        <p className="mt-[1.6em] font-serif text-[0.85em] tracking-[0.5em] text-ink-3">{teardown ? `第 ${chapterNumber} 章` : chapterNumberLabel(prefix)}</p>
        <Editable value={name} placeholder={teardown ? `第 ${chapterNumber} 章` : '给这一章起个名字'} className="mx-auto mt-[0.3em] w-fit min-w-40 font-serif text-[1.75em] leading-snug font-bold text-ink"
          onSave={(value) => { if (value.trim()) save(actions.saveNode(node, { name: value.trim() })) }} />
        <div className="mt-[0.9em] flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[13px] text-ink-3">
          <span className={clsx(live !== undefined && 'text-writer')}>{meta}</span>
          {!teardown && !!body?.attempts && <span>审稿退回重写过 {body.attempts} 次</span>}
          <button type="button" onClick={() => nav.openNode(id)} className="text-chief hover:underline">去大纲看章纲</button>
        </div>
        {!teardown && previous !== undefined && status === 'done' && s.state !== 'working' && (
          <p className="mt-2 text-[13px] text-ink-3">
            这是照你的意见重写的一版。
            <button type="button" className="ml-2 text-chief hover:underline" onClick={() => { say(nav, writing.setText(node, previous).then(() => '换回了原来的')); setPrevious(undefined) }}>换回原来的</button>
          </p>
        )}
      </header>

      <div className="mt-[2.2em]">
        {gate && <GateCard gate={gate} writing={writing} nav={nav} where={gate.kind === 'trial' ? `这是第 ${at + 1} 章` : undefined} />}
        {!teardown && rewriting && (
          <RewritePanel node={node} later={later} onCancel={() => setRewriting(false)}
            onGo={(request) => {
              setRewriting(false)
              writing.rewrite(node, request)
                .then((before) => (before === null ? nav.toast('交给写手了：写好会在这里换上，照样过审稿') : setPrevious(before)))
                .catch((error: unknown) => nav.toast(errorText(error)))
            }} />
        )}
        {live !== undefined ? (
          <>
            <p className="mb-6 flex items-center gap-2 text-[13px] text-writer"><span aria-hidden className="size-2 shrink-0 rounded-full bg-writer motion-safe:animate-pulse" />写手正在写这一章，写完先过审稿，再由设定师记下变化。</p>
            <LiveText text={live} />
          </>
        ) : text !== undefined && status !== 'planned' ? (
          <ChapterText text={text} spot={`t|${id}`} readOnly={teardown} searchWord={searchWord} searchToken={searchToken} onSave={teardown ? undefined : (value) => say(nav, writing.setText(node, value).then(() => '存好了'))} />
        ) : loadError ? (
          <div className="rounded-xl border border-line px-6 py-5">
            <p role="alert" className="text-[14px] text-seal-dark">{loadError}</p>
            <button type="button" className={clsx(smallButton, 'mt-3')} onClick={() => setLoadAttempt(attempt => attempt + 1)}>重新加载</button>
          </div>
        ) : status !== 'planned' ? (
          <p className="text-ink-3">正在读这一章…</p>
        ) : (
          <div className="rounded-xl border border-dashed border-line-2 px-6 py-8 text-center">
            <p className="font-serif text-lg text-ink-2">这一章还没写</p>
            <p className="mt-2 text-[14px] leading-relaxed text-ink-3">
              {nextToWrite?.id === id ? '接着写就从这一章开始。' : '写到这里时，正文会在这里一句句出来。'}章纲在大纲里，想改去那里改。
            </p>
            {!teardown && nextToWrite?.id === id && !busy && <button type="button" className={clsx(primaryButton, 'mt-4')} onClick={() => nav.openChapter('home')}>去开写</button>}
          </div>
        )}
      </div>

      {!teardown && (!!changes?.length || !!review?.good.length || !!review?.issues.length || cast.length > 0) && (
      <div className="mt-10 border-t border-line pt-3">
        {!!changes?.length && (
          <Fold title="设定师记下的变化" count={`${changes.length} 处`}>
            <ul className="space-y-1.5 text-[14px] leading-relaxed text-ink-2">{changes.map((c) => <li key={c} className="flex gap-2"><span className="text-lore">·</span>{c}</li>)}</ul>
          </Fold>
        )}
        {review && (review.good.length > 0 || review.issues.length > 0) && (
          <Fold title="审稿" count={[review.good.length && `说好 ${review.good.length} 条`, review.issues.length && `还能更好 ${review.issues.length} 条`].filter(Boolean).join('，')}>
            <ul className="space-y-1.5 text-[14px] leading-relaxed text-ink-2">
              {review.good.map((g) => <li key={g} className="flex gap-2"><span className="text-lore">✓</span>{g}</li>)}
              {review.issues.map((g) => <li key={g} className="flex gap-2"><span className="text-reviewer">→</span>{g}</li>)}
            </ul>
          </Fold>
        )}
        {cast.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 py-3 text-[13px] text-ink-3">
            <span className="mr-1 tracking-[0.15em]">用到的设定</span>
            {cast.map((e) => <LinkChip key={e!.id} onClick={() => nav.openEntry(e!.id)}>{e!.name}</LinkChip>)}
          </div>
        )}
      </div>
      )}

      <nav className="mt-6 flex items-center justify-between border-t border-line pt-5 text-[14px] text-ink-2" aria-label="翻章">
        {prev ? <button type="button" onClick={() => nav.openChapter(prev.id)} className="flex items-center gap-1 hover:text-seal"><ChevronLeft className="size-4" />{teardown ? '上一章' : prev.title.replace('　', ' ')}</button> : <span />}
        {next ? <button type="button" onClick={() => nav.openChapter(next.id)} className="flex items-center gap-1 hover:text-seal">{teardown ? '下一章' : next.title.replace('　', ' ')}<ChevronRight className="size-4" /></button> : <span />}
      </nav>
      </article>
    </div>
  )
}
