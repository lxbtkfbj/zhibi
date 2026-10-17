import { useJobActions } from '../../api/hooks'
import { composerRoute } from '../../lib/workspace'
import { useBookContext } from './context'

export function useGroupFeedback() {
  const { job, bookId, segmentReview, composerNode } = useBookContext()
  const actions = useJobActions(bookId)
  return async (content: string) => {
    if (!job) throw new Error('待拍板内容已变化，请刷新后再提意见')
    const route = composerRoute(job, content, composerNode, false)
    if (route.kind === 'pitches') await actions.pitches.mutateAsync({ jobId: job.id, action: 'redo', feedback: content })
    else if (route.kind === 'directions') await actions.directions.mutateAsync({ jobId: job.id, action: 'redo', feedback: content })
    else if (route.kind === 'piece') await actions.piece.mutateAsync({ jobId: job.id, action: 'revise', piece: route.piece, feedback: content, ...('node_id' in route ? { node_id: route.node_id } : {}) })
    else if (route.kind === 'segment') { if (!await segmentReview.submit({ action: 'revise', feedback: content })) throw new Error('这一篇正在提交，请稍后再试') }
    else if (route.kind === 'decision') await actions.decide.mutateAsync({ jobId: job.id, action: 'revise', feedback: content })
    else throw new Error('这个旧任务要先按新写法重开或重出，再提修改意见')
  }
}
