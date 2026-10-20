/** 新书页：接真书。编辑部浮窗里只有一个聊天（第五步：@ 点名、边写边显示、停、重新回答、新对话、从这里重来）；开写、正文、拍板在新书页上；
 *  左边一栏最下面固定两行：「存档」和「本书设置」都是居中弹窗；右上角齿轮是系统设置。
 *  「待处理」是编辑部等你定的建议（第四步第二批）：在编辑部窗口里，顶上点了整个窗口换成待处理；收成小球时小球旁边说一声。 */

import { useIsMutating, useQueryClient } from '@tanstack/react-query'
import { Settings } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { keys, useBook, useJobActions, useOutline } from '../../api/hooks'
import { startTeardown, stopTeardown } from '../../api/teardown'
import { TeardownStartDialog } from '../../components/TeardownStart'
import { TeardownControlProvider } from './TeardownProgress'
import { useLibrarySuggestions } from '../../api/library'
import type { BookDetail, ChatViewing, Conversation, Job, LiveDraft, MeetingMessage } from '../../api/types'
import { EmptyState } from '../../components/ui'
import type { ChatQuote } from '../../lib/chat'
import { useMeeting } from '../../lib/useMeeting'
import { useConversationReads } from '../../lib/useWorkspacePanels'
import { currentTarget, type NodeFeedback, nodeFeedback } from '../../lib/workspace'
import { segmentReviewKey } from '../../lib/outlineWriting'
import { BookContext, type BookContextValue, type PitchChoice } from '../book/context'
import { BookSettingsDialog } from './BookSettings'
import { ChatConvs } from './ChatConvs'
import { LiveChat } from './LiveChat'
import { flushAutoSave, useLiveBook } from './liveActions'
import { SavesPanel, SavesRow } from './Saves'
import { useLiveWriting } from './liveWriting'
import { useSettingsModal } from '../../lib/settingsModal'
import { PendingBallTag, PendingButton, PendingList } from './Inbox'
import { PendingContext, pendingTarget } from './pending'
import { Workspace } from './Workspace'
import { Icon } from './desk-v2/shared'

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

/** 写书以外的活（编辑部帮拆这类）在干：顶栏下面说一声；用以前的开书流程建的书停在开书半路：能在这里停下开书，之后直接在新书页写。
 *  写书的活顶栏下面有写作条，不用这一条。 */
function JobNotice({ book }: { book: BookDetail }) {
  const { cancel } = useJobActions(book.id)
  const job = book.active_job
  if (!job || ['write_book', 'rewrite_chapter'].includes(job.kind) || !['queued', 'running', 'waiting_author'].includes(job.status)) return null
  const setup = job.kind === 'book_setup'
  const text = setup
    ? job.status === 'waiting_author'
      ? '这本书是用以前的开书流程建的，开书还没走完。新书页不走那一套了：停下开书以后，简介、设定、大纲都在这里直接写，写好了就能开写。'
      : '这本书在走以前的开书流程，编辑部正在干活。新书页不走那一套了：停下开书以后，简介、设定、大纲都在这里直接写。'
    : '编辑部正在干活，这时候书里的东西先改不了，等它停下。'
  return (
    <div className="flex shrink-0 items-center justify-center gap-3 border-b border-line bg-seal-soft/60 px-4 py-2 text-[13px] text-seal-dark">
      <span>{text}</span>
      {setup && (
        <button type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(job.id)}
          className="h-7 shrink-0 rounded-md border border-line-2 bg-card px-3 text-[13px] text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink disabled:opacity-50">
          {job.status === 'running' ? '做完这一步就停下开书' : '停下开书'}
        </button>
      )}
    </div>
  )
}

