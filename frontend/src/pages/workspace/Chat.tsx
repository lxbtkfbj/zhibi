/** 编辑部浮窗里的聊天：只有一个聊天，打 @ 点名找谁；回答边写边显示，回答时发送键变「停」；最新一条回答下面能重新回答，没答上来能重试。 */

import clsx from 'clsx'
import { AlertTriangle, ArrowDown, ArrowUp, AtSign, Check, ChevronDown, Copy, PencilLine, RotateCcw, Search, Square, X } from 'lucide-react'
import { type ReactNode, useLayoutEffect, useRef, useState } from 'react'
import { Spinner, TypingDots } from '../../components/ui'
import { CHAT_ROLES, type ChatControl, type ChatMessage, type ChatRole, chatRecipient, latestReply, mentionAt, takeMention } from './chatModel'
import { clearSentChatDraft, copyChatText, loadChatDraft, saveChatDraft, subscribeChatDraft, type ChatDraft } from './chatBrowser'

const ROLE_COLOR: Record<ChatRole, { dot: string; text: string; soft: string }> = {
  主编: { dot: 'bg-chief', text: 'text-chief', soft: 'bg-chief-soft' },
  设定师: { dot: 'bg-lore', text: 'text-lore', soft: 'bg-lore-soft' },
  写手: { dot: 'bg-writer', text: 'text-writer', soft: 'bg-writer-soft' },
  审稿: { dot: 'bg-reviewer', text: 'text-reviewer', soft: 'bg-reviewer-soft' },
}

function Avatar({ role, working, small }: { role: ChatRole; working?: boolean; small?: boolean }) {
  return (
    <span className={clsx('relative inline-flex shrink-0 items-center justify-center rounded-full font-serif text-on-role', ROLE_COLOR[role].dot, working && 'breath', small ? 'size-6 text-xs' : 'size-9 text-[15px]')}>
      {role[0]}
    </span>
  )
}

/** 编辑部某个人交的一整块（方案卡）：左边头像，右边名字和内容 */
export function RoleRow({ role, children }: { role: ChatRole; children: ReactNode }) {
  return (
    <div className="flex gap-2.5">
      <Avatar role={role} />
      <div className="min-w-0 flex-1">
        <p className={clsx('mb-1 text-xs font-medium', ROLE_COLOR[role].text)}>{role}</p>
        {children}
      </div>
    </div>
  )
}

const ACTION_CLASS = 'flex items-center gap-1 rounded-md px-1 py-0.5 text-xs whitespace-nowrap text-ink-3 transition-colors hover:bg-line/50 hover:text-ink'

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState<'idle' | 'done' | 'failed'>('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const mounted = useRef(true)
  const attempt = useRef(0)
  useLayoutEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; clearTimeout(timer.current) }
  }, [])
  const copy = async () => {
    const current = ++attempt.current
    clearTimeout(timer.current)
    const ok = await copyChatText(text)
    if (!mounted.current || current !== attempt.current) return
    setCopied(ok ? 'done' : 'failed')
    timer.current = setTimeout(() => setCopied('idle'), ok ? 2000 : 3000)
  }
  return (
    <button type="button" onClick={() => void copy()} className={clsx(ACTION_CLASS, copied === 'failed' && 'max-w-40 whitespace-normal text-left')}>
      {copied === 'done' ? <Check className="size-3.5 shrink-0" /> : <Copy className="size-3.5 shrink-0" />}
      <span aria-live="polite">{copied === 'done' ? '已复制' : copied === 'failed' ? '没复制上，选中文字手动复制' : '复制'}</span>
    </button>
  )
}

