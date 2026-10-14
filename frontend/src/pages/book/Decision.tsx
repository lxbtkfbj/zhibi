import clsx from 'clsx'
import { Check, CirclePause, MessageSquareText, PenLine, RotateCcw, Stamp } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { InterviewQuestion, Job } from '../../api/types'
import { Button, ErrorText, inputClass, TypingDots } from '../../components/ui'
import { useBookContext } from './context'

/** 只有盖章按钮：编辑部面板里修改意见直接在底部输入框里说。 */
export function ApproveButton({ job }: { job: Job }) {
  const { bookId, celebrate } = useBookContext()
  const { decide } = useJobActions(bookId)
  const approve = async () => {
    await decide.mutateAsync({ jobId: job.id, action: 'approve' })
    celebrate()
  }
  return (
    <div>
      <Button variant="seal" onClick={approve} loading={decide.isPending && decide.variables?.action === 'approve'}>
        <Stamp className="size-4" />
        盖章批准
      </Button>
      <ErrorText error={decide.error} />
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
                    {j === q.recommended && <span className={clsx('text-[11px]', active ? 'text-paper-2/70' : 'text-seal')}>推荐</span>}
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
                  custom[i] ? 'border-chief/40 bg-chief-soft text-chief' : 'border-line-2 text-ink-3 hover:border-ink-3/50 hover:text-ink',
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
            {!custom[i] && !picked[i] && <p className="mt-1.5 pl-5 text-xs text-ink-3">交给编辑部决定</p>}
          </li>
        ))}
      </ol>
      <div>
        <p className="mb-1.5 text-sm font-medium text-ink-2">还有别的要求？<span className="ml-1 font-normal text-ink-3">可选</span></p>
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
        <button onClick={() => submit(true)} disabled={answer.isPending} className="text-sm text-ink-3 underline-offset-4 hover:text-ink hover:underline">
          都交给编辑部决定
        </button>
      </div>
      <ErrorText error={answer.error} />
    </div>
  )
}

/** 拍板：盖章批准或提修改意见。 */
export function DecisionControls({ job, compact }: { job: Job; compact?: boolean }) {
  const { bookId, celebrate } = useBookContext()
  const { decide } = useJobActions(bookId)
  const [feedback, setFeedback] = useState('')
  const [writing, setWriting] = useState(false)

  const approve = async () => {
    await decide.mutateAsync({ jobId: job.id, action: 'approve' })
    celebrate()
  }
  const submit = async () => {
    await decide.mutateAsync({ jobId: job.id, action: 'revise', feedback: feedback.trim() })
    setFeedback('')
    setWriting(false)
  }

  return (
    <div>
      <AnimatePresence mode="wait" initial={false}>
        {writing ? (
          <motion.div
            key="write"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
            className="space-y-2"
          >
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={compact ? 3 : 4}
              autoFocus
              placeholder="例如：女主出场太晚了，第一单元就让她登场；反派的动机再狠一点。"
              className={inputClass}
              onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && feedback.trim() && void submit()}
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setWriting(false)}>
                取消
              </Button>
              <Button size="sm" variant="primary" onClick={submit} loading={decide.isPending} disabled={!feedback.trim()}>
                交给主编
              </Button>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="buttons"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
            className="flex flex-wrap gap-2"
          >
            <Button variant="seal" size={compact ? 'md' : 'lg'} onClick={approve} loading={decide.isPending}>
              <Stamp className="size-4" />
              盖章批准
            </Button>
            <Button variant="outline" size={compact ? 'md' : 'lg'} onClick={() => setWriting(true)}>
              <MessageSquareText className="size-4" />
              提修改意见
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
      <ErrorText error={decide.error} />
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
      <p className="text-xs text-ink-3">已经完成的步骤都保存着，继续时从中断的地方接着做，不会重来。</p>
      <Button size="sm" variant="primary" onClick={() => resume.mutate(job.id)} loading={resume.isPending}>
        <RotateCcw className="size-4" />
        继续
      </Button>
      <ErrorText error={resume.error} />
    </div>
  )
}
