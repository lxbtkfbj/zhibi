/** 新书页：接真书。编辑部浮窗里只有一个聊天（第五步：@ 点名、边写边显示、停、重新回答、新对话、从这里重来）；开写、正文、拍板在新书页上；
 *  顶栏「存档」是整本书的存档（第五步第二批），「待处理」是编辑部等你定的建议（第四步第二批），都在右边一栏。 */

import { useIsMutating } from '@tanstack/react-query'
import { Settings } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useBook, useJobActions, useOutline } from '../../api/hooks'
import { useLibrarySuggestions } from '../../api/library'
import type { BookDetail, ChatViewing, Conversation, LiveDraft, MeetingMessage } from '../../api/types'
import { EmptyState } from '../../components/ui'
import type { ChatQuote } from '../../lib/chat'
import { useMeeting } from '../../lib/useMeeting'
import { useConversationReads } from '../../lib/useWorkspacePanels'
import { currentTarget, type NodeFeedback, nodeFeedback } from '../../lib/workspace'
import { segmentReviewKey } from '../../lib/outlineWriting'
import { BookContext, type BookContextValue, type PitchChoice } from '../book/context'
import { ChatConvs } from './ChatConvs'
import { LiveChat } from './LiveChat'
import { flushAutoSave, useLiveBook } from './liveActions'
import { SavesButton, SavesPanel } from './Saves'
import { useLiveWriting } from './liveWriting'
import { PendingButton, PendingPanel } from './Inbox'
import { PendingContext, pendingTarget } from './pending'
import { Workspace } from './Workspace'

/** 现有聊天要的那一套状态：和旧版书页一样，只是不跟着编辑部跳页面。 */
function useEditorial(bookId: string, book: BookDetail, onOpen: () => void): { ctx: BookContextValue; unread: number; messages: MeetingMessage[]; draft: LiveDraft | null } {
  const navigate = useNavigate()
  const { messages, connected, draft, typing: chatTyping } = useMeeting(bookId)
  const { data: outline } = useOutline(bookId)
  const { segment, segmentPending } = useJobActions(bookId)
  const [conversation, setConversationState] = useState<Conversation>('group')
  // 群聊正在看哪一段对话：打开时是最近聊的那一段
  const [chatConv, setChatConv] = useState<string | null>(null)
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
    bookId, book, job, messages, connected, chatTyping, chatQuotes, setChatQuotes, draft, working, waiting, asking, outline, conversation, setConversation, unread, chatConv, setChatConv,
    askChief: (quote) => { setChatQuotes((previous) => ({ ...previous, chief: quote })); setConversation('chief'); setFocusComposer((n) => n + 1) },
    following: false, followTarget, resumeFollow: () => undefined,
    // 聊天里点到书稿的地方：新书页还没有的，先去旧版
    manualNavigate: (path) => { void navigate(path) },
    focusComposer, focusChat: () => { onOpen(); setFocusComposer((n) => n + 1) }, showChat: onOpen,
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
  return { ctx, unread: Object.values(unread).reduce((sum, n) => sum + n, 0), messages, draft }
}

