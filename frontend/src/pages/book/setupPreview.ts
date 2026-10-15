import type { Job, MeetingMessage, Outline } from '../../api/types'
import { artifactTarget } from '../../lib/workspace.ts'

const SETUP_PREVIEWS = new Set(['directions', 'concept', 'lore', 'spine', 'threads', 'outline', 'volume_plan'])

/** Setup persists only at its final checkpoint. Never put provisional output in the editable query cache. */
export function setupPreviewForPath(
  bookId: string,
  job: Job | null,
  messages: MeetingMessage[],
  pathname: string,
  outline?: Outline,
): MeetingMessage | null {
  if (job?.kind !== 'book_setup' || (job.status !== 'queued' && job.status !== 'running')) return null
  const path = pathname.replace(/\/+$/, '')
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i]
    if (message.book_id !== bookId || message.job_id !== job.id || message.kind !== 'artifact') continue
    if (!SETUP_PREVIEWS.has(message.payload?.type ?? '') || !message.payload?.data) continue
    if (artifactTarget(message, bookId, outline)?.path.replace(/\/+$/, '') === path) return message
  }
  return null
}
