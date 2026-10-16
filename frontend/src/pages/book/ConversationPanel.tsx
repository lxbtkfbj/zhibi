import { useReducedMotion } from '../../lib/appearance'
import clsx from 'clsx'
import { ArrowRight, SendHorizontal } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { useJobActions } from '../../api/hooks'
import { Button, ErrorText } from '../../components/ui'
import { decisionCopy } from '../../lib/decision'
import { ROLE_META } from '../../lib/roles'
import { teamStatus } from '../../lib/team'
import { composerRoute, pendingTarget, retainedNodeFeedback } from '../../lib/workspace'
import { useBookContext } from './context'
import { ResumeControls, RunningControls, WritingControls } from './Decision'
import { MeetingFeed, RoleAvatar } from './MeetingFeed'

const DUTIES = {
  chief: '方向、大纲、章纲',
  lorekeeper: '人物、世界观、伏笔台账',
  writer: '正文',
  reviewer: '审稿意见',
} as const

const QUICK_PHRASES = {
  chief: ['调整故事方向', '改一下大纲', '这段节奏再快一点'],
  lorekeeper: ['改人物', '补设定', '查矛盾'],
  writer: ['这章节奏快一点', '对话少一点', '多一点细节'],
  reviewer: ['检查人物动机', '看看节奏', '检查前后矛盾'],
} as const

