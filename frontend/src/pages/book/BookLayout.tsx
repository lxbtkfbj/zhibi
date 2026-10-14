import clsx from 'clsx'
import { ChevronLeft, Menu, Users, X } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useParams } from 'react-router-dom'
import { useBook } from '../../api/hooks'
import { Seal } from '../../components/decor'
import { EmptyState, Sheet, Skeleton } from '../../components/ui'
import { cleanTitle } from '../../lib/status'
import { computeStages } from '../../lib/team'
import { useMeeting } from '../../lib/useMeeting'
import { BookContext, type BookContextValue } from './context'
import { Sidebar } from './Sidebar'
import { Stepper } from './Stepper'
import { TeamPanel, TeamSheetBody } from './TeamPanel'

const TEAM_KEY = 'zhibi:team-open'

function readTeamPref() {
  try {
    return localStorage.getItem(TEAM_KEY) !== '0'
  } catch {
    return true
  }
}

/** 批准时的盖章动画。 */
function StampOverlay({ show }: { show: boolean }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center"
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
        >
          <motion.span
            className="absolute size-40 rounded-full border-4 border-seal/40"
            initial={{ scale: 0.4, opacity: 0.9 }}
            animate={{ scale: 2.4, opacity: 0 }}
            transition={{ duration: 0.9, delay: 0.25, ease: 'easeOut' }}
          />
          <motion.div
            className="flex items-center justify-center rounded-md border-[5px] border-seal bg-paper-2/80 px-8 py-4 font-serif text-5xl font-bold tracking-[0.4em] text-seal backdrop-blur-sm"
            initial={{ scale: 2.4, rotate: -24, opacity: 0 }}
            animate={{ scale: 1, rotate: -10, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 380, damping: 18 }}
          >
            已批准
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export function BookLayout() {
  const { bookId = '' } = useParams()
  const { data: book, isLoading, error } = useBook(bookId)
  const { messages, connected } = useMeeting(bookId)
  const [teamOpen, setTeamOpenState] = useState(readTeamPref)
  const [navOpen, setNavOpen] = useState(false)
  const [teamSheet, setTeamSheet] = useState(false)
  const [stamp, setStamp] = useState(false)
  const location = useLocation()
  const reduce = useReducedMotion()

  const setTeamOpen = useCallback((open: boolean) => {
    setTeamOpenState(open)
    try {
      localStorage.setItem(TEAM_KEY, open ? '1' : '0')
    } catch {
      /* 浏览器禁用存储时忽略 */
    }
  }, [])

  const job = book?.active_job ?? null
  const working = job?.status === 'running' || job?.status === 'queued'
  const asking = job?.status === 'waiting_author' && job.pending?.kind === 'setup_questions'
  const waiting = job?.status === 'waiting_author' && !asking

  // 编辑部开始工作、有问题要问或等你拍板时，自动展开编辑部面板
  const lastStatus = useRef(job?.status)
  useEffect(() => {
    if (job?.status && job.status !== lastStatus.current && (working || waiting || asking)) setTeamOpenState(true)
    lastStatus.current = job?.status
  }, [job?.status, working, waiting, asking])

  const celebrate = useCallback(() => {
    setStamp(true)
    setTimeout(() => setStamp(false), 1600)
  }, [])

  const stages = useMemo(() => (book ? computeStages(book.status, job, messages) : []), [book, job, messages])

  if (isLoading) {
    return (
      <div className="flex h-full">
        <div className="hidden w-64 space-y-3 border-r border-line p-5 lg:block">
          <Skeleton className="h-16" />
          <Skeleton className="h-6" />
          <Skeleton className="h-6" />
          <Skeleton className="h-6" />
        </div>
        <div className="flex-1 space-y-4 p-10">
          <Skeleton className="h-10 w-1/3" />
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      </div>
    )
  }
  if (error || !book) {
    return (
      <EmptyState title="找不到这本书">
        <Link to="/" className="text-seal underline">
          回到书房
        </Link>
      </EmptyState>
    )
  }

  const ctx: BookContextValue = { bookId, book, job, messages, connected, working, waiting, asking, teamOpen, setTeamOpen, celebrate }

  return (
    <BookContext.Provider value={ctx}>
      <div className="flex h-full flex-col">
        {/* 唯一的顶栏 */}
        <header className="z-20 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-paper-2/85 px-3 backdrop-blur-md sm:px-4">
          <button onClick={() => setNavOpen(true)} className="rounded-lg p-1.5 text-ink-2 hover:bg-line/60 lg:hidden" aria-label="目录">
            <Menu className="size-5" />
          </button>
          <Link to="/" className="group hidden items-center gap-2 text-sm text-ink-3 hover:text-ink lg:flex">
            <Seal size={26} />
            <ChevronLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
            书房
          </Link>
          <span className="hidden h-5 w-px bg-line-2 lg:block" />
          <h1 className="min-w-0 truncate font-serif text-[17px] font-bold">{cleanTitle(book.title)}</h1>
          <div className="ml-auto hidden md:block">
            <Stepper stages={stages} />
          </div>
          <button
            onClick={() => setTeamSheet(true)}
            className={clsx('relative ml-auto rounded-lg p-1.5 text-ink-2 hover:bg-line/60 md:ml-2 lg:hidden')}
            aria-label="编辑部"
          >
            <Users className="size-5" />
            {(working || waiting || asking) && <span className="absolute top-1 right-1 size-2 rounded-full bg-seal" />}
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          <aside className="hidden w-64 shrink-0 border-r border-line bg-paper-2/50 lg:block">
            <Sidebar />
          </aside>

          <main className="scroll-thin relative min-w-0 flex-1 overflow-y-auto">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={location.pathname}
                initial={reduce ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduce ? undefined : { opacity: 0, y: -6 }}
                transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                className="mx-auto w-full max-w-4xl px-5 py-8 sm:px-10 sm:py-10"
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </main>

          <TeamPanel />
        </div>

        {/* 窄屏目录 */}
        <AnimatePresence>
          {navOpen && (
            <motion.div className="fixed inset-0 z-50 bg-ink/20 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setNavOpen(false)}>
              <motion.aside
                initial={{ x: '-100%' }}
                animate={{ x: 0 }}
                exit={{ x: '-100%' }}
                transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                onClick={(e) => e.stopPropagation()}
                className="absolute inset-y-0 left-0 w-72 bg-paper-2 shadow-[var(--shadow-panel)]"
              >
                <button onClick={() => setNavOpen(false)} className="absolute top-4 right-3 rounded-lg p-1.5 text-ink-3" aria-label="关闭">
                  <X className="size-5" />
                </button>
                <Sidebar onNavigate={() => setNavOpen(false)} />
              </motion.aside>
            </motion.div>
          )}
        </AnimatePresence>
        <Sheet open={teamSheet} onClose={() => setTeamSheet(false)} title="编辑部">
          <TeamSheetBody onNavigate={() => setTeamSheet(false)} />
        </Sheet>
        <StampOverlay show={stamp} />
      </div>
    </BookContext.Provider>
  )
}
