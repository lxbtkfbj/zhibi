/** 真书的写作：开写、停下、接着写、拍板都交给后台的写作任务；状态从任务、群聊里的进度和写手边写边推的字里算出来。 */

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { get, patch, post } from '../../api/client'
import { keys } from '../../api/hooks'
import { settingsKeys, useBookSettings } from '../../api/settings'
import type { BookDetail, Chapter, Job, LiveDraft, MeetingMessage, Pending } from '../../api/types'
import type { ApiParts } from './fromApi'
import { refreshWorkspace } from './liveActions'
import { cn, type VGate, type VNode, type VWriting, type WritePlan, type WritingGates } from './model'
import { type ChapterDetail, type WritingControl, timesOf } from './writing'

const WHO: Record<string, VWriting['who']> = { chief: '主编', lorekeeper: '设定师', writer: '写手', reviewer: '审稿' }
const WRITE_KINDS = new Set(['write_book', 'rewrite_chapter'])

/** 这一轮写多少 → 开写接口要的 */
function writeBody(plan: WritePlan): { until: 'count' | 'unit' | 'volume' | 'book'; count: number } {
  if (plan === '1') return { until: 'count', count: 1 }
  if (plan === '3') return { until: 'count', count: 3 }
  return { until: plan, count: 1 }
}

/** 等作者拍板的那件事放在哪一页、怎么说 */
function gateOf(pending: Pending, parts: ApiParts | undefined, rewrites: number): VGate | undefined {
  switch (pending.kind) {
    case 'trial_read':
      return {
        kind: 'trial', node: 'c1', title: `试读前 ${pending.chapters} 章`,
        hint: '网文讲「黄金三章」：读者看完前三章，就决定追不追。读一读开头：文风、节奏、人物哪里不对就说，之后每一章都照你说的写；满意就接着写。',
      }
    case 'chapter_stuck':
      return {
        kind: 'stuck', node: `c${pending.chapter}`, title: rewrites > 0 ? `第${pending.chapter}章重写了${timesOf(rewrites)}次，审稿还不满意` : `第${pending.chapter}章审稿不满意`,
        hint: '先读一读：觉得能用，就直接用这一版；想让写手再改，就告诉他怎么改。', issues: pending.issues,
      }
    case 'volume_review': {
      const volume = parts?.outline.arcs.flatMap((a) => a.volumes).find((v) => v.index === pending.volume)
      return {
        kind: 'volume', node: volume ? `v:${volume.id}` : 'book', title: `第${cn(pending.volume)}卷的卷纲`,
        hint: '主编把这一卷拆成了几个单元，就在下面，审稿也查过一遍。看看这一卷怎么走；觉得哪里不对，可以直接改，也可以让主编改。满意就开写。',
        issues: [...(pending.issues ?? []), ...(pending.node_update ? [`主编建议顺手改一下后面的节点「${pending.node_update.current.title}」：${pending.node_update.reason}`] : [])],
      }
    }
    case 'chapters_review':
      return {
        kind: 'chapters', node: `u:${pending.unit_id}`, title: `「${pending.unit_title}」的章纲`,
        hint: `主编给这个单元出了第 ${pending.first}–${pending.last} 章的章纲，就在下面。看看剧情顺不顺、爽点够不够；觉得哪里不对，可以直接改，也可以让主编改。满意就开写。`,
      }
    case 'segment_review': {
      if (pending.flow !== 3) {
        return { kind: 'segment', node: 'book', title: `第${cn(pending.number)}篇怎么走`, hint: '这一篇是按旧写法规划的，要按新写法重出一次；先去旧版处理。' }
      }
      return {
        kind: 'segment', node: 'book', title: `第${cn(pending.number)}篇怎么走`,
        hint: '上一篇快写完了。主编照全书的结局和前面的收尾，定好了下一篇的走向和分卷，就在下面。看看方向对不对；满意就往下写。',
        issues: pending.warnings,
        detail: {
          title: pending.plan.title, text: pending.plan.text,
          items: pending.split.volumes.map((v) => `第${cn(v.index)}卷「${v.title}」${v.chapter_count ? `· ${v.chapter_count} 章` : ''}：${v.summary || v.goal}`),
        },
      }
    }
    default:
      return undefined
  }
}

