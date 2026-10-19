/** 编辑部浮窗里的聊天：只有一个聊天，打 @ 点名找谁；回答边写边显示，回答时发送键变「停」；最新一条回答下面能重新回答，没答上来能重试。 */

import clsx from 'clsx'
import { AlertTriangle, ArrowUp, AtSign, ChevronDown, RotateCcw, Search, Square, X } from 'lucide-react'
import { type ReactNode, useLayoutEffect, useRef, useState } from 'react'
import { Spinner, TypingDots } from '../../components/ui'
import { CHAT_ROLES, type ChatControl, type ChatMessage, type ChatRole, latestReply, mentionAt, takeMention } from './chatModel'

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

function AuthorBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex flex-col items-end">
      <p className="max-w-[85%] rounded-[16px_4px_16px_16px] bg-author-bubble px-4 py-2.5 chat-text leading-[1.75] break-words whitespace-pre-wrap text-ink">
        {message.to && <span className={clsx('mr-1.5 font-medium', ROLE_COLOR[message.to].text)}>@{message.to}</span>}
        {message.text}
      </p>
      {message.below && <div className="max-w-[85%]">{message.below}</div>}
    </div>
  )
}

/** 回答下面一行小字「查了：陈默、第 12 章」，点开看查到的原文 */
function Looked({ items }: { items: { label: string; text: string }[] }) {
  const [open, setOpen] = useState(false)
  const labels = [...new Set(items.map((item) => item.label))]
  return (
    <div className="mt-1.5 text-xs text-ink-3">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} title="点开看查到的原文"
        className="flex max-w-full items-center gap-1 rounded-md px-1 py-0.5 text-left transition-colors hover:bg-line/50 hover:text-ink">
        <Search className="size-3.5 shrink-0" /><span className="min-w-0 truncate">查了：{labels.join('、')}</span>
        <ChevronDown className={clsx('size-3.5 shrink-0 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
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

function Reply({ message, latest, answering, onAgain }: { message: ChatMessage; latest: boolean; answering: boolean; onAgain: () => void }) {
  const role = message.who as ChatRole
  const live = message.state === 'thinking' || message.state === 'streaming'
  // 最新一条答完了、停下了：下面能重新回答；别的回答不放按钮
  const canAgain = latest && !answering && !!message.replyTo
  return (
    <div data-testid={`reply-${message.id}`} data-state={message.state ?? 'done'} className="flex gap-2.5">
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
        {!live && !!message.looked?.length && <Looked items={message.looked} />}
        {message.below}
        {message.state === 'stopped' && (
          <p className="mt-1.5 text-xs text-ink-3">{message.text ? '你让它停下了，写出来的留着' : '还没开口就停下了'}</p>
        )}
        {canAgain && (message.state === 'done' || message.state === 'stopped') && (
          <button type="button" onClick={onAgain} title="把上面你那句话重新答一遍，这一条换成新的"
            className="mt-1.5 flex items-center gap-1 rounded-md px-1 py-0.5 text-xs text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
            <RotateCcw className="size-3.5" />重新回答
          </button>
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
            <span className="text-[14px] text-ink">{role}</span>
            <span className="ml-auto text-xs text-ink-3">{duty}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

interface Mention { start: number; query: string; roles: ChatRole[]; index: number }

function Composer({ chat, to, setTo, focusKey }: { chat: ChatControl; to?: ChatRole; setTo: (role?: ChatRole) => void; focusKey: number }) {
  const [text, setText] = useState('')
  // 正在打「@设…」，或者点了「@ 点名」：输入框上面弹出四个人
  const [mention, setMention] = useState<Mention | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)
  const caretAt = useRef<number | null>(null)

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
    if (chat.answering || chat.sending) return
    const taken = takeMention(text)
    const content = taken.text.trim()
    if (!content) return
    setMention(null)
    // 没发出去（返回 false）就留着原话
    if ((await chat.send(content, to ?? taken.to)) === false) return
    setText((now) => (now === text ? '' : now))
    setTo(undefined)
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
      <div className="rounded-[14px] border border-line-2 bg-card transition-[border-color,box-shadow] focus-within:border-ink-3/70 focus-within:shadow-[var(--shadow-paper)]">
        {to && (
          <div className="px-3 pt-2.5">
            <span className={clsx('inline-flex items-center gap-1.5 rounded-full py-0.5 pr-1 pl-1 text-[13px]', ROLE_COLOR[to].soft, ROLE_COLOR[to].text)}>
              <Avatar role={to} small />
              问{to}
              <button type="button" onClick={() => { setTo(undefined); ref.current?.focus() }} aria-label="不点名了" title="不点名，让编辑部自己挑人答"
                className="rounded-full p-0.5 opacity-70 hover:bg-card/70 hover:opacity-100"><X className="size-3.5" /></button>
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
          placeholder={to ? `想问${to}什么` : chat.placeholder ?? '想改哪儿、想问什么直接说；打 @ 点名找谁'}
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
            <button type="button" onClick={() => void send()} disabled={!takeMention(text).text.trim() || chat.sending} aria-label="发送" title="发送（Enter）；换行按 Shift + Enter"
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
  const [to, setTo] = useState<ChatRole>()
  const [focusKey, setFocusKey] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  // 作者往上翻着看的时候，新冒出来的字不把他拽回底下
  const pinned = useRef(true)
  const count = chat.messages.length
  const lastCount = useRef(count)
  useLayoutEffect(() => {
    if (count > lastCount.current) pinned.current = true
    lastCount.current = count
    if (pinned.current && box.current) box.current.scrollTop = box.current.scrollHeight
  })
  const latest = latestReply(chat.messages)
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-pane-mid">
      <div ref={box} className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5"
        onScroll={(e) => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48 }}>
        {count === 0 && <EmptyChat onPick={(role) => { setTo(role); setFocusKey((n) => n + 1) }} />}
        {chat.messages.map((m) => (m.custom ? <div key={m.id}>{m.custom}</div>
          : m.who === '作者'
            ? <AuthorBubble key={m.id} message={m} />
            : <Reply key={m.id} message={m} latest={m === latest} answering={chat.answering} onAgain={() => chat.again(m.id)} />))}
      </div>
      <Composer chat={chat} to={to} setTo={setTo} focusKey={focusKey} />
    </div>
  )
}
