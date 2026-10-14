import clsx from 'clsx'
import { ArrowLeft, Coins } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useBook, useUsage } from '../api/hooks'
import { Badge, EmptyState, Spinner } from '../components/ui'
import { BOOK_STATUS } from '../lib/roles'
import { useMeeting } from '../lib/useMeeting'
import { BiblePanel } from './book/BiblePanel'
import { JobPanel } from './book/JobPanel'
import { MeetingRoom } from './book/MeetingRoom'
import { OutlinePanel } from './book/OutlinePanel'

type Pane = 'meeting' | 'outline' | 'bible'

function formatTokens(n: number) {
  return n >= 10_000 ? `${(n / 10_000).toFixed(1)} 万` : String(n)
}

function UsageChip({ bookId }: { bookId: string }) {
  const { data } = useUsage(bookId)
  if (!data || data.calls === 0) return null
  return (
    <span
      className="hidden items-center gap-1 text-xs text-ink-3 md:flex"
      title={Object.entries(data.by_role)
        .map(([role, v]) => `${role}：${v.calls} 次，输入 ${v.prompt_tokens}，输出 ${v.completion_tokens}`)
        .join('\n')}
    >
      <Coins className="size-3.5" />
      {data.calls} 次调用
      {data.prompt_tokens + data.completion_tokens > 0 && ` · ${formatTokens(data.prompt_tokens + data.completion_tokens)} token`}
    </span>
  )
}

function ApprovedStamp() {
  return (
    <span className="stamp-in inline-flex -rotate-8 items-center rounded border-2 border-seal px-2 py-0.5 font-serif text-sm font-bold tracking-widest text-seal">
      已批准
    </span>
  )
}

export function BookPage() {
  const { bookId = '' } = useParams()
  const { data: book, isLoading, error } = useBook(bookId)
  const { messages, connected } = useMeeting(bookId)
  const [pane, setPane] = useState<Pane>('meeting')
  const [workspaceTab, setWorkspaceTab] = useState<'outline' | 'bible'>('outline')

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-ink-3">
        <Spinner />
      </div>
    )
  }
  if (error || !book) {
    return (
      <EmptyState title="找不到这本书">
        <Link to="/" className="text-seal underline">
          回到书架
        </Link>
      </EmptyState>
    )
  }

  const job = book.active_job
  const working = job?.status === 'running' || job?.status === 'queued'
  const status = BOOK_STATUS[book.status] ?? { label: book.status, tone: 'idle' as const }
  const visibleTab = pane === 'meeting' ? workspaceTab : pane

  const workspace = (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="hidden items-center gap-1 border-b border-line px-4 pt-2 lg:flex">
        {(['outline', 'bible'] as const).map((key) => (
          <button
            key={key}
            onClick={() => setWorkspaceTab(key)}
            className={clsx(
              '-mb-px border-b-2 px-3 py-2 text-sm',
              workspaceTab === key ? 'border-seal font-medium text-ink' : 'border-transparent text-ink-3 hover:text-ink',
            )}
          >
            {key === 'outline' ? '大纲' : '设定库'}
          </button>
        ))}
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto max-w-3xl">
          {visibleTab === 'outline' ? (
            <OutlinePanel bookId={bookId} locked={working} />
          ) : (
            <BiblePanel bookId={bookId} locked={working} />
          )}
        </div>
      </div>
    </div>
  )

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-line bg-paper-2 px-4 py-3 sm:px-6">
        <Link to="/" className="rounded-md p-1 text-ink-3 hover:bg-line/60 hover:text-ink" aria-label="回到书架">
          <ArrowLeft className="size-5" />
        </Link>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate font-serif text-xl font-bold">{book.title}</h1>
            {book.status === 'ready' ? (
              <ApprovedStamp />
            ) : (
              <Badge tone={status.tone}>
                {status.tone === 'busy' && <Spinner className="size-3" />}
                {status.label}
              </Badge>
            )}
          </div>
          <p className="truncate text-xs text-ink-3">{book.logline || book.idea}</p>
        </div>
        <UsageChip bookId={bookId} />
      </div>

      {/* 窄屏：三个面板切换 */}
      <div className="flex shrink-0 gap-1 border-b border-line bg-paper-2 px-3 py-1.5 lg:hidden">
        {(
          [
            ['meeting', '会议室'],
            ['outline', '大纲'],
            ['bible', '设定库'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setPane(key)}
            className={clsx(
              'flex-1 rounded-md py-1.5 text-sm',
              pane === key ? 'bg-card font-medium shadow-sm ring-1 ring-line' : 'text-ink-2',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1">
        <section
          className={clsx(
            'min-h-0 w-full flex-col border-line bg-paper-2/50 lg:flex lg:w-[440px] lg:shrink-0 lg:border-r',
            pane === 'meeting' ? 'flex' : 'hidden',
          )}
        >
          <MeetingRoom messages={messages} connected={connected} working={working} />
          <JobPanel bookId={bookId} job={job} />
        </section>
        <section className={clsx('min-h-0 flex-1 flex-col', pane === 'meeting' ? 'hidden lg:flex' : 'flex')}>{workspace}</section>
      </div>
    </div>
  )
}
