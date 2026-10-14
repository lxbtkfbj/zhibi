import { CirclePause, MessageSquareText, RotateCcw, Stamp } from 'lucide-react'
import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { Job } from '../../api/types'
import { Button, ErrorText, inputClass, TypingDots } from '../../components/ui'

/** 会议室底部的任务控制：工作中可停止，出错可继续，等待拍板时盖章批准或提意见。 */
export function JobPanel({ bookId, job }: { bookId: string; job: Job | null }) {
  const { decide, resume, cancel } = useJobActions(bookId)
  const [feedback, setFeedback] = useState('')
  const [writing, setWriting] = useState(false)

  if (!job || job.status === 'succeeded') return null

  if (job.status === 'queued' || job.status === 'running') {
    return (
      <div className="flex items-center justify-between gap-3 border-t border-line bg-chief-soft/60 px-4 py-3 text-sm text-chief">
        <span className="flex items-center gap-2">
          <TypingDots />
          {job.status === 'queued' ? '排队中，马上开始…' : '编辑部正在工作，方案暂时不能修改'}
        </span>
        <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job.id)} loading={cancel.isPending}>
          <CirclePause className="size-4" />
          停止
        </Button>
      </div>
    )
  }

  if (job.status === 'failed' || job.status === 'cancelled') {
    return (
      <div className="space-y-2 border-t border-line bg-seal-soft/50 px-4 py-3 text-sm">
        <p className="text-seal">{job.status === 'failed' ? `这一轮出错了：${job.error}` : '任务已停止。'}</p>
        <p className="text-xs text-ink-3">已经完成的步骤都保存着，继续时会从中断的地方接着做，不会重来。</p>
        <Button size="sm" variant="primary" onClick={() => resume.mutate(job.id)} loading={resume.isPending}>
          <RotateCcw className="size-4" />
          继续
        </Button>
        <ErrorText error={resume.error} />
      </div>
    )
  }

  // waiting_author
  const round = job.pending?.round ?? 0
  const submitFeedback = async () => {
    await decide.mutateAsync({ jobId: job.id, action: 'revise', feedback: feedback.trim() })
    setFeedback('')
    setWriting(false)
  }

  return (
    <div className="space-y-3 border-t-2 border-seal/40 bg-card px-4 py-4">
      <div>
        <p className="font-serif font-semibold text-seal">
          开书方案已就绪{round > 0 ? `（第 ${round + 1} 版）` : ''}，等你拍板
        </p>
        <p className="mt-1 text-xs leading-relaxed text-ink-3">
          看看右边的大纲和设定库，不满意的地方可以直接点文字修改。满意就盖章批准；想让编辑部改，就写下意见。
        </p>
      </div>
      {writing ? (
        <div className="space-y-2">
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            autoFocus
            placeholder="例如：女主出场太晚了，第一单元就让她登场；反派的动机再狠一点。"
            className={inputClass}
            onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && feedback.trim() && void submitFeedback()}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setWriting(false)}>
              取消
            </Button>
            <Button size="sm" variant="primary" onClick={submitFeedback} loading={decide.isPending} disabled={!feedback.trim()}>
              交给主编
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="seal"
            onClick={() => decide.mutate({ jobId: job.id, action: 'approve' })}
            loading={decide.isPending && decide.variables?.action === 'approve'}
          >
            <Stamp className="size-4" />
            盖章批准
          </Button>
          <Button variant="outline" onClick={() => setWriting(true)}>
            <MessageSquareText className="size-4" />
            提修改意见
          </Button>
        </div>
      )}
      <ErrorText error={decide.error} />
    </div>
  )
}