export function useLiveWriting({ bookId, detail, parts, messages, draft }: {
  bookId: string; detail: BookDetail; parts: ApiParts | undefined; messages: MeetingMessage[]; draft: LiveDraft | null
}): WritingControl {
  const qc = useQueryClient()
  const settings = useBookSettings(bookId)
  // 一章不过审稿最多重写几次：本书设置「编辑部写得多仔细」那一档定的
  const rewrites = settings.data?.settings.max_rewrites ?? 2
  const job = detail.active_job
  const writingJob = job && WRITE_KINDS.has(job.kind) ? job : null
  // 点了停下：等手上这一章写完（记的是哪一轮，换了一轮就不算）
  const [stopping, setStopping] = useState('')
  // 这一轮写完了：在这一页上看着它写完的才说一声，收起以后不再说
  const [finished, setFinished] = useState('')
  const [last, setLast] = useState<{ id: string; status: string } | null>(null)
  if (writingJob && (last?.id !== writingJob.id || last.status !== writingJob.status)) {
    if (last?.id === writingJob.id && last.status !== 'succeeded' && writingJob.status === 'succeeded') setFinished(writingJob.id)
    setLast({ id: writingJob.id, status: writingJob.status })
  }

  const status = useMemo((): VWriting => {
    if (!writingJob) return { state: 'idle' }
    const { status: state } = writingJob
    if (state === 'queued' || state === 'running') {
      const live = draft && draft.job_id === writingJob.id && !draft.done ? draft : null
      if (live) {
        return {
          state: 'working', who: '写手', chapter: `c${live.chapter}`, live: live.text, stopping: stopping === writingJob.id,
          doing: { write: '写手在写', extend: '字数不够，写手在接着写', ending: '写手在改结尾' }[live.mode] + `第${live.chapter}章${live.title ? `「${live.title}」` : ''}`,
        }
      }
      const last = [...messages].reverse().find((m) => m.job_id === writingJob.id && m.kind === 'status')
      return {
        state: 'working', who: WHO[last?.speaker ?? 'chief'] ?? '主编', stopping: stopping === writingJob.id,
        doing: state === 'queued' ? '排队中，马上开始' : (last?.content ?? '编辑部在干活').replace(/[.…]+$/, ''),
      }
    }
    if (state === 'waiting_author' && writingJob.pending) {
      const gate = gateOf(writingJob.pending, parts, rewrites)
      return gate ? { state: 'waiting', gate } : { state: 'idle' }
    }
    if (state === 'failed') return { state: 'failed', error: writingJob.error || '模型出错了', note: '写好的都留着，点「接着写」从中断的地方接着做。' }
    if (state === 'cancelled') return { state: 'stopped', note: '停下了，写好的都留着。接着写从中断的地方开始。' }
    if (finished === writingJob.id) {
      const note = [...messages].reverse().find((m) => m.job_id === writingJob.id && m.kind === 'decision' && m.speaker === 'system')?.content
      return { state: 'finished', note: note || '这一轮写完了。' }
    }
    return { state: 'idle' }
  }, [writingJob, draft, messages, parts, stopping, finished, rewrites])

  const gates: WritingGates = {
    segment: settings.data?.settings.segment_approval ?? true,
    volume: settings.data?.settings.volume_approval ?? true,
    chapters: settings.data?.settings.chapters_approval ?? false,
    trial: settings.data?.settings.trial_read ?? true,
  }

  const refresh = useCallback(async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: keys.book(bookId) }),
      refreshWorkspace(qc, bookId),
    ])
  }, [qc, bookId])
  const setJob = useCallback((next: Job) => {
    qc.setQueryData<BookDetail>(keys.book(bookId), (old) => (old ? { ...old, active_job: next } : old))
  }, [qc, bookId])
  // 正文页拿它当依赖：每次都是同一个，不然一章会被反复读
  const loadChapter = useCallback(async (node: VNode): Promise<ChapterDetail> => {
    if (!node.ref) return { text: '' }
    const chapter = await get<Chapter & { changes?: string[] }>(`/books/${bookId}/chapters/${node.ref.id}`)
    const review = chapter.review?.review
    const issues = [...(review?.issues ?? []), ...(chapter.review?.consistency?.issues ?? [])].map((i) => i.problem)
    return { text: chapter.content, changes: chapter.changes ?? [], teardown: chapter.teardown, review: review || issues.length ? { good: review?.highlights ?? [], issues } : undefined }
  }, [bookId])

  // 写着的时候，每写完一章、换到下一步，目录和字数跟着刷新
  const progress = writingJob ? `${writingJob.id}|${writingJob.status}|${draft?.chapter ?? ''}|${draft?.done ?? ''}|${messages.filter((m) => m.job_id === writingJob.id && m.kind === 'artifact').length}` : ''
  useEffect(() => {
    if (progress) void refreshWorkspace(qc, bookId)
  }, [progress, qc, bookId])

  return {
    status, gates, trialDone: detail.trial_read_done, rewrites,
    setGate: async (key, on) => {
      const field = { segment: 'segment_approval', volume: 'volume_approval', chapters: 'chapters_approval', trial: 'trial_read' }[key]
      await patch(`/books/${bookId}/settings`, { [field]: on })
      await qc.invalidateQueries({ queryKey: settingsKeys.book(bookId) })
      return on ? '好，写到那里会停下来请你看' : '好，写到那里编辑部自己定，不停下来'
    },
    start: async (plan) => {
      setFinished('')
      setJob(await post<Job>(`/books/${bookId}/write`, writeBody(plan)))
      await refresh()
    },
    stop: async () => {
      if (!writingJob) return
      setStopping(writingJob.id)
      setJob(await post<Job>(`/jobs/${writingJob.id}/cancel`))
      return writingJob.status === 'running' ? '好，等手上这一步做完就停' : '停下了'
    },
    resume: async () => {
      if (!writingJob) return
      setJob(await post<Job>(`/jobs/${writingJob.id}/resume`))
    },
    approve: async () => {
      if (!writingJob?.pending) return
      if (writingJob.pending.kind === 'segment_review') setJob(await post<Job>(`/jobs/${writingJob.id}/segment`, { action: 'confirm' }))
      else setJob(await post<Job>(`/jobs/${writingJob.id}/decision`, { action: 'approve', feedback: '' }))
      return writingJob.pending.kind === 'trial_read' ? '好，接着写' : '好，开写'
    },
    revise: async (text) => {
      if (!writingJob?.pending || !text.trim()) return
      if (writingJob.pending.kind === 'segment_review') setJob(await post<Job>(`/jobs/${writingJob.id}/segment`, { action: 'revise', feedback: text.trim() }))
      else setJob(await post<Job>(`/jobs/${writingJob.id}/decision`, { action: 'revise', feedback: text.trim() }))
      return writingJob.pending.kind === 'trial_read' ? '记下了：以后每一章都照这个写（记在写作要求里，随时能改）' : '好，交给编辑部改'
    },
    rewrite: async (node, request) => {
      if (!node.ref) throw new Error('这一章还不能重写')
      setFinished('')
      setJob(await post<Job>(`/books/${bookId}/chapters/${node.ref.id}/rewrite`, { feedback: request.trim(), confirm: true }))
      return null
    },
    setText: async (node, text) => {
      if (!node.ref) throw new Error('这一章还不能改')
      await patch<Chapter>(`/books/${bookId}/chapters/${node.ref.id}`, { content: text })
      await refresh()
    },
    loadChapter,
    dismiss: () => setFinished(''),
  }
}
