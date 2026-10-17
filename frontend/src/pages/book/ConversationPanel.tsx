import { post } from '../../api/client'
import type { Conversation, MeetingMessage } from '../../api/types'
import { sendChatFirst, typingVisible } from '../../lib/chat'
import clsx from 'clsx'
import { ArrowRight, ArrowUp, ListChecks, MoreHorizontal, RotateCcw, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useGroupFeedback } from './useGroupFeedback'
import { ErrorText, Spinner } from '../../components/ui'
import { decisionCopy } from '../../lib/decision'
import { ROLE_META } from '../../lib/roles'
import { TEAM, teamStatus } from '../../lib/team'
import { pendingTarget, retainedNodeFeedback } from '../../lib/workspace'
import { useBookContext } from './context'
import { MeetingFeed, RoleAvatar } from './MeetingFeed'

const QUICK_PHRASES = {
  chief: ['为什么这样安排？', '帮我想想这里怎么更爽', '后面打算怎么走？'],
  lorekeeper: ['主角现在什么境界？', '这个设定前后对得上吗？', '谁知道主角的秘密？'],
  writer: ['这种场面怎么写更爽？', '示范一下这种写法', '文风哪里还能改？'],
  reviewer: ['最近一章哪里不好看？', '这个设定有漏洞吗？', '节奏拖不拖？'],
} as const

/** 群聊和四个私聊的切换：放在聊天栏自己顶上，点哪里就变哪里。 */
function ConversationTabs() {
  const { conversation, setConversation, messages, working, unread } = useBookContext()
  const statuses = teamStatus(messages, working)
  return <div role="tablist" aria-label="编辑部会话" className="no-scrollbar flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
    {(['group', ...TEAM] as Conversation[]).map(role => {
      const name = role === 'group' ? '编辑部群聊' : ROLE_META[role].name
      const busy = role !== 'group' && statuses[role].state === 'working'
      const active = conversation === role
      return <button key={role} type="button" role="tab" data-conversation={role} aria-selected={active} aria-pressed={active} aria-label={name}
        title={role === 'group' ? name : `${name} · ${ROLE_META[role].duty} · ${statuses[role].text}`}
        onClick={() => setConversation(role)}
        className={clsx('relative flex shrink-0 items-center gap-1.5 rounded-lg py-1 pr-2 pl-1 text-[13px] transition-colors', active ? 'bg-card font-medium text-ink ring-1 ring-line' : 'text-ink-2 hover:bg-card/60 hover:text-ink')}>
        <RoleAvatar speaker={role} size="sm" working={busy} />
        <span className={clsx(role !== 'group' && !active && 'hidden @md/chat:inline')}>{role === 'group' ? '群聊' : ROLE_META[role].name}</span>
        {unread[role] > 0 && <span aria-label={`${unread[role]} 条未读`} className="absolute -top-0.5 left-5 min-w-4 rounded-full bg-seal px-1 text-center text-[11px] leading-4 text-on-role tabular-nums">{unread[role] > 99 ? '99+' : unread[role]}</span>}
      </button>
    })}
  </div>
}

/** 「换个话题」不常用，收进更多菜单。 */
function MoreMenu({ disabled, onReset }: { disabled: boolean; onReset: () => void }) {
  const ref = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const close = (event: PointerEvent) => { if (ref.current?.open && !ref.current.contains(event.target as Node)) ref.current.open = false }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [])
  return <details ref={ref} className="relative shrink-0">
    <summary aria-label="更多" title="更多" className="flex size-8 cursor-pointer list-none items-center justify-center rounded-lg text-ink-2 hover:bg-line/60 hover:text-ink [&::-webkit-details-marker]:hidden"><MoreHorizontal className="size-4" /></summary>
    <div className="absolute top-9 right-0 z-30 w-56 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]">
      <button type="button" disabled={disabled} onClick={() => { if (ref.current) ref.current.open = false; onReset() }} className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink hover:bg-subtle disabled:opacity-50">
        <RotateCcw className="mt-0.5 size-3.5 shrink-0 text-ink-2" /><span>换个话题<span className="mt-0.5 block text-xs text-ink-3">之前聊的不再带进这个会话的回答</span></span>
      </button>
    </div>
  </details>
}

