/** 书页的编辑部聊天（接真书）：只看群聊里正在看的那一段对话，消息换成聊天界面要的样子；发话带上点了谁、作者正在看哪一页、
 *  是哪一段对话；回答边写边推（chat_delta），「停」「重新回答」走后台；作者的话能「从这里重来」（只退聊天）。
 *  编辑部干活的进度压成一行：正在做的只在最底下留一行跟着变；做完的一行小字带「去看」；等拍板的一行「……等你看 · 去看」；
 *  大块产出只放在页面上。 */

import { AlertTriangle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { post } from '../../api/client'
import type { ChatOutcome, Job, MeetingMessage, Outline, TeamRole } from '../../api/types'
import { ErrorText } from '../../components/ui'
import { sendChatFirst } from '../../lib/chat'
import { pendingTarget } from '../../lib/workspace'
import { useBookContext } from '../book/context'
import { PlanSubmitted, StepOutcomes } from '../book/MeetingFeed'
import { PlanCard } from '../book/PlanCard'
import { useGroupFeedback } from '../book/useGroupFeedback'
import { EditorialChat, RoleRow } from './Chat'
import { convOf, dayLabel, useCurrentConv } from './convs'
import { chatRecipient, clearSentQuote, type ChatControl, type ChatMessage, type ChatRole } from './chatModel'
import { gateTarget, type WritingControl } from './writing'

const NAME: Record<TeamRole, ChatRole> = { chief: '主编', lorekeeper: '设定师', writer: '写手', reviewer: '审稿' }
const CODE = Object.fromEntries(Object.entries(NAME).map(([code, name]) => [name, code])) as Record<ChatRole, TeamRole>
const isRole = (speaker: string): speaker is TeamRole => speaker in NAME
const live = (m: MeetingMessage) => m.payload?.state === 'thinking' || m.payload?.state === 'streaming'

/** 一行小字最多这么长：主编干活时说的一大段只留开头，鼠标移上去看全文；大块的东西在页面上 */
const LINE_LIMIT = 80

/** 编辑部干活做完的一件、系统的话：小字一行，能去看的带「去看」 */
function Line({ children, onGo, full }: { children: string; onGo?: () => void; full?: boolean }) {
  // 系统的话（换回了存档……）照全文
  const long = !full && children.length > LINE_LIMIT
  return (
    <p className="py-0.5 text-center text-xs leading-relaxed text-ink-3" title={long ? children : undefined}>
      {long ? `${children.slice(0, LINE_LIMIT)}……` : children}
      {onGo && <> · <button type="button" onClick={onGo} className="text-chief hover:underline">去看</button></>}
    </p>
  )
}

/** 打开书里的某一处 */
type Go = (type: string, id: string) => void

/** 做完了要留一行的产出；别的（备资料、初稿、审稿、比稿、回顾……）只是过程，不占聊天 */
const DONE_OUTPUTS = new Set(['chapter_final', 'chapter_plan', 'volume_plan', 'segment_volumes', 'segment_plan', 'concept', 'settings_focus', 'settings_rest', 'outline', 'segment', 'spine', 'pitches'])

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

/** 编辑部的一件产出在新书页上哪一处：去看 */
function outputTarget(m: MeetingMessage, outline: Outline | undefined, go: Go | undefined): (() => void) | undefined {
  if (!go) return undefined
  const data = record(m.payload?.data)
  const type = m.payload?.type
  const volumeAt = (n: unknown) => outline?.volumes.find((v) => v.index === Number(n))
  if (type === 'chapter_final') return data.index ? () => go('manuscript', `c${Number(data.index)}`) : undefined
  if (type === 'chapter_plan') {
    // 「第1卷第2单元「药铺试手」」：按名字找单元，找不到就去那一卷
    const named = String(data.unit ?? '')
    const title = /「([^」]*)」/.exec(named)?.[1]
    const unit = outline?.volumes.flatMap((v) => v.units).find((u) => u.id === data.unit_id || (title && u.title === title))
    if (unit) return () => go('unit', unit.id)
    const volume = volumeAt(/第\s*(\d+)\s*卷/.exec(named)?.[1])
    return volume ? () => go('volume', volume.id) : undefined
  }
  if (type === 'volume_plan') {
    const volume = volumeAt(data.volume ?? data.index ?? /第\s*(\d+)\s*卷/.exec(m.content)?.[1])
    return volume ? () => go('volume', volume.id) : undefined
  }
  if (type === 'segment_volumes') {
    const first = record(Array.isArray(data.volumes) ? data.volumes[0] : undefined)
    const volume = volumeAt(first.index)
    return volume ? () => go('volume', volume.id) : () => go('book', '')
  }
  if (type === 'concept') return () => go('concept', '')
  if (['outline', 'segment', 'segment_plan', 'spine'].includes(type ?? '')) return () => go('book', '')
  return undefined
}

/** 这句话照办时改了书的几处（换回了的不算） */
const CHANGED = new Set(['edit', 'fill', 'created', 'outline', 'requirement', 'deleted'])
function changedPlaces(m: MeetingMessage): number {
  const list: ChatOutcome[] = m.kind === 'plan' ? m.payload?.results ?? [] : m.payload?.steps ?? (m.payload?.outcome ? [m.payload.outcome] : [])
  return list.filter((o) => CHANGED.has(o.kind) && !o.undone && !(o.kind === 'edit' && o.mode === 'options') && !(o.kind === 'fill' && !o.filled?.length)).length
}

function toChat(messages: MeetingMessage[], outline: Outline | undefined, go: Go | undefined): ChatMessage[] {
  const out: ChatMessage[] = []
  // 从后往前数：这句和后面的话一共改过书几处（从这里重来时提醒书不跟着退）
  const changedFrom = new Map<number, number>()
  let changed = 0
  for (const m of [...messages].reverse()) {
    changed += m.speaker === 'author' || m.kind === 'plan' ? changedPlaces(m) : 0
    changedFrom.set(m.id, changed)
  }
  // 上一行是编辑部干活时主编说的一句：紧跟着的产出并进这一行，只多一个「去看」
  let chiefLine: { job: string; index: number } | null = null
  let authorLine: { job: string; index: number } | null = null
  for (const m of messages) {
    const id = String(m.id)
    if (m.job_id && m.kind !== 'error' && !(m.speaker === 'author' && m.kind === 'decision' && m.content.startsWith('【和作者商量定的方案'))) {
      // 编辑部干活：进度不占聊天（最底下那一行跟着变），做完的、交代的一行小字
      if (m.kind === 'status') continue
      if (m.kind === 'artifact') {
        if (!DONE_OUTPUTS.has(m.payload?.type ?? '')) continue
        const onGo = outputTarget(m, outline, go)
        if (chiefLine?.job === m.job_id && chiefLine.index === out.length - 1) {
          const line = out[chiefLine.index]
          out[chiefLine.index] = { ...line, custom: <Line onGo={onGo}>{line.text}</Line> }
          chiefLine = null
          continue
        }
        const text = m.content
        out.push({ id: `line:${id}`, who: '主编', text, custom: <Line onGo={onGo}>{text}</Line> })
        continue
      }
      if (m.speaker === 'author') {
        const text = `你：${m.content}`
        out.push({ id: `line:${id}`, who: '主编', text, custom: <Line>{text}</Line> })
        authorLine = { job: m.job_id, index: out.length - 1 }
        continue
      }
      // 紧跟着作者那一行、复述作者决定的系统那句（「作者决定第 9 章就按现在的版本定稿」）不重复
      if (m.speaker === 'system' && m.kind === 'decision' && authorLine?.job === m.job_id && authorLine.index === out.length - 1) continue
      // 设定师记变化、审稿的意见、写手的交代：过程，不占聊天（审稿意见在正文那一页）
      if (m.kind === 'speech' && m.speaker !== 'chief') continue
      out.push({ id: `line:${id}`, who: '主编', text: m.content, custom: <Line>{m.content}</Line> })
      chiefLine = m.kind === 'speech' ? { job: m.job_id, index: out.length - 1 } : null
      continue
    }
    chiefLine = null
    if (m.kind === 'status' || m.kind === 'artifact' || (m.kind === 'decision' && m.speaker !== 'author')) {
      const text = m.kind === 'artifact' ? `${m.speaker_name}交了「${m.content}」` : m.content
      out.push({ id: `line:${id}`, who: '主编', text, custom: <Line full>{text}</Line> })
    } else if (m.kind === 'error') {
      out.push({
        id, who: '主编', text: m.content,
        custom: (
          <div className="flex gap-2 rounded-lg border border-seal/30 bg-seal-soft px-3 py-2 text-[13px] text-seal-dark">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" /><span className="break-words">{m.content}</span>
          </div>
        ),
      })
    } else if (m.speaker === 'author') {
      if (m.kind === 'decision' && m.content.startsWith('【和作者商量定的方案')) {
        out.push({ id, who: '作者', text: m.content, custom: <div className="flex flex-col items-end"><PlanSubmitted text={m.content} /></div> })
        continue
      }
      const ask = m.payload?.ask
      const n = changedFrom.get(m.id) ?? 0
      out.push({
        id, who: '作者', text: m.content, to: ask ? NAME[ask] : undefined, below: <StepOutcomes message={m} />,
        // 作者在聊天里说的话能从这里重来；这句和后面的话改过书，先提醒书不跟着退
        rewind: m.kind === 'note' && m.payload?.conv
          ? { warn: n ? `这句和后面的话改过书（${n} 处）。改了重发，聊天退回这里，书不跟着退：要退书，用那几处下面的「换回原来的」，或者去「存档」。` : undefined }
          : undefined,
      })
    } else if (isRole(m.speaker) && m.kind === 'plan') {
      out.push({ id, who: NAME[m.speaker], text: m.content, custom: <RoleRow role={NAME[m.speaker]}><PlanCard message={m} /></RoleRow> })
    } else if (isRole(m.speaker)) {
      const asked = m.payload?.reply_to
      out.push({
        id, who: NAME[m.speaker], text: m.content,
        // 照作者的话答的才能重新回答；编辑部干活时说的话、改完设定报的一句不能
        replyTo: asked?.length ? String(asked[0]) : undefined,
        state: m.payload?.state ?? 'done', error: m.payload?.error,
        // 自己查、自己动手的回答：干活时那一行，答完下面「查了：……」
        doing: m.payload?.doing,
        looked: m.payload?.tools?.filter((t) => t.kind === 'query'),
      })
    } else if (m.content) {
      out.push({ id: `line:${id}`, who: '主编', text: m.content, custom: <Line full>{m.content}</Line> })
    }
  }
  return out
}

function elapsed(since: string | null | undefined, now: number): string {
  if (!since) return ''
  const seconds = Math.max(0, Math.round((now - Date.parse(since)) / 1000))
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分钟`
}

/** 聊天最底下一行：编辑部正在做什么（跟着变，做完消失），或者什么等你看 */
function WorkNow({ job, messages, writing, go, bookId }: {
  job: Job; messages: MeetingMessage[]; writing?: WritingControl; go?: Go; bookId: string
}) {
  const running = job?.status === 'queued' || job?.status === 'running'
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  const row = 'flex items-center justify-center gap-2 py-1 text-xs leading-relaxed'
  if (running) {
    const step = messages.findLast((m) => m.job_id === job.id && m.kind === 'status')
    const doing = writing?.status.state === 'working' && writing.status.doing
      ? writing.status.doing
      : step?.content.replace(/[.…]+$/, '') ?? (job.status === 'queued' ? '排队中，马上开始' : '编辑部在干活')
    const since = elapsed(step?.created_at ?? job.updated_at, now)
    return (
      <p data-testid="work-now" className={`${row} text-chief`}>
        <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-chief motion-safe:animate-pulse" />
        <span className="min-w-0 truncate">{doing}{since && ` · 已用 ${since}`}</span>
      </p>
    )
  }
  if (job.status !== 'waiting_author') return null
  // 等拍板：新书页上有拍板卡的直接打开那一页，开书这些还在旧版的去旧版
  const gate = writing?.status.state === 'waiting' ? writing.status.gate : undefined
  let label = gate?.title
  let onGo: (() => void) | undefined
  if (gate && go) {
    const at = gateTarget(gate)
    const volume = at.node?.startsWith('v:') ? at.node.slice(2) : undefined
    const unit = at.node?.startsWith('u:') ? at.node.slice(2) : undefined
    onGo = at.chapter ? () => go('manuscript', at.chapter!) : volume ? () => go('volume', volume) : unit ? () => go('unit', unit) : () => go('node', at.node ?? 'book')
  } else {
    // 以前的开书流程停在半路：新书页上没有它的拍板卡，顶栏下面那一行能停下开书
    label = pendingTarget(job.pending, bookId)?.label
  }
  return (
    <p data-testid="work-now" className={`${row} text-seal-dark`}>
      <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-seal" />
      <span className="min-w-0 truncate">{label ?? '编辑部'}等你看</span>
      {onGo && <> · <button type="button" onClick={onGo} className="font-medium hover:underline">去看</button></>}
    </p>
  )
}

export function LiveChat({ writing }: { writing?: WritingControl }) {
  const { bookId, book, messages, job, waiting, working, viewing, focusComposer, openTarget, outline, setChatConv, chatQuotes, setChatQuotes } = useBookContext()
  const quote = book.source === 'teardown' ? chatQuotes.chief ?? undefined : undefined
  // 只清掉这次发送的引用；请求在途时新选的一句留给下一问。
  const clearQuote = () => setChatQuotes(current => clearSentQuote(current, quote))
  const feedback = useGroupFeedback()
  const { conv, latest, convs } = useCurrentConv()
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  // 只看正在看的那一段；「从这里重来」收起来的不显示
  const shown = useMemo(() => messages.filter((m) => !m.payload?.thread && !m.payload?.dropped && convOf(m, latest) === conv), [messages, conv, latest])
  const chatMessages = useMemo(() => toChat(shown, outline, openTarget), [shown, outline, openTarget])
  const current = shown.findLast(live)

  const run = async (request: () => Promise<unknown>) => {
    setError(null)
    try {
      await request()
      return true
    } catch (cause) {
      setError(cause)
      return false
    }
  }
  const target = waiting ? pendingTarget(job?.pending, bookId) : null
  const old = conv && latest && conv !== latest ? convs?.find((c) => c.id === conv) : undefined
  const control: ChatControl = {
    bookId,
    messages: chatMessages,
    answering: !!current,
    sending,
    quote,
    clearQuote: quote ? clearQuote : undefined,
    send: async (content, to, rewindFrom) => {
      setSending(true)
      try {
        // 原地修改只重发那句话；底下尚未发送的新引用留给下一问。
        const sentQuote = rewindFrom ? undefined : quote
        const recipient = chatRecipient(to, undefined, sentQuote)
        const sent = await run(() => sendChatFirst(
          () => {
            // 带上作者正在看的那一页：说「帮我写这一篇」就写这一页
            const seeing = viewing?.() ?? null
            return post<MeetingMessage>(`/books/${bookId}/notes`, {
              content, ...(recipient ? { ask: CODE[recipient] } : {}), ...(sentQuote ? { quote: sentQuote } : {}), ...(seeing ? { viewing: seeing } : {}),
              ...(conv ? { conv } : {}), ...(rewindFrom ? { rewind_from: Number(rewindFrom) } : {}),
            })
          },
          () => feedback(content), false))
        if (sent && sentQuote) setChatQuotes(current => clearSentQuote(current, sentQuote))
        return sent
      } finally {
        setSending(false)
      }
    },
    stop: () => { if (current) void run(() => post(`/books/${bookId}/chat/replies/${current.id}/stop`)) },
    again: (id) => { void run(() => post(`/books/${bookId}/chat/replies/${id}/again`)) },
    notice: waiting ? (
      <p className="mb-2 rounded-lg bg-seal-soft px-3 py-2 text-[13px] leading-relaxed text-seal-dark">
        编辑部在等你拍板{target ? `「${target.label}」` : ''} · 现在说要改，会当成修改意见
      </p>
    ) : undefined,
    banner: old ? (
      <div className="flex shrink-0 items-center gap-2 border-b border-line bg-subtle px-4 py-1.5 text-xs text-ink-3">
        <span className="min-w-0 flex-1 truncate">以前的对话「{old.title || '新对话'}」· {dayLabel(old.last_at)} · {old.archived ? '归档了，接着说就取消归档' : '接着说就在这一段里聊'}</span>
        <button type="button" onClick={() => setChatConv?.(null)} className="shrink-0 text-chief hover:underline">回到最近的</button>
      </div>
    ) : undefined,
    footer: job && ['queued', 'running', 'waiting_author'].includes(job.status)
      ? <WorkNow job={job} messages={messages} writing={writing} go={openTarget} bookId={bookId} />
      : undefined,
    placeholder: working ? '插句话或者问一句都行，例如：从下一章开始节奏快一点；打 @ 点名找谁' : undefined,
    sendError: <ErrorText error={error} />,
    focusKey: focusComposer,
  }
  return <EditorialChat key={`${bookId}:${conv}`} chat={control} />
}
