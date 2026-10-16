import type { Job, MeetingMessage, Outline } from '../../api/types'
import { artifactTarget } from '../../lib/workspace.ts'

const SETUP_PREVIEWS = new Set(['directions', 'concept', 'protagonist', 'world', 'segment', 'segment_volumes', 'lore', 'spine', 'threads', 'outline', 'volume_plan'])

/** 每块入库前展示本轮产出；只读快照绝不能写进可编辑的 query cache。 */
export function setupPreviewForPath(
  bookId: string,
  job: Job | null,
  messages: MeetingMessage[],
  pathname: string,
  outline?: Outline,
): MeetingMessage | null {
  if (job?.kind !== 'book_setup' || (job.status !== 'queued' && job.status !== 'running')) return null
  const path = pathname.replace(/\/+$/, '')
  // 同一个开书任务会逐块确认和多次改稿。作者最新决定之前的产出已经是旧稿，
  // 不应在新一轮排队时盖住正式稿或方向选择的加载提示；普通插话 note 不划断产出。
  const decision = messages.findLast(message => message.book_id === bookId && message.job_id === job.id && message.speaker === 'author' && message.kind === 'decision')
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i]
    if (message.book_id !== bookId || message.job_id !== job.id || message.kind !== 'artifact') continue
    if (decision && message.id <= decision.id) continue
    if (!SETUP_PREVIEWS.has(message.payload?.type ?? '') || !message.payload?.data) continue
    if (artifactTarget(message, bookId, outline)?.path.replace(/\/+$/, '') === path) return message
  }
  return null
}