/** 每个会话保留自己的草稿；切稿件路由不会重挂载这块区域。 */
function NoteComposer() {
  const { job, working, waiting, asking, bookId, conversation, focusComposer, composerNode, setComposerNode, composerDrafts: drafts, setComposerDrafts: setDrafts, segmentReview, chatQuotes, setChatQuotes, resumeFollow } = useBookContext()
  const feedback = useGroupFeedback()
  const [sendError, setSendError] = useState<unknown>(null)
  const [sendingNote, setSendingNote] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)
  const sending = useRef(false)
  const text = drafts[conversation] ?? ''
  const direct = conversation !== 'group'
  const oldSetup = job?.kind === 'book_setup' && job.setup_flow !== 3
  const legacyArc = job?.status === 'waiting_author' && job.pending?.kind === 'segment_review' && job.pending.flow === 2
  const inputLimit = 5000
  const tooLong = text.trim().length > inputLimit
  const pending = sendingNote || segmentReview.submitting
  const target = waiting ? pendingTarget(job?.pending, bookId) : null

  useEffect(() => {
    const element = ref.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`
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
        ? '写下哪里不满意，主编会重新出三个故事方向…'
        : job?.pending?.kind === 'setup_directions'
        ? '写下哪里不满意，主编会重新出开书方向…'
        : decisionCopy(job?.pending, bookId).placeholder
      : asking
        ? '还有别的要求也可以先说，例如：主角叫云澈'
        : working
          ? '插句话或者问一句都行，例如：从下一章开始节奏快一点'
          : '交代事情或者问问题都行，例如：下一卷感情线慢一点；主角现在什么境界？'
  // 只在等你拍板时说清楚：这时候发的话会被怎么处理。
  const context = direct || oldSetup ? null : legacyArc ? '这一篇要先按新写法重出，重出后再提意见'
    : waiting && job?.pending?.kind === 'setup_pitches' ? '等你选故事方向：明说要改，主编就重出三个；提问照常回答'
      : waiting && job?.pending?.kind === 'setup_directions' ? '等你选开书方向：明说要改，主编会重新出方向'
        : waiting && target ? `等你${job?.pending?.kind === 'setup_piece' || job?.pending?.kind === 'segment_review' ? '确认' : '拍板'}「${target.label}」：明说要改，会当成修改意见；提问照常回答`
          : asking ? '主编在等你回答动笔前的提问；别的要求也可以先在这里说' : null

  return (
    <div className="shrink-0 px-4 pt-2 pb-4">
      {context && <div className="mb-2 flex items-center gap-1.5 text-xs leading-relaxed text-seal-dark">
        <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-seal" /><span className="min-w-0 flex-1">{context}</span>
        <button type="button" onClick={resumeFollow} className="flex shrink-0 items-center gap-0.5 text-chief hover:underline lg:hidden">去处理<ArrowRight className="size-3" /></button>
      </div>}
      {direct && (
        <div className="no-scrollbar mb-2 flex gap-1.5 overflow-x-auto" aria-label="快捷短语">
          {QUICK_PHRASES[conversation].map((phrase) => (
            <button key={phrase} type="button" onClick={() => { setText(phrase); ref.current?.focus() }}
              className="shrink-0 rounded-full border border-line-2 bg-card px-2.5 py-1 text-xs text-ink-2 transition-colors hover:border-ink-3 hover:text-ink">{phrase}</button>
          ))}
        </div>
      )}
      {chatQuotes[conversation] && <div className="mb-2 flex items-start gap-2 rounded-lg border-l-2 border-chief bg-card px-2.5 py-1.5 text-xs text-ink-2"><span className="min-w-0 flex-1 break-words">引用 {chatQuotes[conversation]!.where}：{chatQuotes[conversation]!.text.slice(0, 30)}……</span><button aria-label="取消引用" className="text-ink-3 hover:text-ink" onClick={() => setChatQuotes(previous => ({ ...previous, [conversation]: null }))}><X className="size-3.5" /></button></div>}
      <div className="group rounded-xl border border-line-2 bg-card transition-[border-color,box-shadow] focus-within:border-ink-3/70 focus-within:shadow-[var(--shadow-paper)]">
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
          aria-label={direct ? `发消息给${ROLE_META[conversation].name}` : waiting && !oldSetup && !legacyArc ? '修改意见' : '给编辑部发消息'}
          className="scroll-thin block max-h-44 min-h-14 w-full resize-none bg-transparent px-3.5 pt-3 pb-1 text-sm leading-[1.75] text-ink placeholder:text-ink-3 focus:outline-none"
        />
        <div className="flex items-center gap-2 px-2.5 pb-2">
          <span className="text-[11px] text-ink-3 opacity-0 transition-opacity group-focus-within:opacity-100">Enter 发送 · Shift + Enter 换行</span>
          <button type="button" aria-label="发送" onClick={() => void send()} disabled={!text.trim() || tooLong || pending}
            className="press ml-auto flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-paper-2 transition-colors hover:bg-ink-2 disabled:cursor-not-allowed disabled:bg-line-2 disabled:text-card">
            {pending ? <Spinner className="size-3.5" /> : <ArrowUp className="size-4" />}
          </button>
        </div>
      </div>
      <ErrorText error={sendError} />
      {tooLong && <p className="mt-2 text-sm text-seal">当前意见最多 {inputLimit} 字，请精简后发送。原文已保留。</p>}
    </div>
  )
}

/** 中栏固定会话：群聊、点名私聊与产出卡片。 */
export function ConversationPanel() {
  const { bookId, messages, connected, draft, conversation, working, chatTyping } = useBookContext()
  const [now, setNow] = useState(() => Date.now())
  const [resetError, setResetError] = useState<unknown>(null)
  const [resetting, setResetting] = useState(false)
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const [showGroup, setShowGroup] = useState(true)
  const direct = conversation !== 'group'
  const run = async (request: () => Promise<unknown>) => { setResetting(true); setResetError(null); try { await request() } catch (cause) { setResetError(cause) } finally { setResetting(false) } }
  const typing = Object.values(chatTyping).filter(value => typingVisible(value, conversation, now))

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col bg-pane-mid" aria-label="会话消息与输入">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-divider pr-2 pl-3">
        <ConversationTabs />
        {!connected && <span className="shrink-0 text-xs text-ink-3" role="status">连接中…</span>}
        <button type="button" disabled={resetting} title="把前面聊的整理成一张方案卡，看过再决定要不要照办"
          onClick={() => void run(() => post(`/books/${bookId}/notes`, { content: '总结一下前面聊的', ...(direct ? { to: conversation } : {}) }))}
          className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-line-2 bg-card px-2.5 text-[13px] text-ink hover:border-ink-3/50 disabled:opacity-50">
          <ListChecks className="size-3.5 text-chief" />总结一下
        </button>
        <MoreMenu disabled={resetting} onReset={() => void run(() => post(`/books/${bookId}/chat/${conversation}/reset`))} />
      </header>
      {direct && <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-divider px-4 py-2 text-xs text-ink-2">
        <span><span className={clsx('font-medium', ROLE_META[conversation].text)}>{ROLE_META[conversation].name}</span> · 管{ROLE_META[conversation].duty}</span>
        <span className="text-ink-3">只商量，不改书稿也不记要求；聊出想法点「总结一下」</span>
        <label className="ml-auto flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={showGroup} onChange={(event) => setShowGroup(event.target.checked)} className="size-3.5 accent-[var(--color-chief)]" />
          显示他在群里的发言
        </label>
      </div>}
      {!!resetError && <div className="shrink-0 px-4 pt-2"><ErrorText error={resetError} /></div>}
      <MeetingFeed messages={messages} working={working} draft={draft} conversation={conversation} showGroup={showGroup} className="min-h-0 flex-1 px-4 py-5" />
      {typing.map(value => <p key={value.thread} role="status" className="flex items-center gap-2 px-5 pb-1 text-xs text-ink-3"><RoleAvatar speaker={(value.speaker in ROLE_META ? value.speaker : 'chief') as keyof typeof ROLE_META} size="xs" />{ROLE_META[value.speaker as keyof typeof ROLE_META]?.name ?? '主编'}{value.mode === 'plan' ? '正在整理方案…' : '正在想…'}</p>)}
      <NoteComposer />
    </section>
  )
}
