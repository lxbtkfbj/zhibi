import type { BookDetail, Conversation, Job, LiveDraft, MeetingMessage, Outline, Pending } from '../api/types'

export interface WorkspaceTarget { path: string; label: string }

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}
function positive(value: unknown): number | null {
  const n = Number(value)
  return Number.isInteger(n) && n > 0 ? n : null
}

/** One resolver for both automatic following and manually opened artifact cards. */
export function artifactTarget(message: MeetingMessage, bookId: string, outline?: Outline): WorkspaceTarget | null {
  const base = `/books/${bookId}`
  const type = message.payload?.type
  const data = record(message.payload?.data)
  const page = (suffix: string, label: string) => ({ path: `${base}${suffix}`, label })
  switch (type) {
    case 'concept': return page('/concept', '书的概念')
    case 'lore': return page('/characters', '人物设定')
    case 'spine': return page('/spine', '主线骨架')
    case 'threads': return page('/threads', '线索')
    case 'outline': return page('', '全书总纲')
    case 'questions': return page('', '动笔前提问')
    case 'critique': return page('', '开书方案')
    case 'volume_plan': case 'volume_directions': case 'volume_pitch': case 'pitch_scores': case 'volume_audit': case 'volume_recap': {
      const n = positive(data.volume ?? data.index)
      return n ? page(`/volume/${n}`, `第 ${n} 卷卷纲`) : null
    }
    case 'chapter_plan': case 'unit_recap': {
      // Existing messages identify the unit as 第N卷第M单元「标题」, not a database id.
      const named = String(data.unit ?? '')
      const n = positive(data.volume) ?? positive(named.match(/第\s*(\d+)\s*卷/)?.[1])
        ?? outline?.volumes.find(v => v.units.some(u => u.id === data.unit_id || u.id === data.unit || u.title === named))?.index
      return n ? page(`/volume/${n}`, `第 ${n} 卷卷纲`) : null
    }
    case 'chapter_final': case 'chapter_draft': case 'chapter_polish': case 'chapter_materials': case 'chapter_review': case 'chapter_consistency': {
      const n = positive(data.index ?? data.chapter)
      return n ? page(`/chapter/${n}`, `第 ${n} 章`) : null
    }
    default: return null
  }
}

export function pendingTarget(pending: Pending | null | undefined, bookId: string): WorkspaceTarget | null {
  const base = `/books/${bookId}`
  switch (pending?.kind) {
    case 'setup_questions': return { path: base, label: '动笔前提问' }
    case 'setup_review': return { path: base, label: '开书方案' }
    case 'volume_review': return { path: `${base}/volume/${pending.volume}`, label: `第 ${pending.volume} 卷卷纲` }
    case 'trial_read': return { path: `${base}/chapter/1`, label: `前 ${pending.chapters} 章试读` }
    case 'chapter_stuck': return { path: `${base}/chapter/${pending.chapter}`, label: `第 ${pending.chapter} 章` }
    default: return null
  }
}

const SETUP_OUTPUTS = new Set(['concept', 'lore', 'spine', 'threads', 'outline', 'volume_plan'])
const WRITE_OUTPUTS = new Set(['volume_plan', 'volume_directions', 'volume_pitch', 'pitch_scores', 'volume_audit', 'chapter_plan', 'chapter_final'])

export function currentTarget(bookId: string, job: Job | null, messages: MeetingMessage[], draft: LiveDraft | null, outline?: Outline): WorkspaceTarget | null {
  if (!job) return null
  if (job.status === 'waiting_author') return pendingTarget(job.pending, bookId)
  if (job.status !== 'queued' && job.status !== 'running') return null
  const current = messages.filter(m => m.job_id === job.id)
  if (draft && !draft.done && draft.job_id === job.id) return { path: `/books/${bookId}/chapter/${draft.chapter}`, label: `第 ${draft.chapter} 章` }
  if (job.kind === 'rewrite_chapter') {
    // The author's persisted rewrite request exists before the worker starts emitting a draft.
    const request = current.find(m => m.speaker === 'author' && /按我的意见重写/.test(m.content) && (m.kind === 'speech' || m.kind === 'decision'))
    const n = positive(request?.content.match(/第\s*(\d+)\s*章/)?.[1])
      ?? positive([...current].reverse().find(m => /第\s*\d+\s*章/.test(m.content))?.content.match(/第\s*(\d+)\s*章/)?.[1])
    return n ? { path: `/books/${bookId}/chapter/${n}`, label: `第 ${n} 章` } : null
  }
  const allowed = job.kind === 'book_setup' ? SETUP_OUTPUTS : WRITE_OUTPUTS
  for (const message of [...current].reverse()) {
    if (message.kind !== 'artifact' || !allowed.has(message.payload?.type ?? '')) continue
    const target = artifactTarget(message, bookId, outline)
    if (target) return target
  }
  return job.kind === 'book_setup' ? { path: `/books/${bookId}`, label: '开书方案' } : null
}

export function conversationContains(message: MeetingMessage, conversation: Conversation) {
  // Read markers belong to the actual thread, not optionally displayed group speech.
  if (conversation === 'group') return !message.payload?.thread
  return message.payload?.thread === conversation
}

export function unreadCount(messages: MeetingMessage[], conversation: Conversation, lastRead: number) {
  return messages.filter(m => m.id > lastRead && m.speaker !== 'author' && conversationContains(m, conversation)).length
}

export function progressText(book: BookDetail, messages: MeetingMessage[], draft: LiveDraft | null, target: WorkspaceTarget | null) {
  const job = book.active_job
  if (job?.status === 'waiting_author') return `${job.pending?.kind === 'setup_questions' ? '等你回答' : '等你拍板'}：${target?.label ?? '编辑部的提问'}`
  const working = job?.status === 'queued' || job?.status === 'running'
  const lastStatus = [...messages].reverse().find(m => m.job_id === job?.id && m.kind === 'status')
  if (working && job.kind === 'book_setup') return `开书中 · ${lastStatus?.content.replace(/[.…]+$/, '') ?? '主编在准备方案'}`
  const volume = target?.path.match(/\/volume\/(\d+)$/)?.[1]
  const progress = `${volume ? `第 ${volume} 卷 · ` : ''}已定稿 ${book.chapters_final} 章`
  if (working) return `${progress} · ${draft && !draft.done && draft.job_id === job.id ? `写手在写第 ${draft.chapter} 章` : lastStatus?.content.replace(/[.…]+$/, '') ?? '编辑部工作中'}`
  if (job?.status === 'failed') return `${progress} · 任务出错，可继续`
  return `${progress} · ${book.status === 'completed' ? '全书完结' : '编辑部空闲'}`
}