/** 作者的话：修改留在原气泡，下面输入框的草稿不动。 */
function AuthorBubble({ message, canRewind, onRewind, editing, chat, endRewind }: {
  message: ChatMessage; canRewind: boolean; onRewind: () => void; editing: boolean; chat: ChatControl; endRewind: () => void
}) {
  const [asking, setAsking] = useState(false)
  if (!canRewind && asking) setAsking(false)
  const rewind = () => {
    if (!canRewind) return
    if (message.rewind?.warn && !asking) setAsking(true)
    else {
      setAsking(false)
      onRewind()
    }
  }
  return (
    <div data-testid={`note-${message.id}`} className="group flex flex-col items-end">
      {editing ? <InlineEdit message={message} chat={chat} onCancel={endRewind} /> : (
        <div className="flex max-w-[85%] flex-col items-end">
          <p data-testid="author-bubble" className="min-w-0 max-w-full rounded-[16px_4px_16px_16px] bg-author-bubble px-4 py-2.5 chat-text leading-[1.75] break-words whitespace-pre-wrap text-ink">
            {message.to && <span className={clsx('mr-1.5 font-medium', ROLE_COLOR[message.to].text)}>@{message.to}</span>}
            {message.text}
          </p>
          <div data-testid="author-actions" className="mt-1.5 flex shrink-0 items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <CopyButton text={message.text} />
            {canRewind && message.rewind && (
              <button type="button" onClick={rewind} title="改这句话再发：这句和后面的聊天收起来，从改过的这句重新回答；书里改过的不跟着退" className={ACTION_CLASS}>
                <PencilLine className="size-3.5" />修改
              </button>
            )}
          </div>
        </div>
      )}
      {asking && (
        <div role="alertdialog" className="mt-1.5 max-w-[85%] rounded-lg border border-line bg-card px-3 py-2 text-[13px] leading-relaxed text-ink-2">
          <p>{message.rewind?.warn}</p>
          <div className="mt-1.5 flex justify-end gap-2">
            <button type="button" onClick={() => setAsking(false)} className="rounded-md px-2 py-0.5 text-ink-3 hover:bg-line/50 hover:text-ink">算了</button>
            <button type="button" onClick={rewind} className="rounded-md px-2 py-0.5 font-medium text-chief hover:bg-chief-soft">接着改</button>
          </div>
        </div>
      )}
      {message.below && <div className="max-w-[85%]">{message.below}</div>}
      {message.memories && <div className="max-w-[85%]"><MemoryBox>{message.memories}</MemoryBox></div>}
    </div>
  )
}

