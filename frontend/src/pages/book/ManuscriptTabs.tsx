import clsx from 'clsx'
import { ArrowRight, Check } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useLibrarySuggestions } from '../../api/library'
import type { PieceStatus } from '../../api/types'
import { pendingTarget } from '../../lib/workspace'
import { useBookContext } from './context'
import { usePuzzleProgress } from './usePuzzleProgress'

type TabKey = 'overview' | 'concept' | 'library' | 'outline' | 'text'

const TABS: { key: TabKey; label: string; path: string; match: (path: string) => boolean }[] = [
  { key: 'overview', label: '概览', path: '', match: path => path === '' || path === '/' },
  { key: 'concept', label: '定调', path: '/concept', match: path => path.startsWith('/concept') },
  { key: 'library', label: '设定库', path: '/library', match: path => ['/library', '/relations', '/secrets', '/foreshadowing'].some(prefix => path.startsWith(prefix)) },
  { key: 'outline', label: '大纲', path: '/outline', match: path => path.startsWith('/outline') },
  { key: 'text', label: '正文', path: '/chapters', match: path => path.startsWith('/chapter') },
]

/** 开书各块落在哪个标签上；第二包旧书的五块也归到这三处。 */
const STEP_PIECES: Partial<Record<TabKey, string[]>> = {
  concept: ['concept'],
  library: ['settings', 'protagonist', 'world'],
  outline: ['outline', 'segment', 'first_volume'],
}

function tabStatus(statuses: PieceStatus[]): PieceStatus | null {
  if (!statuses.length) return null
  if (statuses.includes('waiting')) return 'waiting'
  if (statuses.includes('drafting')) return 'drafting'
  if (statuses.every(status => status === 'confirmed' || status === 'done')) return 'confirmed'
  return 'todo'
}

/** 书稿栏顶上的一排标签：导航本身，开书期间兼作三步进度。 */
export function ManuscriptTabs() {
  const { bookId, book, job, draft, working, following, followTarget, manualNavigate, resumeFollow } = useBookContext()
  const { pathname } = useLocation()
  const progress = usePuzzleProgress()
  const suggestions = useLibrarySuggestions(bookId)
  const base = `/books/${bookId}`
  const current = pathname.startsWith(base) ? pathname.slice(base.length) : pathname
  const pendingPath = job?.status === 'waiting_author' ? pendingTarget(job.pending, bookId)?.path.split('?')[0].slice(base.length) : undefined
  const live = working && !!draft && !draft.done && draft.job_id === job?.id
  return <nav aria-label="书稿" data-testid="manuscript-tabs" className="flex h-11 shrink-0 items-stretch gap-1 border-b border-divider bg-page pr-3 pl-3 @2xl/manuscript:pl-5">
    <div className="no-scrollbar flex min-w-0 flex-1 items-stretch gap-1 overflow-x-auto">
      {TABS.map(tab => {
        const active = tab.match(current)
        const step = progress.show ? tabStatus(progress.pieces.filter(piece => STEP_PIECES[tab.key]?.includes(piece.key)).map(piece => piece.status)) : null
        const pendingHere = pendingPath !== undefined && tab.match(pendingPath)
        const count = tab.key === 'library' ? suggestions.data?.length : undefined
        return <a key={tab.key} href={`${base}${tab.path}`} aria-current={active ? 'page' : undefined}
          onClick={event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return; event.preventDefault(); manualNavigate(`${base}${tab.path}`) }}
          title={step === 'waiting' || pendingHere ? '等你处理' : step === 'drafting' ? '编辑部正在写' : step === 'confirmed' ? '已确认' : undefined}
          className={clsx('relative flex shrink-0 items-center gap-1.5 px-2.5 text-[13px] transition-colors',
            active ? 'font-medium text-ink after:absolute after:inset-x-2.5 after:bottom-0 after:h-0.5 after:rounded-full after:bg-ink' : step === 'todo' ? 'text-ink-3 hover:text-ink-2' : 'text-ink-2 hover:text-ink')}>
          {tab.label}
          {step === 'confirmed' && <Check aria-label="已确认" className="size-3.5 text-lore" />}
          {(step === 'waiting' || (pendingHere && step !== 'confirmed')) && <span aria-label="等你处理" className="size-1.5 rounded-full bg-seal" />}
          {step === 'drafting' && <span aria-label="正在写" className="size-1.5 rounded-full bg-chief motion-safe:animate-pulse" />}
          {tab.key === 'text' && live && <span aria-label="正在写" className="size-1.5 rounded-full bg-writer motion-safe:animate-pulse" />}
          {!!count && <span className="rounded-full bg-line px-1.5 text-[11px] leading-4 text-ink-2 tabular-nums">{count}</span>}
          {tab.key === 'text' && !!book.chapters_final && <span className="text-[11px] text-ink-3 tabular-nums">{book.chapters_final}</span>}
        </a>
      })}
    </div>
    {followTarget && (following || followTarget.path.split('?')[0] !== pathname) && (following
      ? <span className="hidden shrink-0 items-center gap-1.5 self-center text-xs text-ink-3 @xl/manuscript:flex" title="右边会跟着编辑部正在做的切换；自己点开别的页面就停下"><span className="size-1.5 rounded-full bg-chief" />跟随编辑部</span>
      : <button type="button" data-testid="resume-follow" onClick={resumeFollow} title={`回到正在进行的：${followTarget.label}`} className="flex min-w-0 shrink items-center gap-1 self-center rounded-md px-2 py-1 text-xs text-chief hover:bg-chief-soft">
        <span className="truncate">回到正在进行的<span className="hidden @2xl/manuscript:inline">：{followTarget.label}</span></span><ArrowRight className="size-3.5 shrink-0" />
      </button>)}
  </nav>
}