/** 每个会话保留自己的草稿；切稿件路由不会重挂载这块区域。 */
function NoteComposer() {
  const { job, working, waiting, asking, bookId, book, conversation, focusComposer, composerNode, setComposerNode, composerDrafts: drafts, setComposerDrafts: setDrafts } = useBookContext()
  const { note, decide, directions, piece, segment, segmentPending } = useJobActions(bookId)
  const [sent, setSent] = useState<{ conversation: string; message: string } | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)
  const sending = useRef(false)
  const text = drafts[conversation] ?? ''
  const direct = conversation !== 'group'
  const oldSetup = job?.kind === 'book_setup' && job.setup_flow === 1
  const blocked = oldSetup && !direct
  const revising = waiting && !oldSetup
  const feedbackPrefix = direct ? `（给${ROLE_META[conversation].name}）` : ''
  const inputLimit = waiting ? 5000 - feedbackPrefix.length : 5000
  const tooLong = text.trim().length > inputLimit
  const pending = note.isPending || decide.isPending || directions.isPending || piece.isPending || segmentPending
  const error = note.error ?? decide.error ?? directions.error ?? piece.error ?? segment.error
  const idle = !working && !waiting && !asking
  const resumable = job?.status === 'failed' || job?.status === 'cancelled'

  useEffect(() => {
    const element = ref.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`
  }, [text])

  useEffect(() => {
    if (focusComposer > 0) ref.current?.focus()
  }, [focusComposer])

  useEffect(() => {
    if (!sent) return
    const timer = setTimeout(() => setSent(null), 6000)
    return () => clearTimeout(timer)
  }, [sent])

  const setText = (value: string) => {
    setDrafts((previous) => ({ ...previous, [conversation]: value }))
    if (conversation === 'group') setComposerNode(retainedNodeFeedback(value, composerNode))
  }
  const send = async () => {
    const content = text.trim()
    if (!content || pending || sending.current || tooLong || blocked) return
    sending.current = true
    const sentConversation = conversation
    try {
      const route = composerRoute(job, text, conversation === 'group' ? composerNode : null, direct)
      if (route.kind === 'blocked') return
      if (route.kind === 'directions' && job) {
        await directions.mutateAsync({ jobId: job.id, action: 'redo', feedback: `${feedbackPrefix}${content}` })
      } else if (route.kind === 'piece' && job) {
        await piece.mutateAsync({ jobId: job.id, action: 'revise', piece: route.piece, feedback: `${feedbackPrefix}${content}`, ...('node_id' in route ? { node_id: route.node_id } : {}) })
      } else if (route.kind === 'segment' && job) {
        await segment.mutateAsync({ jobId: job.id, action: 'revise', feedback: `${feedbackPrefix}${content}` })
      } else if (route.kind === 'decision' && job) {
        await decide.mutateAsync({
          jobId: job.id,
          action: 'revise',
          feedback: `${feedbackPrefix}${content}`,
        })
      } else {
        await note.mutateAsync({ content, ...(direct ? { to: conversation } : {}) })
      }
      setDrafts((previous) => previous[sentConversation] === text ? { ...previous, [sentConversation]: '' } : previous)
      if (sentConversation === 'group') setComposerNode(null)
      setSent({
        conversation: sentConversation,
        message: revising ? '意见已交给编辑部，按你的要求修改。' : !oldSetup && (asking || (working && (job?.kind === 'book_setup' || job?.kind === 'write_book')))
          ? '已送达。做完手头这一步后，编辑部会处理你的要求。'
          : '已记下，下次开工会按你的要求来。',
      })
    } catch {
      // 错误由 ErrorText 展示；失败时保留作者原文，不清空、不重发。
    } finally { sending.current = false }
  }

  const placeholder = blocked ? '这本书要先按新流程重开，重开后再提意见' : direct
    ? `发消息给${ROLE_META[conversation].name}…`
    : waiting && job?.pending?.kind === 'setup_piece' ? '说说这一块想怎么改…' : waiting
      ? job?.pending?.kind === 'setup_directions'
        ? '写下哪里不满意，主编会重新出开书方向…'
        : decisionCopy(job?.pending, bookId).placeholder
      : asking
        ? '还有别的要求也可以先说，例如：主角叫云澈'
        : working
          ? '插句话，例如：金手指再巧妙一点；开局直接打脸'
          : '说说你的要求，编辑部下次开工会照办…'

  return (
    <div className="shrink-0 border-t border-divider bg-pane-mid px-4 pt-3 pb-3">
      {idle && !resumable && (book.status === 'ready' || book.status === 'writing') && (
        <div className="mb-3 border-b border-divider pb-3"><WritingControls compact /></div>
      )}
      {direct && (
        <div className="mb-2 flex flex-wrap gap-1.5" aria-label="快捷短语">
          {QUICK_PHRASES[conversation].map((phrase) => (
            <button
              key={phrase}
              type="button"
              onClick={() => { setText(phrase); ref.current?.focus() }}
              className="rounded-full border border-divider bg-card px-2.5 py-1 text-xs text-ink-2 transition-colors hover:border-ink-3 hover:text-ink"
            >{phrase}</button>
          ))}
        </div>
      )}
      {revising && <p className="mb-2 text-xs font-medium text-seal">提意见 · 发送后会修改当前待拍板的方案</p>}
      <div className="flex items-end gap-2 rounded-xl border border-divider bg-card px-3 py-2 transition-shadow focus-within:border-ink-3 focus-within:shadow-[var(--shadow-paper)]">
        <textarea
          ref={ref}
          value={text}
          rows={2}
          maxLength={inputLimit}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // keyCode 229 兼容部分输入法 compositionend / keydown 的不同触发顺序。
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
              event.preventDefault()
              void send()
            }
          }}
          placeholder={placeholder}
          aria-label={direct ? `发消息给${ROLE_META[conversation].name}` : revising ? '修改意见' : '给编辑部发消息'}
          className="scroll-thin max-h-40 min-h-12 min-w-0 flex-1 resize-none bg-transparent py-1 text-sm leading-[1.75] text-ink placeholder:text-ink-3 focus:outline-none"
        />
        <Button size="sm" variant={revising ? 'primary' : 'seal'} onClick={() => void send()} loading={pending} disabled={!text.trim() || tooLong || blocked} aria-label="发送">
          {revising ? '提意见' : <SendHorizontal className="size-4" />}
        </Button>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink-2" role="status">
        {sent?.conversation === conversation ? sent.message : 'Enter 发送，Shift + Enter 换行。'}
      </p>
      <ErrorText error={error} />
      {tooLong && <p className="mt-2 text-sm text-seal">当前意见最多 {inputLimit} 字，请精简后发送。原文已保留。</p>}
    </div>
  )
}

/** 中栏固定会话：群聊、点名插话与产出卡片。 */
export function ConversationPanel() {
  const { bookId, job, messages, working, connected, draft, conversation, asking, waiting, manualNavigate } = useBookContext()
  const [showGroup, setShowGroup] = useState(true)
  const reduce = useReducedMotion()
  const direct = conversation !== 'group'
  const status = teamStatus(messages, working)
  const copy = decisionCopy(job?.pending, bookId)
  const pending = job?.pending
  const destination = pendingTarget(pending, bookId)
  const todoLabel = destination?.label ?? (asking ? '动笔前提问'
    : pending?.kind === 'volume_review' ? `第 ${pending.volume} 卷卷纲`
      : pending?.kind === 'trial_read' ? `前 ${pending.chapters} 章试读`
        : pending?.kind === 'chapter_stuck' ? `第 ${pending.chapter} 章`
          : '开书方案')
  const todoPath = destination?.path ?? (asking || pending?.kind === 'setup_review' ? `/books/${bookId}` : copy.links[0]?.[1] ?? `/books/${bookId}`)

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col bg-pane-mid" aria-label="会话消息与输入">
      <header className="shrink-0 border-b border-divider px-4 py-3">
        <div className="flex items-center gap-2.5">
          <RoleAvatar speaker={conversation} working={direct && status[conversation].state === 'working'} />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-medium text-ink">{direct ? ROLE_META[conversation].name : '编辑部群聊'}</h2>
            <p className="mt-0.5 text-xs text-ink-2">{direct ? DUTIES[conversation] : '主编 · 设定师 · 写手 · 审稿'}</p>
          </div>
          <span className={clsx('flex shrink-0 items-center gap-1 text-xs', connected ? 'text-lore' : 'text-ink-2')}>
            <span className={clsx('size-1.5 rounded-full', connected ? 'bg-lore' : 'bg-ink-3')} />
            {connected ? working ? '工作中' : '在线' : '连接中'}
          </span>
        </div>
        {direct && (
          <label className="mt-2.5 flex cursor-pointer items-center gap-2 text-xs text-ink-2">
            <input type="checkbox" checked={showGroup} onChange={(event) => setShowGroup(event.target.checked)} className="size-3.5 accent-[var(--color-chief)]" />
            显示他在群里的发言
          </label>
        )}
      </header>
      <AnimatePresence initial={false}>
        {(asking || waiting) && (
          <motion.button
            type="button"
            initial={reduce ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: reduce ? 0 : 0.28, ease: 'easeOut' }}
            onClick={() => manualNavigate(todoPath)}
            className="flex shrink-0 items-center justify-between gap-2 overflow-hidden border-b border-seal/20 bg-seal-soft px-4 text-left text-sm text-seal"
          >
            <span className="py-2.5">1 件待你处理：{todoLabel}</span><ArrowRight className="size-4 shrink-0" />
          </motion.button>
        )}
      </AnimatePresence>
      <MeetingFeed messages={messages} working={working} draft={draft} conversation={conversation} showGroup={showGroup} className="min-h-0 flex-1 px-4 py-5" />
      {job && working && <div className="shrink-0 border-t border-divider px-4 py-2"><RunningControls job={job} /></div>}
      {job && (job.status === 'failed' || job.status === 'cancelled') && <div className="shrink-0 border-t border-divider px-4 py-3"><ResumeControls job={job} /></div>}
      <NoteComposer />
    </section>
  )
}
