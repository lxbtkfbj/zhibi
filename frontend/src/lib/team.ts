import { useEffect, useState } from 'react'
import type { BookStatus, Job, MeetingMessage, Speaker } from '../api/types'

export const STAGES = [
  { key: 'concept', label: '概念' },
  { key: 'lore', label: '设定' },
  { key: 'spine', label: '主线' },
  { key: 'threads', label: '线索' },
  { key: 'outline', label: '总纲' },
  { key: 'volume_plan', label: '卷纲' },
  { key: 'critique', label: '审稿' },
  { key: 'approval', label: '拍板' },
  { key: 'writing', label: '写作' },
] as const

export type StageKey = (typeof STAGES)[number]['key']
export type StageState = 'done' | 'current' | 'todo'

const DRAFT_STAGES = ['concept', 'lore', 'spine', 'threads', 'outline', 'volume_plan', 'critique']

/** 根据书和任务状态、会议里已交付的产出，算出流程进度。 */
export function computeStages(book: BookStatus, job: Job | null | undefined, messages: MeetingMessage[]) {
  const approval = STAGES.findIndex((s) => s.key === 'approval')
  let done = 0
  if (book === 'completed') done = STAGES.length
  else if (book === 'ready' || book === 'writing') done = approval + 1
  else if ((job?.status === 'waiting_author' && job.pending?.kind !== 'setup_questions') || book === 'awaiting_approval') done = approval
  else {
    const lastJob = [...messages].reverse().find((m) => m.job_id)?.job_id
    const delivered = new Set(
      messages.filter((m) => m.kind === 'artifact' && m.job_id === lastJob).map((m) => m.payload?.type),
    )
    for (const key of DRAFT_STAGES) {
      if (delivered.has(key)) done += 1
      else break
    }
    // 审稿意见出来后可能还要自动修改一轮，停在审稿这一步
    done = Math.min(done, DRAFT_STAGES.length - 1)
  }
  return STAGES.map((s, i) => ({ ...s, state: (i < done ? 'done' : i === done ? 'current' : 'todo') as StageState }))
}

export type RoleState = 'working' | 'done' | 'idle'
export const TEAM: Exclude<Speaker, 'author' | 'system'>[] = ['chief', 'lorekeeper', 'writer', 'reviewer']

/** 每位编辑当前在做什么。 */
export function teamStatus(messages: MeetingMessage[], working: boolean) {
  const last = messages[messages.length - 1]
  const activeSpeaker = working && last?.kind === 'status' ? last.speaker : null
  return Object.fromEntries(
    TEAM.map((role) => {
      const mine = messages.filter((m) => m.speaker === role)
      const lastStatus = [...mine].reverse().find((m) => m.kind === 'status')
      const lastArtifact = [...mine].reverse().find((m) => m.kind === 'artifact')
      if (activeSpeaker === role) {
        return [role, { state: 'working' as RoleState, text: lastStatus?.content.replace(/^.{2,3}正在/, '正在') ?? '工作中' }]
      }
      if (lastArtifact) return [role, { state: 'done' as RoleState, text: lastArtifact.content }]
      return [role, { state: 'idle' as RoleState, text: role === 'writer' ? '等开写' : '待命' }]
    }),
  ) as Record<(typeof TEAM)[number], { state: RoleState; text: string }>
}

/** 刚到达的消息，用打字机效果逐字显示。 */
export function useTypewriter(text: string, enabled: boolean, speed = 28) {
  const [count, setCount] = useState(enabled ? 0 : text.length)
  useEffect(() => {
    if (!enabled) return
    const step = Math.max(1, Math.ceil(text.length / 60))
    const timer = setInterval(() => {
      setCount((c) => {
        if (c >= text.length) {
          clearInterval(timer)
          return c
        }
        return Math.min(text.length, c + step)
      })
    }, speed)
    return () => clearInterval(timer)
  }, [text, enabled, speed])
  return { shown: enabled ? text.slice(0, count) : text, typing: enabled && count < text.length }
}

export function isFresh(iso: string | null, seconds = 20) {
  return !!iso && Date.now() - new Date(iso).getTime() < seconds * 1000
}
