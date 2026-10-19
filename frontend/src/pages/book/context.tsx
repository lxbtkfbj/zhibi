import { createContext, useContext, type Dispatch, type SetStateAction } from 'react'
import type { BookDetail, ChatViewing, Conversation, Job, LiveDraft, MeetingMessage, Outline, StoryNode } from '../../api/types'
import type { ChatQuote, ChatTyping } from '../../lib/chat'
import type { NodeFeedback, WorkspaceTarget } from '../../lib/workspace'

export interface BookContextValue {
  bookId: string
  book: BookDetail
  job: Job | null
  messages: MeetingMessage[]
  connected: boolean
  chatTyping: Record<string, ChatTyping>
  chatQuotes: Record<string, ChatQuote | null>
  setChatQuotes: Dispatch<SetStateAction<Record<string, ChatQuote | null>>>
  askChief: (quote: ChatQuote) => void
  /** 写手正在写的正文（实时）；写完一段后 done 为 true */
  draft: LiveDraft | null
  working: boolean
  /** 等作者拍板：开书方案、卷纲、试读或卡住的章节 */
  waiting: boolean
  /** 主编动笔前的提问，等作者回答 */
  asking: boolean
  outline: Outline | undefined
  conversation: Conversation
  setConversation: (conversation: Conversation) => void
  unread: Record<Conversation, number>
  following: boolean
  resumeFollow: () => void
  followTarget: WorkspaceTarget | null
  manualNavigate: (path: string) => void
  /** 新书页上有：聊天里点「去看看」直接打开那一条，不跳回旧版 */
  openTarget?: (type: string, id: string) => void
  /** 新书页上有：作者这会儿正在看哪一页，群聊发话时带上 */
  viewing?: () => ChatViewing | null
  /** 新书页上有：打开存档那一栏（带上一档的号就直接点开那一档） */
  openSaves?: (saveId?: number) => void
  /** 新书页上有：群聊正在看哪一段对话；null 是最近聊的那一段 */
  chatConv?: string | null
  setChatConv?: (id: string | null) => void
  focusComposer: number
  focusChat: () => void
  /** 新书页上有：只把编辑部的窗口打开，不把光标放进输入框（不然按 Esc 会停下正在写的回答） */
  showChat?: () => void
  requestFeedback: () => void
  requestNodeFeedback: (node: Pick<StoryNode, 'id' | 'index' | 'title'>) => void
  composerNode: NodeFeedback | null
  setComposerNode: (node: NodeFeedback | null) => void
  composerDrafts: Record<string, string>
  setComposerDrafts: Dispatch<SetStateAction<Record<string, string>>>
  celebrate: () => void
  /** 选故事方向时页面里点选的那一张；底部操作条负责提交。 */
  pitchChoice: PitchChoice | null
  setPitchChoice: (choice: PitchChoice | null) => void
  segmentPinEnd: boolean
  setSegmentPinEnd: (value: boolean) => void
  segmentReview: {
    submitting: boolean
    action: SegmentDecisionInput['action'] | undefined
    error: unknown
    submit: (body: SegmentDecisionInput) => Promise<boolean>
  }
}

export interface PitchChoice {
  /** 任务 id 加轮次；重出一轮后旧选择自动作废。 */
  key: string
  index: number
  name: string
  title: string
  length: string
}

export interface SegmentDecisionInput {
  action: 'confirm' | 'delegate' | 'revise' | 'redo'
  feedback?: string
  flips?: { topic: string; choice: string }[]
}

export const BookContext = createContext<BookContextValue | null>(null)

export function useBookContext() {
  const value = useContext(BookContext)
  if (!value) throw new Error('useBookContext 必须在 BookLayout 内使用')
  return value
}
