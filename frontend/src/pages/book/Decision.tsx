import { CirclePause, MessageSquareText, RotateCcw, Stamp } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { Job } from '../../api/types'
import { Button, ErrorText, inputClass, TypingDots } from '../../components/ui'
import { useBookContext } from './context'

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
