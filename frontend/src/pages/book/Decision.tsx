import clsx from 'clsx'
import { Check, CirclePause, PenLine, RotateCcw, Stamp } from 'lucide-react'
import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useJobActions } from '../../api/hooks'
import type { InterviewQuestion, Job, WriteUntil } from '../../api/types'
import { Button, ErrorText, inputClass, TypingDots } from '../../components/ui'
import { decisionCopy } from '../../lib/decision'
import { useReducedMotion } from '../../lib/appearance'
import { PIECES, targetPiece } from '../../lib/storyMap'
import { pendingTarget } from '../../lib/workspace'
import { useBookContext } from './context'

export function DecisionBar() {
  const { bookId, job, waiting, requestFeedback, manualNavigate, celebrate } = useBookContext()
  const { pieceAction } = useJobActions(bookId)
  const reduce = useReducedMotion()
  const pending = job?.pending
  const target = pendingTarget(pending, bookId)
  const piece = pending?.kind === 'setup_piece' ? pending : null
  const name = PIECES.find(item => item.key === piece?.piece)?.name ?? ''
  const reminders = (piece?.warnings?.length ?? 0) + (piece?.suggestions?.length ?? 0) + (piece?.unlock_requests?.length ?? 0)
  const act = async (action: 'confirm' | 'delegate') => {
    if (!job || !piece) return
    try {
      await pieceAction.mutateAsync({ jobId: job.id, action, piece: piece.piece })
      if (piece.piece === 'first_volume') celebrate()
    } catch { /* 失败保留待确认内容。 */ }
  }
  return <AnimatePresence initial={false}>{waiting && job && target && <motion.div key="decision" data-testid="decision-bar" initial={reduce ? false : { opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: reduce ? 0 : 0.28, ease: 'easeOut' }} className="z-10 max-h-[42vh] shrink-0 overflow-y-auto border-b border-seal/25 bg-paper-2 px-5 py-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm font-medium text-seal">{piece ? `待你确认：${name}${piece.warnings?.[0] ? `（${piece.warnings[0]}）` : ''}` : pending?.kind === 'setup_directions' ? '待你选择：开书方向' : `待你拍板：${target.label}`}</p>
      <div className="flex flex-wrap items-center gap-2">{piece ? <>
        <Button size="sm" variant="seal" loading={pieceAction.isPending && pieceAction.variables?.action === 'confirm'} disabled={pieceAction.isPending} onClick={() => void act('confirm')}>确认这一块</Button>
        <Button size="sm" variant="ghost" loading={pieceAction.isPending && pieceAction.variables?.action === 'delegate'} disabled={pieceAction.isPending} onClick={() => void act('delegate')}>交给编辑部定</Button>
      </> : pending?.kind === 'setup_directions' ? <button className="text-sm text-chief underline underline-offset-4" onClick={() => manualNavigate(`/books/${bookId}`)}>去选择 →</button> : <><ApproveButton job={job} /><Button size="sm" variant="ghost" onClick={requestFeedback}>提意见</Button></>}</div>
    </div>
    {!!reminders && piece && <details className="mt-3 border-t border-divider pt-2">
      <summary className="cursor-pointer text-xs text-ink-2">提醒与审稿建议（{reminders}）</summary>
      <ul className="mt-3 space-y-3 text-sm leading-relaxed text-ink-2">
        {piece.warnings?.map((warning, index) => <li key={`warning-${index}`}><span className="mr-2 text-xs text-seal">提醒</span>{warning}</li>)}
        {piece.suggestions?.map((suggestion, index) => <li key={`suggestion-${index}`}><span className="mr-2 text-xs text-chief">审稿建议</span>{suggestion.problem}<p className="mt-1">{suggestion.suggestion}</p><Button size="sm" variant="ghost" className="mt-1" disabled={pieceAction.isPending} loading={pieceAction.isPending && pieceAction.variables?.feedback === `${suggestion.problem}\n${suggestion.suggestion}`} onClick={() => pieceAction.mutate({ jobId: job.id, action: 'unlock', piece: targetPiece[suggestion.target], feedback: `${suggestion.problem}\n${suggestion.suggestion}` })}>解锁并修改</Button></li>)}
        {piece.unlock_requests?.map((request, index) => <li key={`unlock-${index}`}><span className="mr-2 text-xs text-chief">解锁请求</span>{request.reason}<div><Button size="sm" variant="ghost" className="mt-1" disabled={pieceAction.isPending} loading={pieceAction.isPending && pieceAction.variables?.feedback === request.reason} onClick={() => pieceAction.mutate({ jobId: job.id, action: 'unlock', piece: targetPiece[request.target], feedback: request.reason })}>解锁并修改</Button></div></li>)}
      </ul>
    </details>}
    <ErrorText error={pieceAction.error} />
  </motion.div>}</AnimatePresence>
}

