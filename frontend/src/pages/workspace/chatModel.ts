/** 编辑部聊天：只有一个聊天，想找谁就打 @ 点名；回答边写边显示，能停、能重新回答。原型和真书共用一套界面，回答从哪来由外面给。 */

import type { ReactNode } from 'react'

export type ChatRole = '主编' | '设定师' | '写手' | '审稿'

export const CHAT_ROLES: { role: ChatRole; duty: string }[] = [
  { role: '主编', duty: '方向、大纲，拿主意' },
  { role: '设定师', duty: '人物、世界，前后对得上' },
  { role: '写手', duty: '正文怎么写、文笔' },
  { role: '审稿', duty: '挑毛病、看节奏' },
]

/** thinking 还没出字；streaming 正在一个字一个字出；stopped 作者叫停了，写出来的留着；failed 没答上来 */
export type ReplyState = 'thinking' | 'streaming' | 'done' | 'stopped' | 'failed'

export interface ChatMessage {
  id: string
  who: '作者' | ChatRole
  text: string
  /** 作者这句点了谁的名 */
  to?: ChatRole
  /** 回答：答的是哪一句（重新回答就是把那一句再答一遍） */
  replyTo?: string
  state?: ReplyState
  /** 没答上来的原因，说人话 */
  error?: string
  /** 消息下面再放点东西：改了什么、去看看、撤销…… */
  below?: ReactNode
  /** 不是一问一答的（编辑部干活的进度、方案卡）：整条换成这个 */
  custom?: ReactNode
}

export interface ChatControl {
  messages: ChatMessage[]
  /** 正在回答：发送键变成「停」 */
  answering: boolean
  /** 返回 false：没发出去，输入框里的话留着 */
  send: (text: string, to?: ChatRole) => void | Promise<boolean>
  /** 停下正在写的回答，写出来的字留着 */
  stop: () => void
  /** 把这一条回答重新来一遍；没答上来的就是重试 */
  again: (id: string) => void
  /** 原型的说明：输入框下面一行小字 */
  hint?: string
  /** 输入框左下「点名」旁边再放的按钮（总结一下） */
  tools?: ReactNode
  /** 输入框上面一行提醒（在等你拍板……） */
  notice?: ReactNode
  placeholder?: string
  /** 正在发：发送键转圈 */
  sending?: boolean
  /** 没发出去的原因 */
  sendError?: ReactNode
  /** 外面要把光标放进输入框：每次加一 */
  focusKey?: number
}

const ROLE_NAMES = CHAT_ROLES.map((r) => r.role)

/** 话里直接写了「@设定师」（没从列表里点）：认出来，从话里拿掉。只认第一个。 */
export function takeMention(text: string): { text: string; to?: ChatRole } {
  const match = text.match(/@(主编|设定师|写手|审稿)\s*/)
  if (!match) return { text }
  return { text: (text.slice(0, match.index) + text.slice(match.index! + match[0].length)).trim(), to: match[1] as ChatRole }
}

/** 光标前面是不是正在打「@设…」：是就给出 @ 在哪、打了什么、对得上的人 */
export function mentionAt(text: string, caret: number): { start: number; query: string; roles: ChatRole[] } | null {
  const match = text.slice(0, caret).match(/@([^\s@]{0,3})$/)
  if (!match) return null
  const roles = ROLE_NAMES.filter((role) => role.startsWith(match[1]))
  return roles.length ? { start: caret - match[0].length, query: match[1], roles } : null
}

/** 最新一条回答：只有它下面有「重新回答」。编辑部干活的进度这类不算一句话，跳过去看 */
export function latestReply(messages: ChatMessage[]): ChatMessage | undefined {
  const last = messages.findLast((m) => !m.custom)
  return last && last.who !== '作者' ? last : undefined
}
