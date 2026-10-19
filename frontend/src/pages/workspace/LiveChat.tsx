/** 新书页的编辑部聊天（接真书）：只看群聊，消息换成聊天界面要的样子；发话带上点了谁、作者正在看哪一页；
 *  回答边写边推（chat_delta），「停」「重新回答」走后台。旧版书页的私聊还在旧版里。 */

import { AlertTriangle, ListChecks } from 'lucide-react'
import { useMemo, useState } from 'react'
import { post } from '../../api/client'
import type { MeetingMessage, TeamRole } from '../../api/types'
import { ErrorText } from '../../components/ui'
import { sendChatFirst } from '../../lib/chat'
import { pendingTarget } from '../../lib/workspace'
import { useBookContext } from '../book/context'
import { PlanSubmitted, StepOutcomes } from '../book/MeetingFeed'
import { PlanCard } from '../book/PlanCard'
import { useGroupFeedback } from '../book/useGroupFeedback'
import { EditorialChat, RoleRow } from './Chat'
import type { ChatControl, ChatMessage, ChatRole } from './chatModel'

const NAME: Record<TeamRole, ChatRole> = { chief: '主编', lorekeeper: '设定师', writer: '写手', reviewer: '审稿' }
const CODE = Object.fromEntries(Object.entries(NAME).map(([code, name]) => [name, code])) as Record<ChatRole, TeamRole>
const isRole = (speaker: string): speaker is TeamRole => speaker in NAME
const live = (m: MeetingMessage) => m.payload?.state === 'thinking' || m.payload?.state === 'streaming'

/** 编辑部干活时报的一句（在分卷、写完了第几章……）：小字一行 */
function Line({ children }: { children: string }) {
  return <p className="py-0.5 text-center text-xs leading-relaxed text-ink-3">{children}</p>
}

function toChat(messages: MeetingMessage[]): ChatMessage[] {
  const out: ChatMessage[] = []
  for (const m of messages) {
    if (m.payload?.thread) continue
    const id = String(m.id)
    if (m.kind === 'status' || m.kind === 'artifact' || (m.kind === 'decision' && m.speaker !== 'author')) {
      const text = m.kind === 'artifact' ? `${m.speaker_name}交了「${m.content}」` : m.content
      // 连着的几句进度只留最新的一句
      if (out.at(-1)?.id.startsWith('line:') && m.kind === 'status') out.pop()
      out.push({ id: `line:${id}`, who: '主编', text, custom: <Line>{text}</Line> })
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
      out.push({ id, who: '作者', text: m.content, to: ask ? NAME[ask] : undefined, below: <StepOutcomes message={m} /> })
    } else if (isRole(m.speaker) && m.kind === 'plan') {
      out.push({ id, who: NAME[m.speaker], text: m.content, custom: <RoleRow role={NAME[m.speaker]}><PlanCard message={m} /></RoleRow> })
    } else if (isRole(m.speaker)) {
      const asked = m.payload?.reply_to
      out.push({
        id, who: NAME[m.speaker], text: m.content,
        // 照作者的话答的才能重新回答；编辑部干活时说的话、改完设定报的一句不能
        replyTo: asked?.length ? String(asked[0]) : undefined,
        state: m.payload?.state ?? 'done', error: m.payload?.error,
      })
    } else if (m.content) {
      out.push({ id: `line:${id}`, who: '主编', text: m.content, custom: <Line>{m.content}</Line> })
    }
  }
  return out
}

export function LiveChat() {
  const { bookId, messages, job, waiting, working, viewing, focusComposer } = useBookContext()
  const feedback = useGroupFeedback()
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const chatMessages = useMemo(() => toChat(messages), [messages])
  const current = messages.findLast((m) => !m.payload?.thread && live(m))

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
  const control: ChatControl = {
    messages: chatMessages,
    answering: !!current,
    sending,
    send: async (content, to) => {
      setSending(true)
      try {
        return await run(() => sendChatFirst(
          () => {
            // 带上作者正在看的那一页：说「帮我写这一篇」就写这一页
            const seeing = viewing?.() ?? null
            return post<MeetingMessage>(`/books/${bookId}/notes`, { content, ...(to ? { ask: CODE[to] } : {}), ...(seeing ? { viewing: seeing } : {}) })
          },
          () => feedback(content), false))
      } finally {
        setSending(false)
      }
    },
    stop: () => { if (current) void run(() => post(`/books/${bookId}/chat/replies/${current.id}/stop`)) },
    again: (id) => { void run(() => post(`/books/${bookId}/chat/replies/${id}/again`)) },
    tools: (
      <button type="button" disabled={sending} title="把前面聊的整理成一张方案卡，看过再决定要不要照办"
        onClick={() => void run(() => post(`/books/${bookId}/notes`, { content: '总结一下前面聊的' }))}
        className="flex h-8 items-center gap-1 rounded-lg px-2 text-[13px] text-ink-3 transition-colors hover:bg-line/50 hover:text-ink disabled:opacity-50">
        <ListChecks className="size-4" />总结一下
      </button>
    ),
    notice: waiting ? (
      <p className="mb-2 rounded-lg bg-seal-soft px-3 py-2 text-[13px] leading-relaxed text-seal-dark">
        编辑部在等你拍板{target ? `「${target.label}」` : ''} · 现在说要改，会当成修改意见
      </p>
    ) : undefined,
    placeholder: working ? '插句话或者问一句都行，例如：从下一章开始节奏快一点；打 @ 点名找谁' : undefined,
    sendError: <ErrorText error={error} />,
    focusKey: focusComposer,
  }
  return <EditorialChat chat={control} />
}
