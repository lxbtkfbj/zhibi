import { post } from '../../api/client'
import type { MeetingMessage } from '../../api/types'
import { sendChatFirst, typingVisible } from '../../lib/chat'
import { ROLE_META as ROLES } from '../../lib/roles'
import { useReducedMotion } from '../../lib/appearance'
import clsx from 'clsx'
import { ArrowRight, SendHorizontal } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { useGroupFeedback } from './useGroupFeedback'
import { Button, ErrorText } from '../../components/ui'
import { decisionCopy } from '../../lib/decision'
import { ROLE_META } from '../../lib/roles'
import { teamStatus } from '../../lib/team'
import { pendingTarget, retainedNodeFeedback } from '../../lib/workspace'
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
  chief: ['为什么这样安排？', '帮我想想这里怎么更爽', '后面打算怎么走？'],
  lorekeeper: ['主角现在什么境界？', '这个设定前后对得上吗？', '谁知道主角的秘密？'],
  writer: ['这种场面怎么写更爽？', '示范一下这种写法', '文风哪里还能改？'],
  reviewer: ['最近一章哪里不好看？', '这个设定有漏洞吗？', '节奏拖不拖？'],
} as const

/** 每个会话保留自己的草稿；切稿件路由不会重挂载这块区域。 */
function NoteComposer() {
  const { job, working, waiting, asking, bookId, book, conversation, focusComposer, composerNode, setComposerNode, composerDrafts: drafts, setComposerDrafts: setDrafts, segmentReview, chatQuotes, setChatQuotes } = useBookContext()
  const feedback = useGroupFeedback()
  const [sendError, setSendError] = useState<unknown>(null)
  const [sendingNote, setSendingNote] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)
  const sending = useRef(false)
  const text = drafts[conversation] ?? ''
  const direct = conversation !== 'group'
  const oldSetup = job?.kind === 'book_setup' && job.setup_flow !== 3
  const legacyArc = job?.status === 'waiting_author' && job.pending?.kind === 'segment_review' && job.pending.flow === 2
  const revising = !direct && waiting && !oldSetup && !legacyArc
  const inputLimit = 5000
  const tooLong = text.trim().length > inputLimit
  const pending = sendingNote || segmentReview.submitting
  const error = sendError
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



  const setText = (value: string) => {
    setDrafts((previous) => ({ ...previous, [conversation]: value }))
    if (conversation === 'group') setComposerNode(retainedNodeFeedback(value, composerNode))
  }
  const send = async () => {
    const content = text.trim()
    if (!content || pending || sending.current || tooLong) return
    sending.current = true
    const sentConversation = conversation
    try {
      setSendError(null); setSendingNote(true)
      await sendChatFirst(
        () => post<MeetingMessage>(`/books/${bookId}/notes`, { content, ...(direct ? { to: conversation } : {}), ...(chatQuotes[conversation] ? { quote: chatQuotes[conversation] } : {}) }),
        () => feedback(content), direct)
      setChatQuotes(previous => ({ ...previous, [sentConversation]: null }))
      setDrafts((previous) => previous[sentConversation] === text ? { ...previous, [sentConversation]: '' } : previous)
      if (sentConversation === 'group') setComposerNode(null)

    } catch (cause) {
      setSendError(cause)
    } finally { sending.current = false; setSendingNote(false) }
  }

  const placeholder = direct ? `和${ROLE_META[conversation].name}聊聊，不会改动书稿…` : legacyArc ? '这一篇要先按新写法重出，重出后再提意见'
    : waiting && job?.pending?.kind === 'setup_piece' ? '说说这一块想怎么改…' : waiting
      ? job?.pending?.kind === 'setup_pitches'
        ? '写下哪里不满意，主编会重新出三个短版…'
        : job?.pending?.kind === 'setup_directions'
        ? '写下哪里不满意，主编会重新出开书方向…'
        : decisionCopy(job?.pending, bookId).placeholder
      : asking
        ? '还有别的要求也可以先说，例如：主角叫云澈'
        : working
          ? '插句话或者问一句都行，例如：从下一章开始节奏快一点'
          : '交代事情或者问问题都行，例如：下一卷感情线慢一点；主角现在什么境界？'

  return (
    <div className="shrink-0 border-t border-divider bg-pane-mid px-4 pt-3 pb-3">
      {!direct && idle && !resumable && (book.status === 'ready' || book.status === 'writing') && (
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
      {chatQuotes[conversation] && <div className="mb-2 flex items-start gap-2 rounded-lg bg-paper p-2 text-xs text-ink-2"><span className="min-w-0 flex-1 break-words">引用：{chatQuotes[conversation]!.where} · {chatQuotes[conversation]!.text.slice(0, 30)}……</span><button aria-label="取消引用" onClick={() => setChatQuotes(previous => ({ ...previous, [conversation]: null }))}>×</button></div>}
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
        <Button size="sm" variant={revising ? 'primary' : 'seal'} onClick={() => void send()} loading={pending} disabled={!text.trim() || tooLong} aria-label="发送">
          <SendHorizontal className="size-4" />
        </Button>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink-2" role="status">
        Enter 发送，Shift + Enter 换行。
      </p>
      <ErrorText error={error} />
      {tooLong && <p className="mt-2 text-sm text-seal">当前意见最多 {inputLimit} 字，请精简后发送。原文已保留。</p>}
    </div>
  )
}

/** 中栏固定会话：群聊、点名插话与产出卡片。 */
export function ConversationPanel() {
  const { bookId, job, messages, working, connected, draft, conversation, asking, waiting, manualNavigate, chatTyping } = useBookContext()
  const [now, setNow] = useState(() => Date.now())
  const [resetError, setResetError] = useState<unknown>(null)
  const [resetting, setResetting] = useState(false)
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
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
          <Button size="sm" variant="ghost" disabled={resetting} onClick={async () => { setResetting(true); setResetError(null); try { await post(`/books/${bookId}/chat/${conversation}/reset`) } catch (cause) { setResetError(cause) } finally { setResetting(false) } }}>换个话题</Button>
          <span className={clsx('flex shrink-0 items-center gap-1 text-xs', connected ? 'text-lore' : 'text-ink-2')}>
            <span className={clsx('size-1.5 rounded-full', connected ? 'bg-lore' : 'bg-ink-3')} />
            {connected ? working ? '工作中' : '在线' : '连接中'}
          </span>
        </div>
        <ErrorText error={resetError} />
        {direct && <p className="mt-2 text-xs leading-relaxed text-ink-2">这里只聊天，不会改动书稿，也不会记成要求。聊出结论，点最新回复下面的「记成要求」或「照这个改」。</p>}
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
      {Object.values(chatTyping).filter(value => typingVisible(value, conversation, now)).map(value => <p key={value.thread} role="status" className="px-4 py-2 text-xs text-chief">{ROLES[value.speaker as keyof typeof ROLES]?.name ?? '主编'}正在想…</p>)}
      <NoteComposer />
    </section>
  )
}
