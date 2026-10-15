import { useEffect, useState } from 'react'
import type { MeetingMessage, Speaker } from '../api/types'

export type RoleState = 'working' | 'done' | 'idle'
export const TEAM: Exclude<Speaker, 'author' | 'system'>[] = ['chief', 'lorekeeper', 'writer', 'reviewer']

/** 每位编辑当前在做什么。 */
export function teamStatus(messages: MeetingMessage[], working: boolean) {
  const last = [...messages].reverse().find(m => m.kind === 'status' && !m.payload?.thread)
  const activeSpeaker = working ? last?.speaker : null
  return Object.fromEntries(
    TEAM.map((role) => {
      const mine = messages.filter((m) => m.speaker === role)
      const lastStatus = [...mine].reverse().find((m) => m.kind === 'status')
      const lastArtifact = [...mine].reverse().find((m) => m.kind === 'artifact')
      if (activeSpeaker === role && (!lastArtifact || (lastStatus && lastStatus.id > lastArtifact.id))) {
        return [role, { state: 'working' as RoleState, text: lastStatus?.content.replace(/^.{2,3}正在/, '正在') ?? '工作中' }]
      }
      if (lastArtifact && working) return [role, { state: 'done' as RoleState, text: '已交稿，等下一步' }]
      return [role, { state: 'idle' as RoleState, text: role === 'reviewer' && working ? '等稿子' : '空闲' }]
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
