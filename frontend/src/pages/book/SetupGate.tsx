import { useJobActions } from '../../api/hooks'
import { Button, ErrorText } from '../../components/ui'
import { useBookContext } from './context'
import { PieceDecisions } from './PieceDecisions'

export function SetupGate({ piece }: { piece: 'concept' | 'settings' | 'outline' }) {
  const { bookId, book, job, requestFeedback, resumeFollow } = useBookContext()
  const actions = useJobActions(bookId)
  // 大纲确认后待办会先消失，再轮询开书并启动写作；这段时间失败也必须保留错误。
  if (job?.status !== 'waiting_author' || job.pending?.kind !== 'setup_piece' || job.pending.piece !== piece || job.setup_flow !== 3) return actions.confirmSetupAndWrite.error ? <footer className="mt-8 border-t border-line pt-6"><ErrorText error={actions.confirmSetupAndWrite.error} /><p className="mt-2 text-sm text-ink-2">自动开写未完成。请先处理上面的错误，再从开写入口继续。</p></footer> : null
  const confirm = async () => {
    if (actions.setupPending) return
    try {
      resumeFollow()
      if (piece === 'outline') await actions.confirmSetupAndWrite.mutateAsync({ jobId: job.id, book, action: 'confirm' })
      else await actions.pieceAction.mutateAsync({ jobId: job.id, piece, action: 'confirm' })
    } catch { /* 保留等待和错误。 */ }
  }
  return <footer className="mt-8 border-t border-line pt-6"><PieceDecisions piece={piece} /><div className="flex flex-wrap gap-3"><Button variant="seal" disabled={actions.setupPending} loading={actions.setupPending} onClick={() => void confirm()}>{piece === 'concept' ? '确认，去建设定' : piece === 'settings' ? '设定先这样，去出大纲' : '确认，开写'}</Button><Button variant="ghost" disabled={actions.setupPending} onClick={requestFeedback}>提意见</Button></div><ErrorText error={actions.pieceAction.error ?? actions.confirmSetupAndWrite.error} /></footer>
}
