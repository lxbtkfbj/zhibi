import clsx from 'clsx'
import { BookOpenText, ChevronLeft, Settings2, X } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from 'react'
import { Link, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useBook, useOutline } from '../../api/hooks'
import type { BookDetail, Conversation } from '../../api/types'
import { Seal } from '../../components/decor'
import { Button, EmptyState, Skeleton } from '../../components/ui'
import { cleanTitle } from '../../lib/status'
import { useMeeting } from '../../lib/useMeeting'
import { useConversationReads, useWorkspaceResize } from '../../lib/useWorkspacePanels'
import { currentTarget, pendingTarget, progressText } from '../../lib/workspace'
import { BookContext, type BookContextValue } from './context'
import { ConversationPanel } from './ConversationPanel'
import { ApproveButton } from './Decision'
import { ConversationList, Sidebar } from './Sidebar'
import { SetupArtifactPreview } from './SetupArtifactPreview'

function StampOverlay({ show }: { show: boolean }) {
  const reduce = useReducedMotion()
  return <AnimatePresence>{show && <motion.div data-testid="approval-stamp" aria-live="polite" className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center" initial={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : 0.5 }}>
    {!reduce && <motion.span className="absolute size-40 rounded-full border-4 border-seal/40" initial={{ scale: 0.4, opacity: 0.9 }} animate={{ scale: 2.4, opacity: 0 }} transition={{ duration: 0.9, delay: 0.25, ease: 'easeOut' }} />}
    <motion.div className="rounded-md border-[5px] border-seal bg-paper-2/95 px-8 py-4 font-serif text-5xl font-bold tracking-[0.4em] text-seal" initial={reduce ? false : { scale: 2.4, rotate: -24, opacity: 0 }} animate={{ scale: 1, rotate: -10, opacity: 1 }} transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 380, damping: 18 }}>已批准</motion.div>
  </motion.div>}</AnimatePresence>
}

