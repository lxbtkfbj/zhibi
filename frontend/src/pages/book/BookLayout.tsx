import type { ChatQuote } from '../../lib/chat'
import { useReducedMotion } from '../../lib/appearance'
import { useIsMutating } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronLeft, Settings, SlidersHorizontal } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from 'react'
import { Link, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useBook, useChapters, useJobActions, useNodes, useOutline } from '../../api/hooks'
import type { BookDetail, Conversation } from '../../api/types'
import { Seal } from '../../components/decor'
import { EmptyState, Skeleton } from '../../components/ui'
import { cleanTitle } from '../../lib/status'
import { useMeeting } from '../../lib/useMeeting'
import { MIN_CHAT, useConversationReads, useWorkspaceResize } from '../../lib/useWorkspacePanels'
import { currentTarget, nodeFeedback, progressText, type NodeFeedback } from '../../lib/workspace'
import { ActionBar } from './ActionBar'
import { BookContext, type BookContextValue, type PitchChoice } from './context'
import { ConversationPanel } from './ConversationPanel'
import { ManuscriptTabs } from './ManuscriptTabs'
import { SetupArtifactPreview } from './SetupArtifactPreview'
import { useSettingsModal } from '../../lib/settingsModal'
import { segmentReviewKey } from '../../lib/outlineWriting'
import { followOnBookOpen } from '../../lib/bookRoutes'

function StampOverlay({ show }: { show: boolean }) {
  const reduce = useReducedMotion()
  return <AnimatePresence>{show && <motion.div data-testid="approval-stamp" aria-live="polite" className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center" initial={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : 0.5 }}>
    {!reduce && <motion.span className="absolute size-40 rounded-full border-4 border-seal/40" initial={{ scale: 0.4, opacity: 0.9 }} animate={{ scale: 2.4, opacity: 0 }} transition={{ duration: 0.9, delay: 0.25, ease: 'easeOut' }} />}
    <motion.div className="rounded-md border-[5px] border-seal bg-paper-2/95 px-8 py-4 font-serif text-5xl font-bold tracking-[0.4em] text-seal" initial={reduce ? false : { scale: 2.4, rotate: -24, opacity: 0 }} animate={{ scale: 1, rotate: -10, opacity: 1 }} transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 380, damping: 18 }}>已批准</motion.div>
  </motion.div>}</AnimatePresence>
}

/** 顶栏的状态胶囊：拍板的具体内容只在书稿底部的操作条里说，这里只报「在干什么 / 等你」。 */
function StatusPill({ book, progress, waiting, working }: { book: BookDetail; progress: string; waiting: boolean; working: boolean }) {
  const failed = book.active_job?.status === 'failed'
  const rest = waiting ? progress.replace(/\s*(·\s*)?等你(拍板|确认|回答|选择)：.*$/, '') : progress
  const tone = waiting || failed ? 'wait' : working ? 'busy' : 'idle'
  // 顶上只放前两段（第几篇、第几卷几章），整句放在鼠标提示里。
  const short = rest.split(' · ').slice(0, 2).join(' · ')
  return <p title={progress} data-testid="workspace-status" className={clsx('ml-auto hidden min-w-0 items-center gap-2 truncate rounded-full py-1 pr-3 pl-2.5 text-xs md:flex',
    tone === 'wait' ? 'bg-seal-soft text-seal-dark' : tone === 'busy' ? 'bg-chief-soft text-chief' : 'text-ink-2')}>
    <span aria-hidden className={clsx('size-1.5 shrink-0 rounded-full', tone === 'wait' ? 'bg-seal' : tone === 'busy' ? 'bg-chief motion-safe:animate-pulse' : 'bg-ink-3/60')} />
    <span className="truncate">{waiting ? short ? `${short} · 等你处理` : '等你处理' : short}</span>
  </p>
}

