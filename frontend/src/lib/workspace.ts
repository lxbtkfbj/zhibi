import type { BookDetail, ChapterBrief, Conversation, Job, LiveDraft, MeetingMessage, Outline, Pending, StoryNode, Volume } from '../api/types'
import { isWritingComplete, setupPieces, plannedVolumeChapters, segmentFinishedText, writingPosition, writingSegmentNumber } from './storyMap.ts'

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
    case 'concept': return page('/concept', '定调')
    case 'pitches': return page('/concept', '三个短版');
    case 'settings_focus': case 'settings_rest': return page('/library?view=focus', '设定库');
    case 'directions': return page('', '开书方向')
    case 'protagonist': return page('/library?view=focus', '设定库 · 重点')
    case 'world': return page('/library?cat=世界与地图', '设定库')
    case 'segment': return page('/outline?node=first-arc', '第一篇')
    case 'segment_plan': return page('/next-segment', '下一篇')
    case 'segment_volumes': return page(Array.isArray(data.volumes) && (positive(record(data.volumes[0]).index) ?? 1) > 1 ? '/next-segment' : '/outline?node=first-arc', '这一篇的分卷')
    case 'lore': return page('/library?cat=角色卡片', '人物设定')
    case 'spine': return page('/outline?view=map', '大纲')
    case 'threads': return page('/outline?view=threads', '线索')
    case 'outline': return page('/outline?node=first-arc', '大纲')
    case 'questions': return page('', '动笔前提问')
    case 'critique': return page('', '开书方案')
    case 'volume_plan': case 'volume_directions': case 'volume_pitch': case 'pitch_scores': case 'volume_audit': case 'volume_recap': {
      const n = positive(data.volume ?? data.index)
      return n ? page(`/outline?node=volume-${n}`, `第 ${n} 卷卷纲`) : null
    }
    case 'chapter_plan': case 'unit_recap': {
      // Existing messages identify the unit as 第N卷第M单元「标题」, not a database id.
      const named = String(data.unit ?? '')
      const n = positive(data.volume) ?? positive(named.match(/第\s*(\d+)\s*卷/)?.[1])
        ?? outline?.volumes.find(v => v.units.some(u => u.id === data.unit_id || u.id === data.unit || u.title === named))?.index
      return n ? page(`/outline?node=volume-${n}`, `第 ${n} 卷卷纲`) : null
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
    case 'setup_pitches': return { path: `${base}/concept`, label: '三个短版' };
    case 'setup_directions': return { path: base, label: '开书方向' }
    case 'setup_piece': {
      const PIECES = setupPieces(pending.flow)
      const index = PIECES.findIndex(piece => piece.key === pending.piece)
      const piece = PIECES[index]
      return piece ? { path: `${base}${piece.path}`, label: `第 ${index + 1} 块：${piece.name}` } : null
    }
    case 'segment_review': return { path: `${base}/next-segment`, label: `第 ${pending.number} 篇` }
    case 'volume_review': return { path: `${base}/outline?node=volume-${pending.volume}`, label: `第 ${pending.volume} 卷卷纲` }
    case 'trial_read': return { path: `${base}/chapter/1`, label: `前 ${pending.chapters} 章试读` }
    case 'chapter_stuck': return { path: `${base}/chapter/${pending.chapter}`, label: `第 ${pending.chapter} 章` }
    default: return null
  }
}

const SETUP_OUTPUTS = new Set(['pitches', 'settings_focus', 'settings_rest', 'directions', 'concept', 'protagonist', 'world', 'segment', 'segment_volumes', 'lore', 'spine', 'threads', 'outline', 'volume_plan'])
const WRITE_OUTPUTS = new Set(['segment_plan', 'segment_volumes', 'volume_plan', 'volume_directions', 'volume_pitch', 'pitch_scores', 'volume_audit', 'chapter_plan', 'chapter_final'])

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
    const target = job.kind !== 'book_setup' && message.payload?.type === 'segment_volumes'
      ? { path: `/books/${bookId}/next-segment`, label: '这一篇的分卷' }
      : artifactTarget(message, bookId, outline)
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