function BookWorkspace({ bookId, book }: { bookId: string; book: BookDetail }) {
  const { messages, connected, draft } = useMeeting(bookId)
  const { data: outline } = useOutline(bookId)
  const [conversation, setConversationState] = useState<Conversation>('group')
  const [following, setFollowing] = useState(true)
  const [focusComposer, setFocusComposer] = useState(0)
  const [tab, setTab] = useState<'discussion' | 'manuscript'>('discussion')
  const [wide, setWide] = useState(() => window.innerWidth >= 1024)
  const [navOpen, setNavOpen] = useState(false)
  const [stamp, setStamp] = useState(false)
  const stampTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { container, width, max, dragging, separatorProps, step, reset } = useWorkspaceResize()
  const navigate = useNavigate()
  const location = useLocation()
  const reduce = useReducedMotion()
  const automaticPath = useRef<string | null>(null)
  const previousPath = useRef(location.pathname)
  const manuscriptScroll = useRef<HTMLDivElement>(null)
  const job = book.active_job
  const working = job?.status === 'queued' || job?.status === 'running'
  const asking = job?.status === 'waiting_author' && job.pending?.kind === 'setup_questions'
  const waiting = job?.status === 'waiting_author' && !asking
  const followTarget = useMemo(() => currentTarget(bookId, job, messages, draft, outline), [bookId, job, messages, draft, outline])
  const todo = job?.status === 'waiting_author' ? pendingTarget(job.pending, bookId) : null
  const unread = useConversationReads(bookId, messages, conversation, wide || tab === 'discussion')
  const setConversation = useCallback((next: Conversation) => { setConversationState(next); setTab('discussion') }, [])
  const manualNavigate = useCallback((path: string) => { setFollowing(false); setTab('manuscript'); void navigate(path) }, [navigate])
  const requestFeedback = useCallback(() => { setConversation('group'); setFocusComposer(n => n + 1) }, [setConversation])
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
    if (!navOpen) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setNavOpen(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [navOpen])
  useEffect(() => {
    if (previousPath.current !== location.pathname) {
      if (automaticPath.current !== location.pathname) setFollowing(false)
      previousPath.current = location.pathname
      automaticPath.current = null
      manuscriptScroll.current?.scrollTo({ top: 0 })
    }
  }, [location.pathname])
  const targetPath = followTarget?.path
  useEffect(() => {
    if (!following || !targetPath) return
    automaticPath.current = targetPath
    void navigate(targetPath, { replace: true })
  }, [following, targetPath, navigate])
  const captureManualLink = (event: MouseEvent<HTMLDivElement>) => {
    const href = (event.target as Element).closest('a[href]')?.getAttribute('href')
    if (href?.startsWith(`/books/${bookId}`) && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) { setFollowing(false); setTab('manuscript') }
  }
  const ctx: BookContextValue = { bookId, book, job, messages, connected, draft, working, waiting, asking, outline, conversation, setConversation, unread, following, followTarget, manualNavigate, focusComposer, requestFeedback, celebrate }
  const progress = progressText(book, messages, draft, followTarget)
  return <BookContext.Provider value={ctx}>
    <div className="flex h-full min-h-0 flex-col" onClickCapture={captureManualLink}>
      <header className="z-20 flex h-16 shrink-0 items-center gap-3 border-b border-divider bg-[#f8f3e9] px-4">
        <Link to="/" className="flex shrink-0 items-center gap-1.5 text-sm text-ink-2 hover:text-ink"><Seal size={28} /><ChevronLeft className="size-4" />返回书房</Link>
        <span className="h-5 w-px shrink-0 bg-line" /><h1 className="max-w-[24%] truncate font-serif text-lg font-bold" title={cleanTitle(book.title)}>{cleanTitle(book.title)}</h1>
        <div role="tablist" aria-label="工作台视图" className="flex shrink-0 gap-1 rounded-lg bg-line/50 p-1 lg:hidden">{(['discussion', 'manuscript'] as const).map(value => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={clsx('rounded-md px-3 py-1 text-sm', tab === value ? 'bg-card text-ink shadow-sm' : 'text-ink-2')}>{value === 'discussion' ? '讨论' : '稿件'}</button>)}</div>
        <p className="ml-auto min-w-0 truncate text-xs text-ink-2" title={progress}>{progress}</p>
        <Link to="/settings" className="flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-2 text-sm text-ink-2 hover:bg-line/50"><Settings2 className="size-4" />模型设置</Link>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside data-testid="full-sidebar" className="hidden w-[248px] shrink-0 border-r border-divider bg-[#ece4d4] xl:block"><Sidebar /></aside>
        <aside data-testid="sidebar-rail" className="flex w-16 shrink-0 flex-col border-r border-divider bg-[#ece4d4] pt-5 xl:hidden"><ConversationList compact onSelect={() => setNavOpen(true)} /><button onClick={() => setNavOpen(true)} className="mx-2 mt-5 flex h-12 items-center justify-center rounded-lg border-t border-divider text-ink-2 hover:bg-card/60" aria-label="展开书稿目录"><BookOpenText className="size-5" /></button></aside>
        <div ref={container} className={clsx('flex min-w-0 flex-1', dragging && 'select-none')} style={{ '--discussion-width': `${width}px` } as CSSProperties}>
          <section aria-label="当前会话" data-testid="conversation-pane" className={clsx('h-full min-h-0 min-w-0 w-full shrink-0 flex-col bg-[#f6f1e6] lg:flex lg:w-[var(--discussion-width)]', tab === 'discussion' ? 'flex' : 'hidden')}><ConversationPanel /></section>
          <div role="separator" aria-orientation="vertical" aria-label="调整讨论栏宽度" aria-valuemin={360} aria-valuemax={max} aria-valuenow={width} tabIndex={0} title="拖动调整宽度，双击恢复默认；方向键微调" {...separatorProps}
            onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); step(event.key === 'ArrowLeft' ? -24 : 24) } else if (event.key === 'Home') { event.preventDefault(); reset() } }} className={clsx('relative z-30 hidden w-px shrink-0 touch-none cursor-col-resize bg-divider outline-none before:absolute before:inset-y-0 before:-left-1 before:w-[9px] hover:bg-seal focus:bg-seal lg:block', dragging && 'bg-seal')} />
          <main id="manuscript-pane" aria-label="稿件" className={clsx('@container/manuscript relative min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-[#fffdf8] lg:flex', tab === 'manuscript' ? 'flex' : 'hidden')}>
            {!following && followTarget && <button data-testid="resume-follow" onClick={() => { setFollowing(true); setTab('manuscript') }} className="shrink-0 border-b border-divider bg-[#f8f3e9] px-5 py-3 text-left text-sm text-chief hover:bg-line/40">回到正在进行的：{followTarget.label} →</button>}
            <AnimatePresence initial={false}>{waiting && job && todo && <motion.div key="decision" data-testid="decision-bar" initial={reduce ? false : { opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: reduce ? 0 : 0.28, ease: 'easeOut' }} className="z-10 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-seal/25 bg-[#f8f3e9] px-5 py-3"><p className="text-sm font-medium text-seal">待你拍板：{todo.label}</p><div className="flex items-center gap-2"><ApproveButton job={job} /><Button size="sm" variant="ghost" onClick={requestFeedback}>提意见</Button></div></motion.div>}</AnimatePresence>
            <div ref={manuscriptScroll} data-testid="manuscript-scroll" className="scroll-thin min-h-0 flex-1 overflow-y-auto"><div className="mx-auto w-full max-w-5xl px-5 py-8 @2xl/manuscript:px-9"><SetupArtifactPreview><Outlet /></SetupArtifactPreview></div></div>
          </main>
        </div>
      </div>
      <AnimatePresence>{navOpen && <motion.div className="fixed inset-0 z-50 bg-ink/20 xl:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setNavOpen(false)}><motion.aside role="dialog" aria-label="编辑部与书稿目录" aria-modal="true" initial={reduce ? false : { x: '-100%' }} animate={{ x: 0 }} exit={{ x: '-100%' }} transition={{ duration: reduce ? 0 : 0.28, ease: 'easeOut' }} onClick={event => event.stopPropagation()} className="absolute inset-y-0 left-0 w-[248px] bg-[#ece4d4] shadow-[var(--shadow-panel)]"><button autoFocus onClick={() => setNavOpen(false)} className="absolute top-3 right-3 z-10 rounded-lg p-2 text-ink-2 hover:bg-card" aria-label="关闭目录"><X className="size-4" /></button><Sidebar onNavigate={() => setNavOpen(false)} /></motion.aside></motion.div>}</AnimatePresence>
      <StampOverlay show={stamp} />
    </div>
  </BookContext.Provider>
}

export function BookLayout() {
  const { bookId = '' } = useParams()
  const { data: book, isLoading, error } = useBook(bookId)
  if (isLoading) return <div className="flex h-full gap-8 p-8"><Skeleton className="w-52" /><div className="flex-1 space-y-5"><Skeleton className="h-12" /><Skeleton className="h-80" /></div></div>
  if (error || !book) return <EmptyState title="找不到这本书"><Link to="/" className="text-seal underline">回到书房</Link></EmptyState>
  return <BookWorkspace key={bookId} bookId={bookId} book={book} />
}
