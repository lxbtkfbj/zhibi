import clsx from 'clsx'
import { ArrowRight, MessageCircleQuestion, PanelRightClose, PanelRightOpen, SendHorizontal } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useJobActions } from '../../api/hooks'
import { Button, ErrorText } from '../../components/ui'
import { ROLE_META } from '../../lib/roles'
import { TEAM, teamStatus } from '../../lib/team'
import { useBookContext } from './context'
import { ApproveButton, ResumeControls, RunningControls, WritingControls } from './Decision'
import { decisionCopy } from '../../lib/decision'
import { MeetingFeed, RoleAvatar } from './MeetingFeed'

const WIDTH_KEY = 'zhibi:team-width'
const DEFAULT_WIDTH = 480
const MIN_WIDTH = 360

function maxWidth() {
  return Math.max(MIN_WIDTH, Math.min(860, Math.round(window.innerWidth * 0.55)))
}

function readWidth() {
  try {
    const saved = Number(localStorage.getItem(WIDTH_KEY))
    return saved >= MIN_WIDTH ? saved : DEFAULT_WIDTH
  } catch {
    return DEFAULT_WIDTH
  }
}

function Roster({ compact }: { compact?: boolean }) {
  const { messages, working } = useBookContext()
  const status = teamStatus(messages, working)
  if (compact) {
    return (
      <div className="flex flex-col items-center gap-4">
        {TEAM.map((role) => (
          <div key={role} className="relative" title={`${ROLE_META[role].name}：${status[role].text}`}>
            <RoleAvatar speaker={role} working={status[role].state === 'working'} />
            {status[role].state === 'done' && <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-paper-2 bg-lore" />}
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-2 gap-2">
      {TEAM.map((role) => {
        const s = status[role]
        const meta = ROLE_META[role]
        return (
          <div
            key={role}
            className={clsx(
              'rounded-xl border bg-card px-3 py-2.5 transition-all duration-500',
              s.state === 'working' ? 'border-transparent shadow-[var(--shadow-lift)] ring-1 ring-line-2' : 'border-line shadow-[var(--shadow-paper)]',
            )}
          >
            <div className="flex items-center gap-2">
              <RoleAvatar speaker={role} size="sm" working={s.state === 'working'} />
              <span className="text-[13px] font-medium">{meta.name}</span>
            </div>
            <p
              className={clsx(
                'mt-1.5 line-clamp-1 text-xs',
                s.state === 'working' ? meta.text : s.state === 'done' ? 'text-ink-2' : 'text-ink-3',
              )}
              title={s.text}
            >
              {s.text}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function ActionCard({ onNavigate }: { onNavigate?: () => void }) {
  const { job, waiting, working, asking, bookId, book } = useBookContext()
  if (!job || (job.status === 'succeeded' && !waiting)) {
    if (book.status !== 'ready' && book.status !== 'writing') return null
    return (
      <div className="rounded-xl border border-line bg-card p-4 shadow-[var(--shadow-paper)]">
        <p className="mb-2.5 font-serif text-[15px] font-bold">{book.chapters_final ? `已写到第 ${book.chapters_final} 章` : '方案已定稿，可以开写了'}</p>
        <WritingControls compact />
      </div>
    )
  }
  const copy = decisionCopy(job.pending, bookId)
  const questions = job.pending?.kind === 'setup_questions' ? job.pending.questions.length : 0
  return (
    <AnimatePresence mode="wait">
      {asking && (
        <motion.div
          key="ask"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          className="relative overflow-hidden rounded-xl border border-chief/25 bg-card p-4 shadow-[var(--shadow-lift)]"
        >
          <span className="absolute inset-y-0 left-0 w-1 bg-chief" />
          <p className="flex items-center gap-1.5 font-serif text-[15px] font-bold text-chief">
            <MessageCircleQuestion className="size-4" />
            主编动笔前想先问你 {questions} 件事
          </p>
          <p className="mt-1 mb-3 text-xs leading-relaxed text-ink-3">点选答案就行，不想答的可以交给编辑部决定。回答完编辑部才开始写方案。</p>
          <Link to={`/books/${bookId}`} onClick={onNavigate}>
            <Button size="sm" variant="primary">
              去回答
              <ArrowRight className="size-3.5" />
            </Button>
          </Link>
        </motion.div>
      )}
      {waiting && (
        <motion.div
          key="wait"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          className="relative overflow-hidden rounded-xl border border-seal/30 bg-card p-4 shadow-[var(--shadow-lift)]"
        >
          <span className="absolute inset-y-0 left-0 w-1 bg-seal" />
          <p className="font-serif text-[15px] font-bold text-seal">
            {copy.title}
            {job.pending?.kind === 'setup_review' && job.pending.round > 0 ? `（第 ${job.pending.round + 1} 版）` : ''}
          </p>
          <p className="mt-1 mb-2 text-xs leading-relaxed text-ink-3">{copy.hint}</p>
          <div className="mb-3 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {copy.links.map(([label, to]) => (
              <Link key={to} to={to} onClick={onNavigate} className="text-ink-2 underline-offset-4 hover:text-ink hover:underline">
                {label} →
              </Link>
            ))}
          </div>
          <ApproveButton job={job} />
        </motion.div>
      )}
      {working && (
        <motion.div key="run" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="rounded-xl bg-chief-soft/60 px-3.5 py-2.5">
          <RunningControls job={job} />
        </motion.div>
      )}
      {(job.status === 'failed' || job.status === 'cancelled') && (
        <motion.div key="fail" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="rounded-xl border border-seal/30 bg-seal-soft/50 p-3.5">
          <ResumeControls job={job} />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/**
 * 会议室底部的输入框：编辑部工作时插话，方案出来后直接提修改意见。
 * 插话不会打断正在进行的那一步，做完这一步主编就会处理。
 */
function NoteComposer() {
  const { job, working, waiting, asking, bookId } = useBookContext()
  const { note, decide } = useJobActions(bookId)
  const [text, setText] = useState('')
  const [sent, setSent] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [text])

  useEffect(() => {
    if (!sent) return
    const timer = setTimeout(() => setSent(false), 6000)
    return () => clearTimeout(timer)
  }, [sent])

  if (!job || !(working || waiting || asking)) return null
  const pending = note.isPending || decide.isPending
  const error = note.error ?? decide.error

  const send = async () => {
    const content = text.trim()
    if (!content || pending) return
    if (waiting) await decide.mutateAsync({ jobId: job.id, action: 'revise', feedback: content })
    else await note.mutateAsync(content)
    setText('')
    setSent(!waiting)
  }

  const placeholder = waiting
    ? decisionCopy(job.pending, bookId).placeholder
    : asking
      ? '还有别的要求也可以先说，例如：主角叫云澈'
      : '插句话，例如：主角名字用云澈；金手指改巧妙一点；开局要直接打脸'

  return (
    <div className="shrink-0 border-t border-line bg-paper-2/90 px-4 pt-3 pb-4">
      <div className="flex items-end gap-2 rounded-2xl bg-card px-3 py-2 ring-1 ring-line transition-shadow focus-within:ring-line-2 focus-within:shadow-[var(--shadow-paper)]">
        <textarea
          ref={ref}
          value={text}
          rows={1}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // 输入法选词时的回车不发送
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void send()
            }
          }}
          placeholder={placeholder}
          aria-label={waiting ? '修改意见' : '插话'}
          className="scroll-thin max-h-40 min-h-[1.75rem] flex-1 resize-none bg-transparent py-1 text-[14px] leading-relaxed text-ink placeholder:text-ink-3/80 focus:outline-none"
        />
        <Button size="sm" variant={waiting ? 'primary' : 'seal'} onClick={send} loading={pending} disabled={!text.trim()} aria-label="发送">
          {waiting ? '提意见' : <SendHorizontal className="size-4" />}
        </Button>
      </div>
      <p className="mt-1.5 px-1 text-[11px] text-ink-3">
        {sent
          ? '已送达。编辑部做完手头这一步就处理，之后每一步都按你说的来。'
          : waiting
            ? 'Enter 发送，Shift + Enter 换行。发送后编辑部按你的意见处理。'
            : 'Enter 发送，Shift + Enter 换行。不会打断正在写的这一步。'}
      </p>
      <ErrorText error={error} />
    </div>
  )
}

/** 拖动面板左边缘调整宽度，双击恢复默认。窗口变窄时临时收窄，变宽后回到作者设定的宽度。 */
function useResizableWidth() {
  const [preferred, setPreferred] = useState(readWidth)
  const [limit, setLimit] = useState(maxWidth)
  const [dragging, setDragging] = useState(false)
  const width = Math.min(preferred, limit)

  useEffect(() => {
    const onResize = () => setLimit(maxWidth())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const save = useCallback((value: number) => {
    setPreferred(value)
    try {
      localStorage.setItem(WIDTH_KEY, String(value))
    } catch {
      /* 浏览器禁用存储时忽略 */
    }
  }, [])

  const onPointerDown = (e: ReactPointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = width
    let latest = startWidth
    setDragging(true)
    const move = (ev: PointerEvent) => {
      latest = Math.round(Math.min(maxWidth(), Math.max(MIN_WIDTH, startWidth + startX - ev.clientX)))
      setPreferred(latest)
    }
    const up = () => {
      setDragging(false)
      save(latest)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return { width, dragging, onPointerDown, reset: () => save(DEFAULT_WIDTH) }
}

/** 右侧编辑部面板：可拖动调宽，可收起为一条头像栏。 */
export function TeamPanel() {
  const { teamOpen, setTeamOpen, messages, working, connected, draft } = useBookContext()
  const { width, dragging, onPointerDown, reset } = useResizableWidth()

  return (
    <motion.aside
      animate={{ width: teamOpen ? width : 64 }}
      transition={dragging ? { duration: 0 } : { duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className={clsx('relative hidden h-full shrink-0 flex-col overflow-hidden border-l border-line bg-paper-2/80 lg:flex', dragging && 'select-none')}
    >
      {teamOpen ? (
        <div className="flex h-full flex-col" style={{ width }}>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="拖动调整编辑部宽度"
            title="拖动调整宽度，双击恢复默认"
            onPointerDown={onPointerDown}
            onDoubleClick={reset}
            className="group absolute inset-y-0 left-0 z-10 w-2 -translate-x-1/2 cursor-col-resize"
          >
            <span className={clsx('absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors', dragging ? 'bg-seal/60' : 'bg-transparent group-hover:bg-line-2')} />
          </div>
          <div className="flex items-center justify-between px-4 pt-4 pb-3">
            <div className="flex items-center gap-2">
              <h2 className="font-serif text-lg font-bold">编辑部</h2>
              <span className={clsx('flex items-center gap-1 text-xs', connected ? 'text-lore' : 'text-ink-3')}>
                <span className={clsx('size-1.5 rounded-full', connected ? 'bg-lore' : 'bg-ink-3')} />
                {connected ? (working ? '开会中' : '在线') : '连接中'}
              </span>
            </div>
            <button onClick={() => setTeamOpen(false)} className="rounded-lg p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" aria-label="收起编辑部">
              <PanelRightClose className="size-4" />
            </button>
          </div>
          <div className="space-y-3 px-4 pb-3">
            <Roster />
            <ActionCard />
          </div>
          <div className="flex items-center gap-2 px-4 pt-1 pb-2 text-[11px] tracking-[0.2em] text-ink-3">
            会议记录
            <span className="h-px flex-1 bg-line" />
          </div>
          <MeetingFeed messages={messages} working={working} draft={draft} className="min-h-0 flex-1 px-4 pb-6" />
          <NoteComposer />
        </div>
      ) : (
        <div className="flex h-full w-16 flex-col items-center gap-5 pt-4">
          <button onClick={() => setTeamOpen(true)} className="rounded-lg p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" aria-label="展开编辑部">
            <PanelRightOpen className="size-4" />
          </button>
          <Roster compact />
        </div>
      )}
    </motion.aside>
  )
}

/** 窄屏：编辑部以全屏面板显示。 */
export function TeamSheetBody({ onNavigate }: { onNavigate?: () => void }) {
  const { messages, working, draft } = useBookContext()
  return (
    <div className="-mx-6 -my-4 flex h-full flex-col">
      <div className="space-y-3 px-6 pt-4 pb-3">
        <Roster />
        <ActionCard onNavigate={onNavigate} />
      </div>
      <MeetingFeed messages={messages} working={working} draft={draft} className="min-h-0 flex-1 px-6 pb-6" />
      <NoteComposer />
    </div>
  )
}