function Desk({ bookId, detail }: { bookId: string; detail: BookDetail }) {
  const qc = useQueryClient()
  const teardown = detail.source === 'teardown'
  const { book, actions, loading, error, raw } = useLiveBook(bookId)
  const [openChat, setOpenChat] = useState(0)
  const onOpen = useCallback(() => setOpenChat((n) => n + 1), [])
  const { ctx, unread, messages, draft } = useEditorial(bookId, detail, onOpen)
  const writing = useLiveWriting({ bookId, detail, parts: raw, messages, draft })
  const openRef = useRef<((type: string, id: string) => void) | null>(null)
  const viewingRef = useRef<(() => ChatViewing | null) | null>(null)
  // 存档弹窗：开没开、点开的是哪一档
  const [saves, setSaves] = useState<{ open: boolean; id: number | null }>({ open: false, id: null })
  // 编辑部窗口是不是换成了待处理那一页、要找到挂在哪一条上的建议
  const [inbox, setInbox] = useState<{ open: boolean; focus: string | null }>({ open: false, focus: null })
  // 本书设置：居中的弹窗，背景糊掉
  const [settings, setSettings] = useState(false)
  const [startOpen, setStartOpen] = useState(false)
  const [starting, setStarting] = useState(false)
  const [stoppingId, setStoppingId] = useState<string | null>(null)
  const [teardownError, setTeardownError] = useState<unknown>()
  const teardownJob = detail.active_job?.kind === 'teardown' ? detail.active_job : null
  const stopping = stoppingId === teardownJob?.id && ['queued', 'running'].includes(teardownJob?.status ?? '')
  const start = async (upto: number | null) => {
    if (starting) return
    setStarting(true)
    setTeardownError(undefined)
    try {
      const job = await startTeardown(bookId, upto)
      const event = qc.getQueryData<Job>(['teardown-job-event', bookId])
      const latest = event?.id === job.id ? event : job
      const active = latest.status === 'queued' || latest.status === 'running'
      setStoppingId(null)
      qc.setQueryData<BookDetail>(keys.book(bookId), old => old ? {
        ...old, active_job: latest, teardown: active ? { ...old.teardown!, stage: latest.status, upto } : old.teardown,
      } : old)
      void qc.invalidateQueries({ queryKey: keys.books })
    } finally { setStarting(false) }
  }
  const stop = async () => {
    if (!teardownJob || stopping) return
    setStoppingId(teardownJob.id)
    setTeardownError(undefined)
    try {
      // 不拿 HTTP 回包覆盖较新的 SSE：按钮一直锁到最终任务事件（或重连后的书状态）。
      await stopTeardown(bookId)
    } catch (error) { setStoppingId(null); throw error }
  }
  const closeSettings = useCallback(() => setSettings(false), [])
  const closeSaves = useCallback(() => setSaves({ open: false, id: null }), [])
  const closeInbox = useCallback(() => setInbox({ open: false, focus: null }), [])
  // 打开待处理：编辑部收着就先打开窗口
  const openInbox = useCallback((focus: string | null) => { setInbox({ open: true, focus }); onOpen() }, [onOpen])
  const suggestions = useLibrarySuggestions(bookId)
  const { openSettings: openSystemSettings } = useSettingsModal()
  const notes = useMemo(() => {
    const counts = new Map<string, number>()
    if (teardown) return { count: () => 0, open: () => undefined }
    for (const s of suggestions.data ?? []) {
      const at = pendingTarget(s)?.id
      if (at) counts.set(at, (counts.get(at) ?? 0) + 1)
    }
    return { count: (id: string) => counts.get(id) ?? 0, open: (id?: string) => openInbox(id ?? null) }
  }, [suggestions.data, openInbox, teardown])
  const context = useMemo(() => ({
    ...ctx,
    openTarget: (type: string, id: string) => openRef.current?.(type, id),
    viewing: () => viewingRef.current?.() ?? null,
    openSaves: (id?: number) => setSaves({ open: true, id: id ?? null }),
    openPending: () => { if (!teardown) openInbox(null) },
  }), [ctx, openInbox, teardown])
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
    <button type="button" onClick={openSystemSettings} style={{ all: 'unset', display: 'flex', cursor: 'pointer' }} aria-label="系统设置" title="系统设置">
      <Icon name="settings" />
    </button>
  )
  const pendingCount = suggestions.data?.length ?? book.pending
  const chatTools = (
    <>
      {!teardown && <PendingButton count={pendingCount} open={inbox.open} onClick={() => (inbox.open ? closeInbox() : setInbox({ open: true, focus: null }))} />}
      {(teardown || !inbox.open) && <ChatConvs />}
    </>
  )
  // 换成待处理时聊天不卸掉：回到聊天还是原来翻到的地方
  const chat = (
    <>
      {!teardown && inbox.open && <PendingList key={inbox.focus ?? ''} focus={inbox.focus} onBack={closeInbox} />}
      <div className={!teardown && inbox.open ? 'hidden' : 'contents'}><LiveChat writing={writing} /></div>
    </>
  )
  const row = 'toc-foot'
  const sideFooter = (
    <>
      <SavesRow className={row} open={saves.open} onClick={() => setSaves(saves.open ? { open: false, id: null } : { open: true, id: null })} />
      {!teardown && <button type="button" onClick={() => setSettings(true)} aria-pressed={settings} title="这本书怎么写：人称、每章字数、写作要求……"
        className={`${row} ${settings ? 'bg-line/50 text-ink' : ''}`}>
        <Settings className="size-4 shrink-0" />本书设置
      </button>}
    </>
  )
  return (
    <BookContext.Provider value={context}>
      <PendingContext.Provider value={notes}>
      <TeardownControlProvider value={teardown ? { job: teardownJob, stopping, starting, start, stop, retry: () => start(detail.teardown?.upto ?? null), openStart: () => setStartOpen(true), error: teardownError } : null}>
      <Workspace book={teardown ? { ...book, teardown: detail.teardown } : book} actions={actions} right={right} sideFooter={sideFooter}
        essenceFooter={teardown ? <SavesRow className={row} open={saves.open} onClick={() => setSaves(saves.open ? { open: false, id: null } : { open: true, id: null })} icon={false} /> : undefined}
        notice={!teardown ? <JobNotice book={detail} /> : undefined} openRef={openRef} viewingRef={viewingRef}
        chat={chat} chatTools={chatTools} chatBallNote={!teardown ? <PendingBallTag count={pendingCount} onClick={() => openInbox(null)} /> : undefined}
        chatBadge={unread} openChat={openChat} writing={writing} />
      <SavesPanel open={saves.open} saveId={saves.id} onClose={closeSaves} onOpenSave={(id) => setSaves({ open: true, id })} />
      {!teardown && <BookSettingsDialog open={settings} onClose={closeSettings} />}
      {teardown && <TeardownStartDialog open={startOpen} title={book.title} total={raw?.chapters.length ?? detail.teardown?.chapters ?? 0} last={detail.teardown?.last_read ?? 0} needsClosing={!!detail.teardown?.needs_closing} stage={detail.teardown?.stage ?? 'imported'} initialUpto={detail.teardown?.upto ?? null} onClose={() => setStartOpen(false)} onStart={start} />}
      </TeardownControlProvider>
      </PendingContext.Provider>
    </BookContext.Provider>
  )
}

export function BookDesk() {
  const { bookId = '' } = useParams()
  const detail = useBook(bookId)
  if (detail.isPending) return <div className="flex h-dvh items-center justify-center bg-paper text-[15px] text-ink-3">正在读这本书…</div>
  if (detail.error || !detail.data) return <EmptyState title="找不到这本书"><Link to="/" className="text-seal underline">回到书房</Link></EmptyState>
  if (detail.data.source === 'teardown' && detail.data.teardown?.stage === 'confirming') return <Navigate to={`/teardown/${bookId}`} replace />
  return <Desk key={bookId} bookId={bookId} detail={detail.data} />
}
