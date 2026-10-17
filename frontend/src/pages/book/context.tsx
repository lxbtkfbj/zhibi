import { createContext, useContext, type Dispatch, type SetStateAction } from 'react'
import type { BookDetail, Conversation, Job, LiveDraft, MeetingMessage, Outline, StoryNode } from '../../api/types'
import type { NodeFeedback, WorkspaceTarget } from '../../lib/workspace'

export interface BookContextValue {
  bookId: string
  book: BookDetail
  job: Job | null
  messages: MeetingMessage[]
  connected: boolean
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
  focusComposer: number
  requestFeedback: () => void
  requestNodeFeedback: (node: Pick<StoryNode, 'id' | 'index' | 'title'>) => void
  composerNode: NodeFeedback | null
  setComposerNode: (node: NodeFeedback | null) => void
  composerDrafts: Record<string, string>
  setComposerDrafts: Dispatch<SetStateAction<Record<string, string>>>
  celebrate: () => void
  segmentPinEnd: boolean
  setSegmentPinEnd: (value: boolean) => void
  segmentReview: {
    submitting: boolean
    action: SegmentDecisionInput['action'] | undefined
    error: unknown
    submit: (body: SegmentDecisionInput) => Promise<boolean>
  }
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