/** 只有盖章按钮：编辑部面板里修改意见直接在底部输入框里说。 */
export function ApproveButton({ job }: { job: Job }) {
  const { bookId, celebrate } = useBookContext()
  const { decide } = useJobActions(bookId)
  const copy = decisionCopy(job.pending, bookId)
  const approve = async () => {
    try {
      await decide.mutateAsync({ jobId: job.id, action: 'approve' })
      celebrate()
    } catch { /* ErrorText retains the failure; never stamp an unsuccessful approval. */ }
  }
  return (
    <div>
      <Button variant="seal" onClick={approve} loading={decide.isPending && decide.variables?.action === 'approve'}>
        <Stamp className="size-4" />
        {copy.approve}
      </Button>
      <ErrorText error={decide.error} />
    </div>
  )
}

const WRITE_OPTIONS: { key: string; label: string; until: WriteUntil; count: number; hint: string }[] = [
  { key: '1', label: '写 1 章', until: 'count', count: 1, hint: '先写一章看看' },
  { key: '3', label: '写 3 章', until: 'count', count: 3, hint: '新书写完前 3 章会请你试读' },
  { key: '10', label: '写 10 章', until: 'count', count: 10, hint: '中途可以随时插话或停下' },
  { key: 'volume', label: '写完这一卷', until: 'volume', count: 1, hint: '一卷写完就停，等你看看' },
  { key: 'book', label: '一直写到完本', until: 'book', count: 1, hint: '每卷开写前仍会请你拍板卷纲' },
]

