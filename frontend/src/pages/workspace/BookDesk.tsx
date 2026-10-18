/** 新书页：接真书。编辑部浮窗里先放现有的聊天，拍板、正文这些还没搬过来的先去旧版。 */

import { useIsMutating } from '@tanstack/react-query'
import { Settings } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useBook, useJobActions, useOutline } from '../../api/hooks'
import type { BookDetail, Conversation } from '../../api/types'
import { EmptyState } from '../../components/ui'
import type { ChatQuote } from '../../lib/chat'
import { useMeeting } from '../../lib/useMeeting'
import { useConversationReads } from '../../lib/useWorkspacePanels'
import { currentTarget, type NodeFeedback, nodeFeedback } from '../../lib/workspace'
import { segmentReviewKey } from '../../lib/outlineWriting'
import { BookContext, type BookContextValue, type PitchChoice } from '../book/context'
import { ConversationPanel } from '../book/ConversationPanel'
import { useLiveBook } from './liveActions'
import { InboxButton, Workspace } from './Workspace'

/** 现有聊天要的那一套状态：和旧版书页一样，只是不跟着编辑部跳页面。 */
function useEditorial(bookId: string, book: BookDetail, onOpen: () => void): { ctx: BookContextValue; unread: number } {
  const navigate = useNavigate()
  const { messages, connected, draft, typing: chatTyping } = useMeeting(bookId)
  const { data: outline } = useOutline(bookId)
  const { segment, segmentPending } = useJobActions(bookId)
  const [conversation, setConversationState] = useState<Conversation>('group')
  const [focusComposer, setFocusComposer] = useState(0)
  const [composerNode, setComposerNode] = useState<NodeFeedback | null>(null)
  const [chatQuotes, setChatQuotes] = useState<Record<string, ChatQuote | null>>({})
  const [composerDrafts, setComposerDrafts] = useState<Record<string, string>>({})
  const [pitchChoice, setPitchChoice] = useState<PitchChoice | null>(null)
  const [segmentPin, setSegmentPin] = useState({ key: '', selected: false })
  const job = book.active_job
  const expanding = useIsMutating({ mutationKey: ['outline-expand', bookId] }) > 0
  const working = expanding || job?.status === 'queued' || job?.status === 'running'
  const asking = job?.status === 'waiting_author' && job.pending?.kind === 'setup_questions'
  const waiting = job?.status === 'waiting_author' && !asking
  const segmentKey = segmentReviewKey(job?.id, job?.status === 'waiting_author' ? job.pending : null)
  const segmentPinEnd = !!segmentKey && segmentPin.key === segmentKey && segmentPin.selected
  const followTarget = useMemo(() => currentTarget(bookId, job, messages, draft, outline), [bookId, job, messages, draft, outline])
  const unread = useConversationReads(bookId, messages, conversation, true)
  const setConversation = useCallback((next: Conversation) => { setConversationState(next); onOpen() }, [onOpen])
  const ctx: BookContextValue = {
    bookId, book, job, messages, connected, chatTyping, chatQuotes, setChatQuotes, draft, working, waiting, asking, outline, conversation, setConversation, unread,
    askChief: (quote) => { setChatQuotes((previous) => ({ ...previous, chief: quote })); setConversation('chief'); setFocusComposer((n) => n + 1) },
    following: false, followTarget, resumeFollow: () => undefined,
    // 聊天里点到书稿的地方：新书页还没有的，先去旧版
    manualNavigate: (path) => { void navigate(path) },
    focusComposer, focusChat: () => { onOpen(); setFocusComposer((n) => n + 1) },
    requestFeedback: () => { setConversation('group'); setFocusComposer((n) => n + 1) },
    requestNodeFeedback: (node) => {
      const selection = nodeFeedback(node)
      setComposerNode(selection)
      setComposerDrafts((previous) => ({ ...previous, group: `${selection.prefix}${(previous.group ?? '').replace(/^关于节点 \d+「[^」]*」：/, '')}` }))
      setConversation('group')
      setFocusComposer((n) => n + 1)
    },
    composerNode, setComposerNode, composerDrafts, setComposerDrafts,
    celebrate: () => undefined,
    pitchChoice, setPitchChoice,
    segmentPinEnd, setSegmentPinEnd: (selected) => setSegmentPin({ key: segmentKey, selected }),
    segmentReview: {
      submitting: segmentPending,
      action: segment.variables?.action,
      error: segment.error,
      submit: async (body) => {
        if (!job || !segmentKey || segmentPending) return false
        await segment.mutateAsync({ jobId: job.id, ...body, ...(['confirm', 'delegate'].includes(body.action) ? { pin_end: segmentPinEnd } : {}) })
        setSegmentPin({ key: '', selected: false })
        return true
      },
    },
  }
  return { ctx, unread: Object.values(unread).reduce((sum, n) => sum + n, 0) }
}