function BookWorkspace({ bookId, book }: { bookId: string; book: BookDetail }) {
  const { openSettings } = useSettingsModal()
  const { messages, connected, draft, typing: chatTyping } = useMeeting(bookId)
  const { data: outline } = useOutline(bookId)
  const { data: nodes = [] } = useNodes(bookId)
  const { data: chapters = [] } = useChapters(bookId)
  const [conversation, setConversationState] = useState<Conversation>('group')
  const [following, setFollowing] = useState(() => followOnBookOpen(window.location.pathname, bookId))
  const [focusComposer, setFocusComposer] = useState(0)
  const [composerNode, setComposerNode] = useState<NodeFeedback | null>(null)
  const [chatQuotes, setChatQuotes] = useState<Record<string, ChatQuote | null>>({})
  const [composerDrafts, setComposerDrafts] = useState<Record<string, string>>({})
  const [pitchChoice, setPitchChoice] = useState<PitchChoice | null>(null)
  const [tab, setTab] = useState<'discussion' | 'manuscript'>(() => followOnBookOpen(window.location.pathname, bookId) ? 'discussion' : 'manuscript')
  const [wide, setWide] = useState(() => window.innerWidth >= 1024)
  const [stamp, setStamp] = useState(false)
  const [segmentPin, setSegmentPin] = useState({ key: '', selected: false })
  const segmentLock = useRef(false)
  const { segment, segmentPending } = useJobActions(bookId)
  const stampTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { container, width, max, dragging, separatorProps, step, reset } = useWorkspaceResize()
  const navigate = useNavigate()
  const location = useLocation()
  const automaticPath = useRef<string | null>(null)
  const previousPath = useRef(location.pathname + location.search)
  const manuscriptScroll = useRef<HTMLDivElement>(null)
  const job = book.active_job
  const expanding = useIsMutating({ mutationKey: ['outline-expand', bookId] }) > 0
  const working = expanding || job?.status === 'queued' || job?.status === 'running'
  const asking = job?.status === 'waiting_author' && job.pending?.kind === 'setup_questions'
  const waiting = job?.status === 'waiting_author' && !asking
  const segmentKey = segmentReviewKey(job?.id, job?.status === 'waiting_author' ? job.pending : null)
  const segmentPinEnd = !!segmentKey && segmentPin.key === segmentKey && segmentPin.selected
  const setSegmentPinEnd = (selected: boolean) => setSegmentPin({ key: segmentKey, selected })
  const segmentReview: BookContextValue['segmentReview'] = {
    submitting: segmentPending,
    action: segment.variables?.action,
    error: segment.error,
    submit: async body => {
      if (!job || !segmentKey || segmentPending || segmentLock.current) return false
      segmentLock.current = true
      try {
        await segment.mutateAsync({ jobId: job.id, ...body, ...(['confirm', 'delegate'].includes(body.action) ? { pin_end: segmentPinEnd } : {}) })
        setSegmentPin({ key: '', selected: false })
        return true
      } finally { segmentLock.current = false }
    },
  }
  const followTarget = useMemo(() => currentTarget(bookId, job, messages, draft, outline), [bookId, job, messages, draft, outline])
  const unread = useConversationReads(bookId, messages, conversation, wide || tab === 'discussion')
  const setConversation = useCallback((next: Conversation) => { setConversationState(next); setTab('discussion') }, [])
  const askChief = (quote: ChatQuote) => { setChatQuotes(previous => ({ ...previous, chief: quote })); setConversation('chief'); setFocusComposer(n => n + 1) }
  const manualNavigate = useCallback((path: string) => { setFollowing(false); setTab('manuscript'); void navigate(path) }, [navigate])
  const resumeFollow = useCallback(() => { setFollowing(true); setTab('manuscript') }, [])
  const requestFeedback = useCallback(() => { setConversation('group'); setFocusComposer(n => n + 1) }, [setConversation])
  const requestNodeFeedback: BookContextValue['requestNodeFeedback'] = useCallback(node => {
    const selection = nodeFeedback(node)
    setComposerNode(selection)
    setComposerDrafts(previous => ({ ...previous, group: `${selection.prefix}${(previous.group ?? '').replace(/^关于节点 \d+「[^」]*」：/, '')}` }))
    setConversation('group')
    setFocusComposer(n => n + 1)
  }, [setConversation])
  const celebrate = useCallback(() => {
    if (stampTimer.current) clearTimeout(stampTimer.current)
    setStamp(true)
    stampTimer.current = setTimeout(() => setStamp(false), 1600)
  }, [])
  useEffect(() => () => { if (stampTimer.current) clearTimeout(stampTimer.current) }, [])
  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)')
    const change = () => setWide(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  useEffect(() => {
    if (previousPath.current !== location.pathname + location.search) {
      if (automaticPath.current !== location.pathname + location.search) setFollowing(false)
      previousPath.current = location.pathname + location.search
      automaticPath.current = null
      manuscriptScroll.current?.scrollTo({ top: 0 })
    }
  }, [location.pathname, location.search])
  const targetPath = followTarget?.path
  useEffect(() => {
    if (!following || !targetPath) return
    automaticPath.current = targetPath
    void navigate(targetPath, { replace: true })
  }, [following, targetPath, navigate])
  const captureManualLink = (event: MouseEvent<HTMLDivElement>) => {
    const href = (event.target as Element).closest('a[href]')?.getAttribute('href')
    if ((href?.startsWith(`/books/${bookId}`) || href?.startsWith('#')) && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) { setFollowing(false); setTab('manuscript') }
  }
  const ctx: BookContextValue = { bookId, book, job, messages, connected, chatTyping, chatQuotes, setChatQuotes, askChief, draft, working, waiting, asking, outline, conversation, setConversation, unread, following, followTarget, manualNavigate, resumeFollow, focusComposer, focusChat: () => setFocusComposer(n => n + 1), requestFeedback, requestNodeFeedback, composerNode, setComposerNode, composerDrafts, setComposerDrafts, celebrate, pitchChoice, setPitchChoice, segmentPinEnd, setSegmentPinEnd, segmentReview }
  const progress = expanding ? '展开大纲 · 主编正在展开这一个' : progressText(book, messages, draft, followTarget, { nodes, volumes: outline?.volumes ?? [], chapters })
  const unreadTotal = Object.values(unread).reduce((sum, value) => sum + value, 0)
  return <BookContext.Provider value={ctx}>
    <div className="flex h-full min-h-0 flex-col" onClickCapture={captureManualLink}>
      <header className="z-20 flex h-[52px] shrink-0 items-center gap-3.5 border-b border-divider bg-paper-2 px-[18px]">
        <Link to="/" title="返回书房" className="flex shrink-0 items-center gap-2 rounded-md py-1 pr-1 text-sm text-ink-2 hover:text-ink"><Seal size={28} /><span className="flex items-center"><ChevronLeft className="size-4" />书房</span></Link>
        <span className="h-[18px] w-px shrink-0 bg-line-2" />
        <h1 className="min-w-0 max-w-[32%] truncate font-serif text-lg font-bold" title={cleanTitle(book.title)}>{cleanTitle(book.title)}</h1>
        <div role="tablist" aria-label="工作台视图" className="flex shrink-0 gap-0.5 rounded-lg bg-line/70 p-0.5 lg:hidden">{(['discussion', 'manuscript'] as const).map(value => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={clsx('relative rounded-md px-3 py-1 text-[13px]', tab === value ? 'bg-card font-medium text-ink' : 'text-ink-2')}>{value === 'discussion' ? '讨论' : '稿件'}{value === 'discussion' && tab !== 'discussion' && unreadTotal > 0 && <span aria-label="有未读" className="absolute top-1 right-1 size-1.5 rounded-full bg-seal" />}{value === 'manuscript' && tab !== 'manuscript' && (waiting || asking) && <span aria-label="等你处理" className="absolute top-1 right-1 size-1.5 rounded-full bg-seal" />}</button>)}</div>
        <StatusPill book={book} progress={progress} waiting={waiting || asking} working={working} />
        <Link to={`/books/${bookId}/settings`} className={clsx('flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13px] text-ink-2 hover:bg-line/60 hover:text-ink', 'max-md:ml-auto')}><SlidersHorizontal className="size-4" /><span className="hidden sm:inline">本书设置</span></Link>
        <button type="button" onClick={openSettings} aria-label="全局设置" title="全局设置：模型、外观、新书默认" className="flex shrink-0 items-center rounded-lg p-1.5 text-ink-2 hover:bg-line/60 hover:text-ink"><Settings className="size-4" /></button>
      </header>
      <div ref={container} className={clsx('flex min-h-0 min-w-0 flex-1', dragging && 'select-none')} style={{ '--discussion-width': `${width}px` } as CSSProperties}>
        <section aria-label="当前会话" data-testid="conversation-pane" className={clsx('@container/chat h-full min-h-0 min-w-0 w-full shrink-0 flex-col bg-pane-mid lg:flex lg:w-[var(--discussion-width)]', tab === 'discussion' ? 'flex' : 'hidden')}><ConversationPanel /></section>
        {/* 分隔线：鼠标靠近就显出把手；拖到最宽就停，再宽一行字太长不好读。 */}
        <div role="separator" aria-orientation="vertical" aria-label="调整讨论栏宽度" aria-valuemin={MIN_CHAT} aria-valuemax={max} aria-valuenow={width} tabIndex={0} title="拖动调整聊天栏宽度，双击恢复默认；方向键微调" {...separatorProps}
          onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); step(event.key === 'ArrowLeft' ? -24 : 24) } else if (event.key === 'Home') { event.preventDefault(); reset() } }}
          className={clsx('group relative z-30 hidden w-px shrink-0 touch-none cursor-col-resize bg-divider outline-none lg:block',
            'before:absolute before:inset-y-0 before:-left-1.5 before:w-3 before:content-[""]',
            'after:pointer-events-none after:absolute after:inset-y-0 after:-left-px after:w-[3px] after:rounded-full after:transition-colors after:content-[""] hover:after:bg-ink-3/40 focus-visible:after:bg-seal',
            dragging && 'after:!bg-seal')}>
          <span aria-hidden className={clsx('pointer-events-none absolute top-1/2 left-1/2 flex h-11 w-2 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center gap-[3px] rounded-full bg-card shadow-[var(--shadow-paper)] ring-1 ring-line-2 transition-opacity', dragging ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100')}>
            <span className="size-[3px] rounded-full bg-ink-3" /><span className="size-[3px] rounded-full bg-ink-3" /><span className="size-[3px] rounded-full bg-ink-3" />
          </span>
        </div>
        <main id="manuscript-pane" aria-label="稿件" className={clsx('@container/manuscript relative min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-page lg:flex', tab === 'manuscript' ? 'flex' : 'hidden')}>
          <ManuscriptTabs />
          <div ref={manuscriptScroll} data-testid="manuscript-scroll" className="scroll-thin min-h-0 flex-1 overflow-y-auto"><div className="mx-auto w-full max-w-[1800px] px-5 pt-7 pb-12 @2xl/manuscript:px-9"><SetupArtifactPreview><Outlet /></SetupArtifactPreview></div></div>
          <ActionBar />
        </main>
      </div>
      <StampOverlay show={stamp} />
    </div>
  </BookContext.Provider>
}

export function BookLayout() {
  const { bookId = '' } = useParams()
  const { data: book, isLoading, error } = useBook(bookId)
  if (isLoading) return <div className="flex h-full gap-8 p-8"><Skeleton className="w-80" /><div className="flex-1 space-y-5"><Skeleton className="h-12" /><Skeleton className="h-80" /></div></div>
  if (error || !book) return <EmptyState title="找不到这本书"><Link to="/" className="text-seal underline">回到书房</Link></EmptyState>
  return <BookWorkspace key={bookId} bookId={bookId} book={book} />
}
