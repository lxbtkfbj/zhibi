/** 工作台原型：和新书页同一套界面，书换成示例书、空书或旧书快照，改的东西只留在这一页。 */

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronUp, Library, PenLine, Settings } from 'lucide-react'
import { useCallback, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { get } from '../../api/client'
import type { LibrarySnapshot } from '../../api/library'
import type { BookSummary, Chapter, ChapterBrief } from '../../api/types'
import type { OutlineTree } from '../../lib/outlineTree'
import { useLocalBook } from './actions'
import { type ApiParts, bookFromApi } from './fromApi'
import type { VBook, VNode } from './model'
import { SAMPLE_BOOK, emptyBook } from './sampleBook'
import { EditorialChat } from './Chat'
import { useChatSim } from './chatSim'
import { SampleInbox, type Tab, Workspace } from './Workspace'
import { DEMOS, type DemoKind, useWritingSim } from './writingSim'

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
          <p className="mt-2 px-3 pb-1 text-xs tracking-wider text-ink-3">你书架上的书 · 这里改了不存</p>
          {shelf.isPending && <p className="px-3 py-2 text-[13px] text-ink-3">正在读书架…</p>}
          {shelf.data?.map((b) => item(`live:${b.id}`, b.title || '未命名', [b.genre, b.idea].filter(Boolean).join(' · ').slice(0, 40) || '没有简介'))}
          {shelf.data?.length === 0 && <p className="px-3 py-2 text-[13px] text-ink-3">书架是空的</p>}
          <p className="mt-2 px-3 pb-1 text-xs tracking-wider text-ink-3">以前的书 · 快照，这里改了不存</p>
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

/** 原型左下角：直接跳到写作的几种样子，不用干等编辑部写到那一步。 */
function DemoMenu({ onPick }: { onPick: (kind: DemoKind) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="fixed bottom-4 left-4 z-30">
      {open && (
        <div className="absolute bottom-[calc(100%+8px)] left-0 w-64 rounded-xl border border-line bg-card p-2 shadow-[var(--shadow-lift)]">
          <p className="px-3 pt-1 pb-1.5 text-xs tracking-wider text-ink-3">原型 · 直接看写作的几种样子</p>
          {DEMOS.map((d) => (
            <button key={d.key} type="button" onClick={() => { onPick(d.key); setOpen(false) }}
              className="block w-full rounded-lg px-3 py-2 text-left text-[14px] text-ink-2 transition-colors hover:bg-subtle hover:text-ink">
              {d.label}
            </button>
          ))}
        </div>
      )}
      <button type="button" onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-full border border-writer/30 bg-writer-soft py-1.5 pr-3 pl-3.5 text-xs text-writer shadow-[var(--shadow-paper)] transition-colors hover:border-writer/60">
        <PenLine className="size-3.5" />
        原型 · 演示写作
        <ChevronUp className={clsx('size-3.5 transition-transform', !open && 'rotate-180')} />
      </button>
    </div>
  )
}

/** 链接上的 ?tab=text（正文）、outline（大纲）、blurb（简介），node=大纲那一段，chapter=正文那一章 */
const TABS: Record<string, Tab> = { text: '正文', outline: '大纲', blurb: '简介', settings: '设定' }

function PrototypeDesk({ book: initial, switcher, source }: { book: VBook; switcher: React.ReactNode; source: string }) {
  const [params] = useSearchParams()
  const [start] = useState(() => ({ tab: TABS[params.get('tab') ?? ''], node: params.get('node') ?? undefined, chapter: params.get('chapter') ?? undefined }))
  const [book, actions, setBook] = useLocalBook(initial)
  const sim = useWritingSim(book, setBook, initial)
  const chat = useChatSim(initial)
  const openRef = useRef<((type: string, id: string) => void) | null>(null)
  // 书架上的真书：点开一章才去读正文；快照的正文已经在书里
  const live = source.startsWith('live:') ? source.slice(5) : ''
  const loadChapter = useCallback(async (node: VNode) => {
    if (!live || !node.ref) return { text: '' }
    return { text: (await get<Chapter>(`/books/${live}/chapters/${node.ref.id}`)).content }
  }, [live])
  const writing = useMemo(() => (live ? { ...sim, loadChapter } : sim), [sim, live, loadChapter])
  const right = (
    <>
      <div className="mr-3">{switcher}</div>
      <SampleInbox book={book} />
      <button type="button" className="rounded-lg p-2 text-ink-3 transition-colors hover:bg-line/50 hover:text-ink" aria-label="本书设置" title="本书设置">
        <Settings className="size-4" />
      </button>
    </>
  )
  return (
    <>
      <Workspace book={book} actions={actions} right={right} chat={<EditorialChat chat={chat} />} writing={writing} openRef={openRef} start={start} />
      {initial.id === 'sample' && (
        <DemoMenu onPick={(kind) => {
          const go = sim.demo(kind)
          if (!go) return
          // 等书换好了再跳过去
          setTimeout(() => (go.startsWith('node:') ? openRef.current?.('node', go.slice(5)) : openRef.current?.('manuscript', go)), 60)
        }} />
      )}
    </>
  )
}

export function WorkspacePrototype() {
  const [params, setParams] = useSearchParams()
  const source = params.get('book') ?? 'sample'
  const { book, loading, error } = useBookSource(source)
  const choose = (next: string) => setParams(next === 'sample' ? {} : { book: next })
  // 换书的时候不带 tab、node 这些：只认刚打开时链接上的
  if (book) return <PrototypeDesk key={source} book={book} source={source} switcher={<BookSwitcher inline source={source} onSource={choose} />} />
  return (
    <>
      <div className="flex h-dvh items-center justify-center bg-paper text-[15px] text-ink-3">
        {loading ? '正在读这本书…' : `这本书没读出来：${error ?? ''}`}
      </div>
      <BookSwitcher source={source} onSource={choose} />
    </>
  )
}