/** 开写：选这一轮写多少，编辑部按卷纲和章纲逐章写，写够就停。 */
export function WritingControls({ compact }: { compact?: boolean }) {
  const { bookId, book } = useBookContext()
  const { write } = useJobActions(bookId)
  const [choice, setChoice] = useState(book.chapters_final === 0 && !book.trial_read_done ? '3' : '10')
  const option = WRITE_OPTIONS.find((o) => o.key === choice) ?? WRITE_OPTIONS[1]
  return (
    <div>
      <div className={clsx('flex flex-wrap gap-1.5', compact ? 'mb-2.5' : 'mb-3')}>
        {WRITE_OPTIONS.map((o) => (
          <button
            key={o.key}
            onClick={() => setChoice(o.key)}
            aria-pressed={choice === o.key}
            className={clsx(
              'rounded-xl px-3 py-1.5 ring-1 transition-colors',
              compact ? 'text-[13px]' : 'text-[14px]',
              choice === o.key ? 'bg-ink text-paper-2 ring-ink' : 'bg-card text-ink-2 ring-line-2 hover:text-ink hover:ring-ink-3/50',
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="seal" size={compact ? 'sm' : 'lg'} onClick={() => write.mutate({ until: option.until, count: option.count })} loading={write.isPending}>
          <PenLine className="size-4" />
          {book.chapters_final ? '继续写' : '开写'}
        </Button>
        <span className="text-xs text-ink-2">{option.hint}</span>
      </div>
      <ErrorText error={write.error} />
    </div>
  )
}

/** 动笔前的提问：默认选中主编推荐的答案，作者改想改的就行；再点一次取消，表示交给编辑部决定。 */
export function InterviewForm({ job, questions }: { job: Job; questions: InterviewQuestion[] }) {
  const { bookId } = useBookContext()
  const { answer } = useJobActions(bookId)
  const [picked, setPicked] = useState<Record<number, string>>(() =>
    Object.fromEntries(questions.map((q, i) => [i, q.options[q.recommended] ?? ''])),
  )
  const [custom, setCustom] = useState<Record<number, boolean>>({})
  const [extra, setExtra] = useState('')

  const submit = (skipAll = false) =>
    answer.mutateAsync({
      jobId: job.id,
      answers: skipAll ? [] : questions.map((_, i) => ({ index: i, answer: (picked[i] ?? '').trim() })),
      extra: skipAll ? '' : extra.trim(),
    })

  const choose = (i: number, option: string) => {
    setCustom((c) => ({ ...c, [i]: false }))
    setPicked((p) => ({ ...p, [i]: p[i] === option ? '' : option }))
  }

  return (
    <div className="space-y-5">
      <ol className="space-y-5">
        {questions.map((q, i) => (
          <li key={i}>
            <p className="mb-2 flex gap-2 text-[15px] font-medium">
              <span className="font-serif text-seal">{i + 1}.</span>
              {q.question}
            </p>
            <div className="flex flex-wrap gap-2 pl-5">
              {q.options.map((option, j) => {
                const active = !custom[i] && picked[i] === option
                return (
                  <button
                    key={option}
                    onClick={() => choose(i, option)}
                    aria-pressed={active}
                    className={clsx(
                      'flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-left text-[14px] ring-1 transition-colors',
                      active ? 'bg-ink text-paper-2 ring-ink' : 'bg-card text-ink-2 ring-line-2 hover:text-ink hover:ring-ink-3/50',
                    )}
                  >
                    {active && <Check className="size-3.5 shrink-0" />}
                    {option}
                    {j === q.recommended && <span className={clsx('text-xs', active ? 'text-paper-2/70' : 'text-seal')}>推荐</span>}
                  </button>
                )
              })}
              <button
                onClick={() => {
                  setCustom((c) => ({ ...c, [i]: true }))
                  setPicked((p) => ({ ...p, [i]: '' }))
                }}
                aria-pressed={!!custom[i]}
                className={clsx(
                  'flex items-center gap-1 rounded-xl border border-dashed px-3 py-[5px] text-[14px] transition-colors',
                  custom[i] ? 'border-chief/40 bg-chief-soft text-chief' : 'border-line-2 text-ink-2 hover:border-ink-3/50 hover:text-ink',
                )}
              >
                <PenLine className="size-3.5" />
                我自己说
              </button>
            </div>
            {custom[i] && (
              <input
                autoFocus
                value={picked[i] ?? ''}
                onChange={(e) => setPicked((p) => ({ ...p, [i]: e.target.value }))}
                placeholder="写下你的想法"
                maxLength={500}
                className={clsx(inputClass, 'mt-2 ml-5 w-[calc(100%-1.25rem)] py-2')}
              />
            )}
            {!custom[i] && !picked[i] && <p className="mt-1.5 pl-5 text-xs text-ink-2">交给编辑部决定</p>}
          </li>
        ))}
      </ol>
      <div>
        <p className="mb-1.5 text-sm font-medium text-ink-2">还有别的要求？<span className="ml-1 font-normal text-ink-2">可选</span></p>
        <textarea
          value={extra}
          onChange={(e) => setExtra(e.target.value)}
          rows={2}
          maxLength={5000}
          placeholder="例如：主角叫云澈；开局直接退婚打脸；不要后宫"
          className={inputClass}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="seal" size="lg" onClick={() => submit()} loading={answer.isPending}>
          就这样，开始写方案
        </Button>
        <button onClick={() => submit(true)} disabled={answer.isPending} className="text-sm text-ink-2 underline-offset-4 hover:text-ink hover:underline">
          都交给编辑部决定
        </button>
      </div>
      <ErrorText error={answer.error} />
    </div>
  )
}

export function RunningControls({ job }: { job: Job }) {
  const { bookId } = useBookContext()
  const { cancel } = useJobActions(bookId)
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-sm text-chief">
        <TypingDots />
        {job.status === 'queued' ? '排队中，马上开始' : '编辑部正在工作'}
      </span>
      <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job.id)} loading={cancel.isPending}>
        <CirclePause className="size-4" />
        停止
      </Button>
    </div>
  )
}

export function ResumeControls({ job }: { job: Job }) {
  const { bookId } = useBookContext()
  const { resume } = useJobActions(bookId)
  return (
    <div className="space-y-2">
      <p className="text-sm leading-relaxed text-seal">{job.status === 'failed' ? `这一轮出错了：${job.error}` : '任务已停止。'}</p>
      <p className="text-xs text-ink-2">已经完成的步骤都保存着，继续时从中断的地方接着做，不会重来。</p>
      <Button size="sm" variant="primary" onClick={() => resume.mutate(job.id)} loading={resume.isPending}>
        <RotateCcw className="size-4" />
        继续
      </Button>
      <ErrorText error={resume.error} />
    </div>
  )
}