/** 编辑部在干活或在等拍板：新书页还改不了，说一声。 */
function JobNotice({ book }: { book: BookDetail }) {
  const job = book.active_job
  if (!job || !['queued', 'running', 'waiting_author', 'failed'].includes(job.status)) return null
  const text = job.status === 'waiting_author'
    ? '编辑部在等你拍板。新书页还没有拍板的地方，先去旧版处理；处理完之前这里改不了。'
    : job.status === 'failed'
      ? '编辑部上一次干活没做完，停在半路。去旧版看看怎么处理。'
      : '编辑部正在干活，这时候书里的东西先改不了，等它停下。'
  return (
    <div className="flex shrink-0 items-center justify-center gap-3 border-b border-line bg-seal-soft/60 px-4 py-2 text-[13px] text-seal-dark">
      {text}
      <Link to={`/books/${book.id}`} className="font-medium underline-offset-2 hover:underline">去旧版</Link>
    </div>
  )
}

function Desk({ bookId, detail }: { bookId: string; detail: BookDetail }) {
  const { book, actions, loading, error, raw } = useLiveBook(bookId)
  const [openChat, setOpenChat] = useState(0)
  const onOpen = useCallback(() => setOpenChat((n) => n + 1), [])
  const { ctx, unread } = useEditorial(bookId, detail, onOpen)
  if (loading) return <div className="flex h-dvh items-center justify-center bg-paper text-[15px] text-ink-3">正在读这本书…</div>
  if (error || !book) return <EmptyState title="这本书没读出来"><Link to="/" className="text-seal underline">回到书房</Link></EmptyState>
  const right = (
    <>
      <InboxButton count={book.pending}>
        <div className="px-3 py-2.5">
          <p className="text-[13px] leading-relaxed text-ink">编辑部挂着 {book.pending} 条建议。新书页还没做处理建议的地方，先去旧版的设定库里看。</p>
          <Link to={`/books/${bookId}/library`} className="mt-1.5 inline-block text-xs text-chief hover:underline">去旧版处理</Link>
        </div>
      </InboxButton>
      <Link to={`/books/${bookId}/concept`} title="还没搬过来的功能，先在旧版里用" className="rounded-lg px-2.5 py-1.5 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">回旧版</Link>
      <Link to={`/books/${bookId}/settings`} className="rounded-lg p-2 text-ink-3 transition-colors hover:bg-line/50 hover:text-ink" aria-label="本书设置" title="本书设置">
        <Settings className="size-4" />
      </Link>
    </>
  )
  return (
    <BookContext.Provider value={ctx}>
      <Workspace book={book} actions={actions} right={right} notice={<JobNotice book={detail} />}
        chat={<div className="@container/chat flex min-h-0 flex-1 bg-pane-mid"><ConversationPanel /></div>}
        chatBadge={unread} openChat={openChat}
        manuscriptHref={raw?.chapters.length ? `/books/${bookId}/chapters` : undefined} />
    </BookContext.Provider>
  )
}

export function BookDesk() {
  const { bookId = '' } = useParams()
  const detail = useBook(bookId)
  if (detail.isPending) return <div className="flex h-dvh items-center justify-center bg-paper text-[15px] text-ink-3">正在读这本书…</div>
  if (detail.error || !detail.data) return <EmptyState title="找不到这本书"><Link to="/" className="text-seal underline">回到书房</Link></EmptyState>
  return <Desk key={bookId} bookId={bookId} detail={detail.data} />
}