/** 回答下面一行小字「查了：陈默、第 12 章」，点开看查到的原文 */
function ReplyFooter({ items = [], children }: { items?: { label: string; text: string }[]; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const labels = [...new Set(items.map((item) => item.label))]
  return (
    <div className="mt-1.5 text-xs text-ink-3">
      <div data-testid="reply-footer" className="flex min-w-0 items-center gap-2">
        {!!items.length && <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} title="点开看查到的原文"
          className="flex min-w-0 items-center gap-1 rounded-md px-1 py-0.5 text-left transition-colors hover:bg-line/50 hover:text-ink">
          <Search className="size-3.5 shrink-0" /><span className="min-w-0 truncate">查了：{labels.join('、')}</span>
          <ChevronDown className={clsx('size-3.5 shrink-0 transition-transform', open && 'rotate-180')} />
        </button>}
        {children}
      </div>
      {open && !!items.length && (
        <div className="mt-1.5 space-y-1.5">
          {items.map((item, i) => (
            <div key={i} className="rounded-lg border border-line bg-card px-3 py-2">
              <p className="text-[11px] text-ink-3">{item.label}</p>
              <p className="scroll-thin mt-1 max-h-60 overflow-y-auto text-[13px] leading-relaxed break-words whitespace-pre-line text-ink-2">{item.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** 沿用查阅原文的圆角、细边与浅底；回执本身的字、撤销和灰态不动。 */
function MemoryBox({ children }: { children: ReactNode }) {
  return <div data-testid="chat-memory-box" className="mt-1.5 space-y-1.5 rounded-lg border border-line bg-card px-3 py-2 [&>div]:mt-0">{children}</div>
}

function Reply({ message, latest, answering, onAgain }: { message: ChatMessage; latest: boolean; answering: boolean; onAgain: () => void }) {
  const role = message.who as ChatRole
  const live = message.state === 'thinking' || message.state === 'streaming'
  // 最新一条答完了、停下了：复制旁边还能重新回答。
  const canAgain = latest && !answering && !!message.replyTo
  const canCopy = !live && !!message.text
  const showAgain = canAgain && (message.state === 'done' || message.state === 'stopped')
  return (
    <div data-testid={`reply-${message.id}`} data-state={message.state ?? 'done'} className="group flex gap-2.5">
      <Avatar role={role} working={live} />
      <div className="min-w-0 max-w-[calc(100%-46px)]">
        <p className={clsx('mb-1 text-xs font-medium', ROLE_COLOR[role].text)}>{role}</p>
        {message.state === 'thinking' ? (
          <div data-testid={`doing-${message.id}`} className="flex w-fit items-center gap-2 rounded-[4px_16px_16px_16px] bg-card px-4 py-3 text-[13px] text-ink-3 shadow-[0_1px_1px_rgb(60_40_20/0.05)]">
            <TypingDots />{message.doing ?? '在想'}
          </div>
        ) : message.state === 'failed' ? (
          <div className="flex items-start gap-2 rounded-xl border border-seal/30 bg-seal-soft px-3.5 py-2.5 text-[13px] leading-relaxed text-seal-dark">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span className="min-w-0 flex-1">没答上来：{message.error}</span>
            {canAgain && (
              <button type="button" onClick={onAgain} className="flex shrink-0 items-center gap-1 font-medium hover:underline">
                <RotateCcw className="size-3.5" />重试
              </button>
            )}
          </div>
        ) : message.text ? (
          <div className="w-fit max-w-full rounded-[4px_16px_16px_16px] bg-card px-4 py-2.5 chat-text leading-[1.75] text-ink shadow-[0_1px_1px_rgb(60_40_20/0.05)]">
            <span className={clsx('break-words whitespace-pre-wrap', message.state === 'streaming' && 'caret')}>{message.text}</span>
          </div>
        ) : null}
        {message.below}
        {message.memories && <MemoryBox>{message.memories}</MemoryBox>}
        {message.state === 'stopped' && (
          <p className="mt-1.5 text-xs text-ink-3">{message.text ? '你让它停下了，写出来的留着' : '还没开口就停下了'}</p>
        )}
        {(!live && !!message.looked?.length || canCopy || showAgain) && (
          <ReplyFooter items={!live ? message.looked : undefined}>
            <div className={clsx('flex shrink-0 items-center gap-2 transition-opacity', !latest && 'opacity-0 group-hover:opacity-100 focus-within:opacity-100')}>
              {canCopy && <CopyButton text={message.text} />}
              {showAgain && (
                <button type="button" onClick={onAgain} title="把上面你那句话重新答一遍，这一条换成新的" className={ACTION_CLASS}>
                  <RotateCcw className="size-3.5" />重新回答
                </button>
              )}
            </div>
          </ReplyFooter>
        )}
      </div>
    </div>
  )
}

function EmptyChat({ onPick }: { onPick: (role: ChatRole) => void }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4 py-8 text-center">
      <p className="font-serif text-lg text-ink">跟编辑部说点什么</p>
      <p className="mt-2 max-w-[22rem] text-[13px] leading-relaxed text-ink-3">想改哪儿、想问什么直接说，编辑部自己挑人来答。想找谁，就打 @ 点他的名：</p>
      <div className="mt-4 grid w-full max-w-[18rem] gap-1">
        {CHAT_ROLES.map(({ role, duty }) => (
          <button key={role} type="button" onClick={() => onPick(role)}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-colors hover:bg-card">
            <Avatar role={role} small />
            <span className="shrink-0 whitespace-nowrap text-[14px] text-ink">{role}</span>
            <span className="ml-auto min-w-0 text-xs text-ink-3">{duty}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

interface Mention { start: number; query: string; roles: ChatRole[]; index: number }

function MentionMenu({ mention, setMention, pick }: { mention: Mention | null; setMention: (value: Mention) => void; pick: (role: ChatRole) => void }) {
  if (!mention?.roles.length) return null
  return (
    <div role="listbox" aria-label="点名让谁来答" className="absolute bottom-[calc(100%-4px)] left-0 z-10 w-72 max-w-full rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]">
      <p className="px-2.5 pt-1 pb-1.5 text-xs text-ink-3">让谁来答 · 一次点一个</p>
      {mention.roles.map((role, i) => (
        <button key={role} type="button" role="option" aria-selected={i === mention.index}
          onMouseDown={(e) => e.preventDefault()} onClick={() => pick(role)} onMouseEnter={() => setMention({ ...mention, index: i })}
          className={clsx('flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left', i === mention.index && 'bg-subtle')}>
          <Avatar role={role} small /><span className="text-[14px] text-ink">{role}</span>
          <span className="ml-auto text-xs text-ink-3">{CHAT_ROLES.find((r) => r.role === role)?.duty}</span>
        </button>
      ))}
    </div>
  )
}

function RecipientBadge({ role, clear }: { role: ChatRole; clear?: () => void }) {
  return (
    <div className="px-3 pt-2.5">
      <span className={clsx('inline-flex items-center gap-1.5 rounded-full py-0.5 pr-1 pl-1 text-[13px]', ROLE_COLOR[role].soft, ROLE_COLOR[role].text)}>
        <Avatar role={role} small />问{role}
        {clear && <button type="button" onClick={clear} aria-label="不点名了" title="不点名，让编辑部自己挑人答"
          className="rounded-full p-0.5 opacity-70 hover:bg-card/70 hover:opacity-100"><X className="size-3.5" /></button>}
      </span>
    </div>
  )
}

function InlineEdit({ message, chat, onCancel }: { message: ChatMessage; chat: ChatControl; onCancel: () => void }) {
  const [text, setText] = useState(message.text)
  const [to, setTo] = useState(message.to)
  const [mention, setMention] = useState<Mention | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)
  const pending = useRef(false)
  const caretAt = useRef<number | null>(null)
  useLayoutEffect(() => {
    const field = ref.current
    if (!field) return
    field.focus()
    field.setSelectionRange(field.value.length, field.value.length)
  }, [])
  useLayoutEffect(() => {
    if (caretAt.current === null || !ref.current) return
    ref.current.setSelectionRange(caretAt.current, caretAt.current)
    caretAt.current = null
  })
  const look = (value: string, caret: number) => {
    const found = mentionAt(value, caret)
    setMention(found ? { ...found, index: 0 } : null)
  }
  const pick = (role: ChatRole) => {
    if (mention) {
      setText(text.slice(0, mention.start) + text.slice(mention.start + 1 + mention.query.length))
      caretAt.current = mention.start
    }
    setTo(role)
    setMention(null)
    ref.current?.focus()
  }
  const send = async () => {
    if (chat.answering || chat.sending || pending.current) return
    const taken = takeMention(text)
    const content = taken.text.trim()
    if (!content) return
    setMention(null)
    pending.current = true
    try {
      if ((await chat.send(content, chatRecipient(to, taken.to), message.id)) !== false) onCancel()
    } finally {
      pending.current = false
    }
  }
  return (
    <div data-testid="chat-inline-edit" className="relative w-[85%]">
      <MentionMenu mention={mention} setMention={setMention} pick={pick} />
      <div className="rounded-[14px] border border-line-2 bg-card transition-[border-color,box-shadow] focus-within:border-ink-3/70 focus-within:shadow-[var(--shadow-paper)]">
        {to && <RecipientBadge role={to} clear={() => { setTo(undefined); ref.current?.focus() }} />}
        <textarea ref={ref} value={text} rows={2} aria-label="修改这句话"
          onChange={(e) => { setText(e.target.value); look(e.target.value, e.target.selectionStart) }}
          onSelect={(e) => look(e.currentTarget.value, e.currentTarget.selectionStart)} onBlur={() => setMention(null)}
          onKeyDown={(e) => {
            const composing = e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229
            if (e.key === 'Escape') { e.preventDefault(); onCancel(); return }
            if (mention?.roles.length && !composing) {
              if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()
                const step = e.key === 'ArrowDown' ? 1 : -1
                setMention({ ...mention, index: (mention.index + step + mention.roles.length) % mention.roles.length })
                return
              }
              if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') { e.preventDefault(); pick(mention.roles[mention.index]); return }
            }
            if (e.key === 'Backspace' && to && e.currentTarget.selectionStart === 0 && e.currentTarget.selectionEnd === 0) setTo(undefined)
            else if (e.key === 'Enter' && !e.shiftKey && !composing) { e.preventDefault(); void send() }
          }}
          className="block max-h-52 min-h-[60px] w-full resize-none overflow-y-auto bg-transparent px-4 pt-3 pb-3 chat-text leading-[1.75] text-ink [field-sizing:content] focus:outline-none" />
      </div>
      <div className="mt-2 flex flex-wrap items-start justify-end gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 basis-40 text-xs leading-relaxed text-ink-3">改好了点发送：这句和后面的聊天会收起来，从这句重新回答；书里改过的不跟着退</p>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={onCancel} className="rounded-md px-2 py-1 text-[13px] text-ink-3 hover:bg-line/50 hover:text-ink">取消</button>
          <button type="button" onClick={() => void send()} disabled={!takeMention(text).text.trim() || chat.sending || chat.answering}
            className="rounded-md bg-ink px-3 py-1 text-[13px] text-paper-2 hover:bg-ink-2 disabled:cursor-not-allowed disabled:bg-line-2 disabled:text-card">发送</button>
        </div>
      </div>
    </div>
  )
}

function Composer({ chat, draft, updateDraft, clearDraft, focusKey, editing }: {
  chat: ChatControl; draft: ChatDraft; updateDraft: (change: (current: ChatDraft) => ChatDraft) => void; clearDraft: (sent: ChatDraft) => void; focusKey: number; editing: boolean
}) {
  const { text, to } = draft
  const setText = (value: string) => updateDraft(current => ({ ...current, text: value }))
  const setTo = (role?: ChatRole) => updateDraft(current => ({ ...current, to: role }))
  // 正在打「@设…」，或者点了「@ 点名」：输入框上面弹出四个人
  const [mention, setMention] = useState<Mention | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)
  const caretAt = useRef<number | null>(null)
  const recipient = chatRecipient(to, undefined, chat.quote)

  useLayoutEffect(() => {
    if (focusKey || chat.focusKey) ref.current?.focus()
  }, [focusKey, chat.focusKey])
  useLayoutEffect(() => {
    if (caretAt.current === null || !ref.current) return
    ref.current.setSelectionRange(caretAt.current, caretAt.current)
    caretAt.current = null
  })

  const look = (value: string, caret: number) => {
    const found = mentionAt(value, caret)
    setMention(found ? { ...found, index: 0 } : null)
  }
  const pick = (role: ChatRole) => {
    if (mention && mention.start >= 0) {
      // 打的「@设」从话里拿掉，换成输入框上面的名牌
      setText(text.slice(0, mention.start) + text.slice(mention.start + 1 + mention.query.length))
      caretAt.current = mention.start
    }
    setTo(role)
    setMention(null)
    ref.current?.focus()
  }
  const send = async () => {
    if (chat.answering || chat.sending || editing) return
    const taken = takeMention(text)
    const content = taken.text.trim()
    if (!content) return
    setMention(null)
    // 没发出去（返回 false）就留着原话
    if ((await chat.send(content, chatRecipient(to, taken.to, chat.quote))) === false) return
    clearDraft(draft)
  }
  const options = mention?.roles ?? []

  return (
    <div className="relative shrink-0 border-t border-line px-4 pt-3 pb-4">
      {mention && options.length > 0 && (
        <div role="listbox" aria-label="点名让谁来答" className="absolute bottom-[calc(100%-4px)] left-4 z-10 w-72 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]">
          <p className="px-2.5 pt-1 pb-1.5 text-xs text-ink-3">让谁来答 · 一次点一个</p>
          {options.map((role, i) => (
            <button key={role} type="button" role="option" aria-selected={i === mention.index}
              onMouseDown={(e) => e.preventDefault()} onClick={() => pick(role)} onMouseEnter={() => setMention({ ...mention, index: i })}
              className={clsx('flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left', i === mention.index && 'bg-subtle')}>
              <Avatar role={role} small />
              <span className="text-[14px] text-ink">{role}</span>
              <span className="ml-auto text-xs text-ink-3">{CHAT_ROLES.find((r) => r.role === role)?.duty}</span>
            </button>
          ))}
        </div>
      )}
      {chat.notice}
      {chat.quote && (
        <div className="mb-2 rounded-lg border border-line bg-subtle px-3 py-2 text-[13px] leading-relaxed" aria-label="引用原文">
          <div className="flex items-start justify-between gap-3 text-ink-3">
            <span className="min-w-0 truncate">引用 · {chat.quote.where}</span>
            <button type="button" onClick={chat.clearQuote} aria-label="取消引用" title="取消引用" className="shrink-0 rounded p-0.5 hover:bg-line/70 hover:text-ink"><X className="size-3.5" /></button>
          </div>
          <p className="mt-1 line-clamp-3 whitespace-pre-wrap break-words font-serif text-ink-2">{chat.quote.text}</p>
        </div>
      )}
      <div className="rounded-[14px] border border-line-2 bg-card transition-[border-color,box-shadow] focus-within:border-ink-3/70 focus-within:shadow-[var(--shadow-paper)]">
        {recipient && (
          <div className="px-3 pt-2.5">
            <span className={clsx('inline-flex items-center gap-1.5 rounded-full py-0.5 pr-1 pl-1 text-[13px]', ROLE_COLOR[recipient].soft, ROLE_COLOR[recipient].text)}>
              <Avatar role={recipient} small />
              问{recipient}
              {to && <button type="button" onClick={() => { setTo(undefined); ref.current?.focus() }} aria-label="不点名了" title="不点名，让编辑部自己挑人答"
                className="rounded-full p-0.5 opacity-70 hover:bg-card/70 hover:opacity-100"><X className="size-3.5" /></button>}
            </span>
          </div>
        )}
        <textarea
          ref={ref}
          value={text}
          rows={2}
          onChange={(e) => { setText(e.target.value); look(e.target.value, e.target.selectionStart) }}
          onSelect={(e) => { if (mention?.start !== -1) look(e.currentTarget.value, e.currentTarget.selectionStart) }}
          onBlur={() => setMention(null)}
          onKeyDown={(e) => {
            const composing = e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229
            if (mention && options.length && !composing) {
              if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()
                const step = e.key === 'ArrowDown' ? 1 : -1
                setMention({ ...mention, index: (mention.index + step + options.length) % options.length })
                return
              }
              if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault()
                pick(options[mention.index])
                return
              }
              if (e.key === 'Escape') {
                e.preventDefault()
                setMention(null)
                return
              }
            }
            if (e.key === 'Escape' && chat.answering) {
              e.preventDefault()
              chat.stop()
            } else if (e.key === 'Backspace' && to && e.currentTarget.selectionStart === 0 && e.currentTarget.selectionEnd === 0) {
              setTo(undefined)
            } else if (e.key === 'Enter' && !e.shiftKey && !composing) {
              e.preventDefault()
              void send()
            }
          }}
          placeholder={recipient ? `想问${recipient}什么` : chat.placeholder ?? '想改哪儿、想问什么直接说；打 @ 点名找谁'}
          aria-label="给编辑部发消息"
          className="block max-h-52 min-h-[60px] w-full resize-none bg-transparent px-4 pt-3 pb-1 chat-text leading-[1.75] text-ink [field-sizing:content] placeholder:text-ink-3 focus:outline-none"
        />
        <div className="flex items-center gap-2 px-2.5 pb-2.5">
          <button type="button" onMouseDown={(e) => e.preventDefault()}
            onClick={() => { setMention(mention ? null : { start: -1, query: '', roles: CHAT_ROLES.map((r) => r.role), index: 0 }); ref.current?.focus() }}
            title="点名让谁来答；也可以直接打 @" aria-label="点名"
            className="flex h-8 items-center gap-1 rounded-lg px-2 text-[13px] text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
            <AtSign className="size-4" />点名
          </button>
          {chat.tools}
          {chat.answering && <span className="text-xs text-ink-3">在回答 · 按「停」或 Esc 停下</span>}
          {chat.answering ? (
            <button type="button" onClick={chat.stop} aria-label="停下" title="停下（Esc），写出来的留着"
              className="press ml-auto flex size-[34px] shrink-0 items-center justify-center rounded-full bg-ink text-paper-2 transition-colors hover:bg-ink-2">
              <Square className="size-3.5 fill-current" />
            </button>
          ) : (
            <button type="button" onClick={() => void send()} disabled={!takeMention(text).text.trim() || chat.sending || editing} aria-label="发送" title={editing ? '先发出或取消上面正在改的那句' : '发送（Enter）；换行按 Shift + Enter'}
              className="press ml-auto flex size-[34px] shrink-0 items-center justify-center rounded-full bg-ink text-paper-2 transition-colors hover:bg-ink-2 disabled:cursor-not-allowed disabled:bg-line-2 disabled:text-card">
              {chat.sending ? <Spinner className="size-4" /> : <ArrowUp className="size-[18px]" />}
            </button>
          )}
        </div>
      </div>
      {chat.sendError}
      {chat.hint && <p className="mt-2 text-xs text-writer">{chat.hint}</p>}
    </div>
  )
}

export function EditorialChat({ chat }: { chat: ChatControl }) {
  const [draft, setDraft] = useState<ChatDraft>(() => loadChatDraft(chat.bookId))
  const draftRef = useRef(draft)
  useLayoutEffect(() => subscribeChatDraft(chat.bookId, next => {
    draftRef.current = next
    setDraft(next)
  }), [chat.bookId])
  const updateDraft = (change: (current: ChatDraft) => ChatDraft) => {
    const next = change(draftRef.current)
    draftRef.current = next
    setDraft(next)
    // 在输入事件里写入，收起或切换浮窗导致马上卸载时也不丢。
    saveChatDraft(chat.bookId, next)
  }
  const clearDraft = (sent: ChatDraft) => {
    if (draftRef.current !== sent || !clearSentChatDraft(chat.bookId, sent)) return
    draftRef.current = { text: '' }
    setDraft(draftRef.current)
  }
  const [focusKey, setFocusKey] = useState(0)
  const [rewinding, setRewinding] = useState<string | null>(null)
  // 只把正在修改那一句后面的聊天淡下去；原句被收起时退出修改。
  const from = rewinding ? chat.messages.findIndex((m) => m.id === rewinding) : -1
  if (rewinding && from < 0) setRewinding(null)
  const box = useRef<HTMLDivElement>(null)
  // 作者往上翻着看的时候，新冒出来的字不把他拽回底下
  const pinned = useRef(true)
  const smoothing = useRef(false)
  const scrollFrame = useRef<number | undefined>(undefined)
  useLayoutEffect(() => () => {
    if (scrollFrame.current !== undefined) cancelAnimationFrame(scrollFrame.current)
  }, [])
  const [away, setAway] = useState(false)
  const [unread, setUnread] = useState(false)
  const count = chat.messages.length
  const content = chat.messages.map(message => `${message.id}:${message.state}:${message.text}`).join('\n')
  const previousContent = useRef(content)
  useLayoutEffect(() => {
    if (content !== previousContent.current && !pinned.current) setUnread(true)
    previousContent.current = content
  }, [content])
  useLayoutEffect(() => {
    if (pinned.current && !smoothing.current && box.current) box.current.scrollTop = box.current.scrollHeight
  })
  // 作者主动发话/重答要看见这次回答；被动到来的内容仍按上翻状态处理。
  const followLatest = () => {
    if (scrollFrame.current !== undefined) cancelAnimationFrame(scrollFrame.current)
    scrollFrame.current = undefined
    smoothing.current = false
    pinned.current = true
    setAway(false)
    setUnread(false)
    if (box.current) box.current.scrollTop = box.current.scrollHeight
  }
  const authorChat: ChatControl = {
    ...chat,
    send: async (...args) => {
      if ((await chat.send(...args)) === false) return false
      followLatest()
      return true
    },
    again: (id) => { followLatest(); chat.again(id) },
  }
  const scrollLatest = () => {
    const el = box.current
    if (!el) return
    pinned.current = true
    smoothing.current = true
    setAway(false)
    setUnread(false)
    if (scrollFrame.current !== undefined) cancelAnimationFrame(scrollFrame.current)
    const start = el.scrollTop
    const began = performance.now()
    const duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 220
    const step = (now: number) => {
      if (!smoothing.current) return
      const progress = duration ? Math.min(1, (now - began) / duration) : 1
      // 流式回答仍在增高：每一帧都向最新底部走，不停在点击时的旧位置。
      el.scrollTop = start + (el.scrollHeight - el.clientHeight - start) * (1 - (1 - progress) ** 3)
      if (progress < 1) scrollFrame.current = requestAnimationFrame(step)
      else {
        smoothing.current = false
        scrollFrame.current = undefined
        el.scrollTop = el.scrollHeight
      }
    }
    scrollFrame.current = requestAnimationFrame(step)
  }
  const latest = latestReply(chat.messages)
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-pane-mid">
      {chat.banner}
      <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={box} data-testid="chat-messages" className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5"
        onWheel={() => { smoothing.current = false }}
        onTouchStart={() => { smoothing.current = false }}
        onScroll={(e) => {
          const el = e.currentTarget
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 48
          if (smoothing.current) return
          pinned.current = atBottom
          setAway(!atBottom)
          if (atBottom) setUnread(false)
        }}>
        {count === 0 && !chat.footer && <EmptyChat onPick={(role) => { updateDraft(current => ({ ...current, to: role })); setFocusKey((n) => n + 1) }} />}
        {chat.messages.map((m, i) => {
          const body = m.custom ? m.custom
            : m.who === '作者'
              ? <AuthorBubble message={m} canRewind={!chat.answering && !chat.sending && !rewinding}
                onRewind={() => setRewinding(m.id)} editing={rewinding === m.id} chat={authorChat} endRewind={() => setRewinding(null)} />
              : <Reply message={m} latest={m === latest} answering={chat.answering} onAgain={() => authorChat.again(m.id)} />
          return <div key={m.id} className={clsx('transition-opacity', from >= 0 && i > from && 'opacity-35')}>{body}</div>
        })}
        {chat.footer}
      </div>
      {away && (
        <button type="button" onClick={scrollLatest} title="回到最新" aria-label={unread ? '有新回答' : '回到最新'}
          className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-card p-2 text-[13px] text-ink-2 shadow-[var(--shadow-lift)]">
          <ArrowDown className="size-4" />{unread && <span className="pr-1">有新回答</span>}
        </button>
      )}
      </div>
      <Composer chat={authorChat} draft={draft} updateDraft={updateDraft} clearDraft={clearDraft} focusKey={focusKey} editing={!!rewinding} />
    </div>
  )
}