/** 开书这类还没搬到新书页的活在干、在等拍板：说一声，指去旧版。写书的活顶栏下面有写作条，不用这一条。 */
function JobNotice({ book }: { book: BookDetail }) {
  const job = book.active_job
  if (!job || ['write_book', 'rewrite_chapter'].includes(job.kind) || !['queued', 'running', 'waiting_author', 'failed'].includes(job.status)) return null
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
  const { ctx, unread, messages, draft } = useEditorial(bookId, detail, onOpen)
  const writing = useLiveWriting({ bookId, detail, parts: raw, messages, draft })
  const openRef = useRef<((type: string, id: string) => void) | null>(null)
  const viewingRef = useRef<(() => ChatViewing | null) | null>(null)
  // 存档那一栏：开没开、点开的是哪一档
  const [saves, setSavesState] = useState<{ open: boolean; id: number | null }>({ open: false, id: null })
  // 待处理那一栏：开没开、要找到挂在哪一条上的建议；和存档那一栏同一个位置，开一个就关另一个
  const [pending, setPendingState] = useState<{ open: boolean; focus: string | null }>({ open: false, focus: null })
  const setSaves = useCallback((next: { open: boolean; id: number | null }) => {
    setSavesState(next)
    if (next.open) setPendingState({ open: false, focus: null })
  }, [])
  const setPending = useCallback((next: { open: boolean; focus: string | null }) => {
    setPendingState(next)
    if (next.open) setSavesState({ open: false, id: null })
  }, [])
  const closeSaves = useCallback(() => setSaves({ open: false, id: null }), [setSaves])
  const closePending = useCallback(() => setPending({ open: false, focus: null }), [setPending])
  const suggestions = useLibrarySuggestions(bookId)
  const notes = useMemo(() => {
    const counts = new Map<string, number>()
    for (const s of suggestions.data ?? []) {
      const at = pendingTarget(s)?.id
      if (at) counts.set(at, (counts.get(at) ?? 0) + 1)
    }
    return { count: (id: string) => counts.get(id) ?? 0, open: (id?: string) => setPending({ open: true, focus: id ?? null }) }
  }, [suggestions.data, setPending])
  const context = useMemo(() => ({
    ...ctx,
    openTarget: (type: string, id: string) => openRef.current?.(type, id),
    viewing: () => viewingRef.current?.() ?? null,
    openSaves: (id?: number) => setSaves({ open: true, id: id ?? null }),
  }), [ctx, setSaves])
  // 关页面、切到别的页面时：手改了还没存的，存一档
  useEffect(() => {
    const leave = () => flushAutoSave(bookId, true)
    const hidden = () => { if (document.visibilityState === 'hidden') flushAutoSave(bookId, true) }
    window.addEventListener('pagehide', leave)
    document.addEventListener('visibilitychange', hidden)
    return () => {
      window.removeEventListener('pagehide', leave)
      document.removeEventListener('visibilitychange', hidden)
      flushAutoSave(bookId)
    }
  }, [bookId])
  if (loading) return <div className="flex h-dvh items-center justify-center bg-paper text-[15px] text-ink-3">正在读这本书…</div>
  if (error || !book) return <EmptyState title="这本书没读出来"><Link to="/" className="text-seal underline">回到书房</Link></EmptyState>
  const right = (
    <>
      <SavesButton open={saves.open} onClick={() => setSaves(saves.open ? { open: false, id: null } : { open: true, id: null })} />
      <PendingButton count={suggestions.data?.length ?? book.pending} open={pending.open} onClick={() => setPending(pending.open ? { open: false, focus: null } : { open: true, focus: null })} />
      <Link to={`/books/${bookId}/concept`} title="还没搬过来的功能，先在旧版里用" className="rounded-lg px-2.5 py-1.5 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">回旧版</Link>
      <Link to={`/books/${bookId}/settings`} className="rounded-lg p-2 text-ink-3 transition-colors hover:bg-line/50 hover:text-ink" aria-label="本书设置" title="本书设置">
        <Settings className="size-4" />
      </Link>
    </>
  )
  return (
    <BookContext.Provider value={context}>
      <PendingContext.Provider value={notes}>
      <Workspace book={book} actions={actions} right={right} notice={<JobNotice book={detail} />} openRef={openRef} viewingRef={viewingRef}
        chat={<LiveChat writing={writing} />} chatTools={<ChatConvs />}
        chatBadge={unread} openChat={openChat} writing={writing} />
      <SavesPanel open={saves.open} saveId={saves.id} onClose={closeSaves} onOpenSave={(id) => setSaves({ open: true, id })} />
      <PendingPanel open={pending.open} focus={pending.focus} onClose={closePending} />
      </PendingContext.Provider>
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