export function progressText(book: BookDetail, messages: MeetingMessage[], draft: LiveDraft | null, target: WorkspaceTarget | null, writing?: { nodes: StoryNode[]; volumes: Volume[]; chapters: ChapterBrief[] }) {
  const job = book.active_job
  const PIECES = setupPieces(job?.setup_flow)
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_pitches') return '等你选择：三个短版'
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_directions') return '等你选择：开书方向'
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_piece') return `等你确认：${PIECES.find(piece => piece.key === (job.pending as Extract<Pending, { kind: 'setup_piece' }>).piece)?.name ?? '当前拼图'}`
  const position = writing && writingPosition(writing.nodes, writing.volumes, writing.chapters, book.concept)
  const mapReady = !!writing && (writing.nodes.length > 0 || !writing.volumes.some(volume => volume.target_node_id))
  const complete = !!writing && mapReady && isWritingComplete(writing.volumes, writing.chapters, writing.nodes)
  const segmentFinished = !!writing && writing.nodes.some(node => node.segment) && !complete && isWritingComplete(writing.volumes, writing.chapters)
  const waiting = `${job?.pending?.kind === 'setup_questions' ? '等你回答' : job?.pending?.kind === 'segment_review' ? '等你确认' : '等你拍板'}：${target?.label ?? '编辑部的提问'}`
  if (job?.status === 'waiting_author' && position?.volume == null) return waiting
  const working = job?.status === 'queued' || job?.status === 'running'
  const lastStatus = [...messages].reverse().find(m => m.job_id === job?.id && m.kind === 'status')
  if (working && job.kind === 'book_setup') {
    const index = PIECES.findIndex(piece => piece.key === book.setup_progress?.current)
    const status = lastStatus?.content.replace(/[.…]+$/, '') ?? '主编在准备方案'
    return book.setup_progress?.mode === 'puzzle' && index >= 0 ? `开书 · 第 ${index + 1} 块「${PIECES[index].name}」· ${status}` : `开书中 · ${status}`
  }
  const volume = position?.volume ?? target?.path?.match(/[?&]node=volume-(\d+)(?:[&#]|$)/)?.[1] ?? target?.path?.match(/\/volume\/(\d+)$/)?.[1]
  let progress = `${volume ? `第 ${volume} 卷 · ` : ''}已定稿 ${book.chapters_final} 章`
  const segmentNumber = writing && position ? writingSegmentNumber(writing.nodes, writing.volumes, position) : null
  if (segmentNumber != null && position?.volume != null && !complete && !segmentFinished) progress = `第 ${segmentNumber} 篇 · 第 ${position.volume} 卷 ${position.doneInVolume}/${position.volumeChapters} 章`
  if (segmentFinished && writing) progress = segmentFinishedText(writing.nodes, writing.volumes)
  if (position?.volume != null && writing && !complete && !segmentFinished) {
    if (position.nextNode) progress += ` · 离「${position.nextNode.title}」还有 ${position.chaptersToNode} 章`
    else if (mapReady && writing.volumes.some(item => item.target_node_id)) {
      const remaining = Math.max(0, writing.volumes.reduce((sum, item) => sum + plannedVolumeChapters(item), 0) - writing.chapters.filter(item => item.status === 'final').length)
      progress += ` · 正在写最后一篇，离结局还有 ${remaining} 章`
    }
  }
  if (job?.status === 'waiting_author') return `${progress} · ${waiting}`
  if (working) return `${progress} · ${draft && !draft.done && draft.job_id === job.id ? `写手在写第 ${draft.chapter} 章` : lastStatus?.content.replace(/[.…]+$/, '') ?? '编辑部工作中'}`
  if (job?.status === 'failed') return `${progress} · 任务出错，可继续`
  if (segmentFinished) return progress
  return `${progress} · ${book.status === 'completed' || complete ? '全书完结' : segmentFinished && writing ? segmentFinishedText(writing.nodes, writing.volumes) : '编辑部空闲'}`
}

/** 新五块各有独立路径，一律由 NavLink 按实际路由匹配。 */
export function puzzleSidebarActive(): undefined {
  return undefined
}

export interface NodeFeedback { nodeId: string; prefix: string }

export function nodeFeedback(node: Pick<StoryNode, 'id' | 'index' | 'title'>): NodeFeedback {
  return { nodeId: node.id, prefix: `关于节点 ${node.index}「${node.title}」：` }
}

/** 前缀被删除或改写即取消定向授权；之后再次输入相似文字也不恢复旧授权。 */
export function retainedNodeFeedback(text: string, selected: NodeFeedback | null): NodeFeedback | null {
  return selected && text.startsWith(selected.prefix) ? selected : null
}

export function composerRoute(job: Job | null, text: string, selected: NodeFeedback | null, direct = false) {
  // 旧图不再接受修改；点名私聊只记作者要求，不触发旧流程。
  if (job?.kind === 'book_setup' && job.setup_flow !== 3) return { kind: direct ? 'note' as const : 'blocked' as const }
  // 新三步的意见只交给当前步骤；旧图已在上方阻断，不恢复旧块锁定或解锁动作。
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_piece') return { kind: 'piece' as const, action: 'revise' as const, piece: job.pending.piece, ...(job.pending.piece === 'segment' && retainedNodeFeedback(text, selected) ? { node_id: selected!.nodeId } : {}) }
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_pitches') return { kind: 'pitches' as const, action: 'redo' as const }
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_directions') return { kind: 'directions' as const, action: 'redo' as const }
  if (job?.status === 'waiting_author' && job.pending?.kind === 'segment_review') return { kind: 'segment' as const, action: 'revise' as const }
  if (job?.status === 'waiting_author' && job.pending?.kind !== 'setup_questions') return { kind: 'decision' as const, action: 'revise' as const }
  return { kind: 'note' as const }
}

/** 初次出方向和选定方向后的定调是两种不同的等待，不假定作者已经做过选择。 */
export function directionProgressText(jobId: string, messages: MeetingMessage[]) {
  const chosen = messages.some(message => message.job_id === jobId && message.speaker === 'author' && message.kind === 'decision' && (message.content.startsWith('选方向「') || message.content.startsWith('选短版「')))
  return chosen ? '主编正在按你的选择定调…' : '主编正在拟定开书方向…'
}
