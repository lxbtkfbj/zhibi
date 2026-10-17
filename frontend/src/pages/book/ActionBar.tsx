import clsx from 'clsx'
import { AlertTriangle, Check, ChevronUp, CirclePause, PenLine, RotateCcw, Stamp } from 'lucide-react'
import { useLibrary } from '../../api/library'
import { useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useIsMutating } from '@tanstack/react-query'
import { useJobActions } from '../../api/hooks'
import type { Job, Pending } from '../../api/types'
import { Button, ErrorText } from '../../components/ui'
import { decisionCopy } from '../../lib/decision'
import { LEGACY_SETUP_NOTICE, needsSetupRestart } from '../../lib/setupPresentation'
import { setupPieces, targetPiece } from '../../lib/storyMap'
import { pendingTarget } from '../../lib/workspace'
import { useBookContext } from './context'
import { WRITE_OPTIONS } from '../../lib/writingUi'
import { NodeUpdateComparison } from './Decision'

type Tone = 'wait' | 'busy' | 'idle' | 'error'

const DOT: Record<Tone, string> = {
  wait: 'bg-seal',
  busy: 'bg-chief motion-safe:animate-pulse',
  idle: 'bg-ink-3/60',
  error: 'bg-seal',
}

function Bar({ tone, title, onTitle, detail, panel, panelLabel, children, error }: {
  tone: Tone
  title: ReactNode
  onTitle?: () => void
  detail?: ReactNode
  panel?: ReactNode
  panelLabel?: string
  children?: ReactNode
  error?: unknown
}) {
  const [open, setOpen] = useState(false)
  return <div data-testid="action-bar" data-tone={tone} className="relative z-10 shrink-0 border-t border-divider bg-page shadow-[var(--shadow-bar)]">
    {panel && open && <div className="scroll-thin max-h-[45vh] overflow-y-auto border-b border-divider bg-paper-2 px-5 py-4 text-sm leading-relaxed text-ink-2 @2xl/manuscript:px-8">{panel}</div>}
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5 px-5 py-3.5 @2xl/manuscript:px-7">
      <span aria-hidden className={clsx('size-2 shrink-0 rounded-full', DOT[tone])} />
      <div className="min-w-0 flex-1 basis-56">
        {onTitle
          ? <button type="button" onClick={onTitle} className="max-w-full truncate text-left text-[15px] font-semibold text-ink hover:text-chief hover:underline hover:underline-offset-4">{title}</button>
          : <p className="truncate text-[15px] font-semibold text-ink">{title}</p>}
        {(detail || panel) && <div className="mt-0.5 flex min-w-0 items-center gap-2 text-[13px] text-ink-2">
          {detail && <span className="min-w-0 truncate">{detail}</span>}
          {panel && <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)} className="flex shrink-0 items-center gap-0.5 text-chief hover:underline hover:underline-offset-4">
            {open ? '收起' : panelLabel ?? '看细节'}<ChevronUp className={clsx('size-3.5 transition-transform', !open && 'rotate-180')} />
          </button>}
        </div>}
      </div>
      {children && <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>}
    </div>
    {!!error && <div className="px-5 pb-3 @2xl/manuscript:px-8"><ErrorText error={error} /></div>}
  </div>
}

function count(items: unknown[] | undefined) {
  return items?.length ?? 0
}

/** 书稿栏底部固定的一条：所有要作者动手的事——拍板、开写、停止、继续——都只在这里。 */
export function ActionBar() {
  const { book, bookId, job, waiting, asking, working, draft, messages, requestFeedback, resumeFollow, manualNavigate, celebrate, segmentReview, pitchChoice } = useBookContext()
  const actions = useJobActions(bookId)
  const { pieceAction, confirmSetupAndWrite, setupPending, decide, decisionPending, cancel, resume, write, restartSetup, pitches } = actions
  const library = useLibrary(bookId)
  const libraryCount = (library.data?.characters.length ?? 0) + (library.data?.entries.length ?? 0)
  const restarting = useIsMutating({ mutationKey: ['restart-setup', bookId] }) > 0
  const expanding = useIsMutating({ mutationKey: ['outline-expand', bookId] }) > 0
  const { pathname } = useLocation()
  const [choice, setChoice] = useState(book.chapters_final === 0 && !book.trial_read_done ? '3' : '10')
  const pending = job?.pending
  const target = pendingTarget(pending, bookId)
  // 定调和设定合并确认时，两页都算「已经在看了」。
  const mergedSettings = pending?.kind === 'setup_piece' && pending.flow === 3 && pending.piece === 'settings' && pathname === `/books/${bookId}/library`
  const onTarget = (!!target && target.path.split('?')[0] === pathname) || mergedSettings

  if (job && needsSetupRestart(book, job)) {
    const restart = async () => {
      try { await restartSetup.mutateAsync(job.id); manualNavigate(`/books/${bookId}`) } catch { /* 保留操作条，显示错误。 */ }
    }
    return <Bar tone="wait" title="开书流程更新了" detail="这个旧开书任务要按新流程重开" panel={<p>{LEGACY_SETUP_NOTICE}</p>} panelLabel="为什么" error={restartSetup.error}>
      <Button variant="seal" loading={restarting} disabled={restarting} onClick={() => void restart()}><RotateCcw className="size-3.5" />按新流程重开</Button>
    </Bar>
  }

  if (confirmSetupAndWrite.isPending) return <Bar tone="busy" title="正在确认大纲" detail="开书任务结束后会自动开写前 3 章…" />

  if (asking && job) return <Bar tone="wait" title="待你回答：动笔前提问" onTitle={onTarget ? undefined : resumeFollow} detail={onTarget ? '在上面回答，或者都交给编辑部决定' : '主编动笔前有几个问题想问你'}>
    {!onTarget && <Button variant="seal" onClick={resumeFollow}>去回答</Button>}
  </Bar>

  if (waiting && job && pending) return waitingBar(job, pending, onTarget, target?.label)

  if (expanding && !(job && (job.status === 'queued' || job.status === 'running'))) return <Bar tone="busy" title="主编正在展开大纲" detail="展开好了会出现在大纲里" />

  if (job && working) {
    if (job.kind === 'outline_expand') return <Bar tone="busy" title="主编正在展开大纲" detail="展开好了会出现在大纲里" />
    const live = draft && !draft.done && draft.job_id === job.id ? draft : null
    const status = [...messages].reverse().find(message => message.job_id === job.id && message.kind === 'status')
    const title = job.status === 'queued' ? '排队中，马上开始'
      : live ? `写手正在写第 ${live.chapter} 章` : status?.content.replace(/[.…]+$/, '') ?? '编辑部正在工作'
    return <Bar tone="busy" title={title} detail={live ? `已写 ${live.text.replace(/\s/g, '').length} 字 · 想说什么直接在群聊里插话` : '想说什么直接在群聊里插话，不用等'} error={cancel.error}>
      <Button variant="outline" loading={cancel.isPending} onClick={() => cancel.mutate(job.id)}><CirclePause className="size-3.5" />停止</Button>
    </Bar>
  }

  if (job && (job.status === 'failed' || job.status === 'cancelled')) {
    if (job.kind === 'outline_expand') return <Bar tone="error" title="展开没有完成" detail={job.error || '回到大纲，重新点「展开这一个」'} />
    return <Bar tone={job.status === 'failed' ? 'error' : 'idle'} title={job.status === 'failed' ? '这一轮出错了' : '任务已停止'}
      detail={job.status === 'failed' ? job.error || '做完的步骤都保存着' : '做完的步骤都保存着，继续时从中断的地方接着做'}
      panel={job.status === 'failed' && job.error ? <p className="break-words whitespace-pre-wrap">{job.error}</p> : undefined} panelLabel="完整报错" error={resume.error}>
      <Button variant="primary" loading={resume.isPending} onClick={() => resume.mutate(job.id)}><RotateCcw className="size-3.5" />继续</Button>
    </Bar>
  }

  if (confirmSetupAndWrite.error) return <Bar tone="error" title="自动开写没有完成" detail="先看看下面的错误，再从这里开写" error={confirmSetupAndWrite.error} />

  if (book.status === 'ready' || book.status === 'writing') {
    const option = WRITE_OPTIONS.find(item => item.key === choice) ?? WRITE_OPTIONS[1]
    const fresh = !book.chapters_final
    return <Bar tone={fresh ? 'wait' : 'idle'} title={fresh ? '开书稿齐了，随时都能改' : '编辑部空闲'} error={write.error}
      detail={fresh ? <span className="flex flex-wrap items-center gap-x-3.5 gap-y-1"><span className="flex items-center gap-1"><Check className="size-3.5 text-lore" />定调</span><span className="flex items-center gap-1"><Check className="size-3.5 text-lore" />设定 {libraryCount} 条</span><span className="flex items-center gap-1"><Check className="size-3.5 text-lore" />大纲</span><span className="text-ink-3">{option.hint}</span></span> : `已定稿 ${book.chapters_final} 章 · ${option.hint}`}>
      <label className="relative">
        <span className="sr-only">这一轮写多少</span>
        <select value={choice} onChange={event => setChoice(event.target.value)} className="h-9 appearance-none rounded-lg border border-line-2 bg-card pr-8 pl-3 text-sm text-ink hover:border-ink-3/50">
          {WRITE_OPTIONS.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
        </select>
        <ChevronUp aria-hidden className="pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2 rotate-180 text-ink-3" />
      </label>
      <Button variant="primary" loading={write.isPending} onClick={() => write.mutate({ until: option.until, count: option.count })}><PenLine className="size-3.5" />{book.chapters_final ? '继续写' : '开写'}</Button>
    </Bar>
  }

  return null

  // 普通函数而不是嵌套组件：每次渲染位置不变，Bar 的展开状态不会被重置。
  function waitingBar(job: Job, pending: Pending, onTarget: boolean, label?: string) {
    const goTarget = onTarget ? undefined : resumeFollow
    if (pending.kind === 'setup_prefill') return <Bar tone="wait" title="先写设定" detail="把想好的人物、金手指、境界写进设定库，也可以让 AI 补；写好了就出故事方向" error={pitches.error}>
      <Button variant="seal" loading={pitches.isPending} onClick={() => { resumeFollow(); pitches.mutate({ jobId: job.id, action: 'start' }) }}>出三个故事方向</Button>
    </Bar>

    if (pending.kind === 'setup_pitches') {
      const key = `${job.id}-${pending.round}`
      const picked = onTarget && pitchChoice?.key === key ? pitchChoice : null
      const pick = () => picked && pitches.mutate({ jobId: job.id, action: 'pick', index: picked.index + 1, length: Number(picked.length.match(/\d+/)?.[0]), ...(picked.title.trim() ? { title: picked.title.trim() } : {}) })
      const canFill = (pending as { open?: boolean }).open === true && !!book.concept.story?.trim()
      const fill = () => pitches.mutate({ jobId: job.id, action: 'fill', ...(picked ? { length: Number(picked.length.match(/\d+/)?.[0]) } : {}) })
      return <Bar tone="wait" title={canFill && !picked ? '定调有了：可以让编辑部补齐开书稿' : '待你选择：三个故事方向'} onTitle={goTarget} error={pitches.error}
        detail={picked ? `已选「${picked.name}」· ${picked.length}${picked.title.trim() ? ` ·《${picked.title.trim()}》` : ''} · 选好后编辑部一口气写出定调、设定和大纲，中间不停下来等你确认` : canFill ? '按现在的定调和设定把设定、大纲补齐；也可以挑一个故事方向，按那个方向写' : onTarget ? '在上面点选一个方向；都不满意，就在群聊里说想怎么改' : `主编推荐方向 ${pending.recommended}，篇幅和书名一起选`}>
        {canFill && <Button variant={picked ? 'outline' : 'seal'} loading={setupPending && pitches.variables?.action === 'fill'} disabled={setupPending} onClick={fill}>补齐开书稿</Button>}
        {picked ? <Button variant="seal" loading={setupPending && pitches.variables?.action === 'pick'} disabled={setupPending} onClick={pick}>用这个方向</Button>
          : !onTarget ? <Button variant={canFill ? 'outline' : 'seal'} onClick={resumeFollow}>去挑方向</Button>
            : !canFill && <Button variant="outline" onClick={requestFeedback}>在群聊里说</Button>}
      </Bar>
    }

    if (pending.kind === 'setup_directions') return <Bar tone="wait" title="待你选择：开书方向" onTitle={goTarget} detail="去概览挑一个方向">
      {!onTarget && <Button variant="seal" onClick={resumeFollow}>去选择</Button>}
    </Bar>

    if (pending.kind === 'setup_piece') {
      const flow3 = job.setup_flow === 3
      const name = flow3 ? pending.piece === 'settings' ? '定调和设定' : pending.piece === 'concept' ? '定调' : '大纲' : setupPieces(job.setup_flow).find(item => item.key === pending.piece)?.name ?? ''
      const review = pending.review ?? []
      const warnings = [...(pending.warnings ?? []), ...(pending.concept_warnings ?? [])]
      const reminders = warnings.length + review.length + count(pending.suggestions) + count(pending.unlock_requests)
      const decided = count(pending.decisions) + count(pending.concept_decisions)
      const confirm = async (action: 'confirm' | 'delegate') => {
        if (setupPending) return
        try {
          if (action === 'confirm') resumeFollow()
          if (flow3 && pending.piece === 'outline') await confirmSetupAndWrite.mutateAsync({ jobId: job.id, action, book })
          else await pieceAction.mutateAsync({ jobId: job.id, action, piece: pending.piece })
          if (pending.piece === 'first_volume') celebrate()
        } catch { /* 失败保留待确认内容和错误。 */ }
      }
      const detail = [reminders ? `${reminders} 条提醒` : '', decided ? `主编替你定了 ${decided} 处，页面最上面可以改` : '', !reminders && !decided ? onTarget ? '看完没问题就确认；想改就提意见，或在群聊里直接说' : '先去看看' : ''].filter(Boolean).join(' · ')
      const panel = reminders ? <ul className="space-y-3">
        {warnings.map((warning, index) => <li key={`warning-${index}`}><span className="mr-2 text-xs text-seal">提醒</span>{warning}</li>)}
        {review.map((issue, index) => <li key={`review-${index}`}><span className="mr-2 text-xs text-chief">审稿</span>{issue.problem}——{issue.suggestion}</li>)}
        {pending.suggestions?.map((suggestion, index) => <li key={`suggestion-${index}`}><span className="mr-2 text-xs text-chief">审稿建议</span>{suggestion.problem}<p className="mt-1">{suggestion.suggestion}</p>
          {!flow3 && <Button size="sm" variant="ghost" className="mt-1" disabled={pieceAction.isPending} onClick={() => pieceAction.mutate({ jobId: job.id, action: 'unlock', piece: targetPiece[suggestion.target], feedback: `${suggestion.problem}\n${suggestion.suggestion}` })}>解锁并修改</Button>}</li>)}
        {pending.unlock_requests?.map((request, index) => <li key={`unlock-${index}`}><span className="mr-2 text-xs text-chief">解锁请求</span>{request.reason}
          {!flow3 && <div><Button size="sm" variant="ghost" className="mt-1" disabled={pieceAction.isPending} onClick={() => pieceAction.mutate({ jobId: job.id, action: 'unlock', piece: targetPiece[request.target], feedback: request.reason })}>解锁并修改</Button></div>}</li>)}
      </ul> : undefined
      return <Bar tone="wait" title={`待你确认：${name}`} onTitle={goTarget} detail={detail} panel={panel} panelLabel="看提醒" error={pieceAction.error ?? confirmSetupAndWrite.error}>
        <Button variant="outline" disabled={setupPending} onClick={requestFeedback}>提意见</Button>
        {!flow3 && <Button variant="ghost" disabled={setupPending} loading={pieceAction.isPending && pieceAction.variables?.action === 'delegate'} onClick={() => void confirm('delegate')}>交给编辑部定</Button>}
        <Button variant="seal" disabled={setupPending} loading={setupPending && pieceAction.variables?.action !== 'delegate'} onClick={() => void confirm('confirm')}>
          {flow3 ? pending.piece === 'outline' ? '确认，开写' : pending.piece === 'concept' ? '确认，去建设定' : '确认，去出大纲' : '确认这一块'}
        </Button>
      </Bar>
    }

    if (pending.kind === 'segment_review') {
      const act = async (action: 'confirm' | 'delegate' | 'redo') => { try { await segmentReview.submit({ action }) } catch { /* 保留下一篇和作者意见，允许重试。 */ } }
      const warnings = pending.warnings ?? []
      return <Bar tone="wait" title={`待你确认：第 ${pending.number} 篇`} onTitle={goTarget} error={segmentReview.error}
        detail={pending.flow === 2 ? '这一篇是按旧写法规划的，要按新写法重出一次' : warnings.length ? `${warnings.length} 条提醒` : '确认后照常拆卷纲；想改就提意见'}
        panel={warnings.length ? <ul aria-label="下一篇的提醒" className="space-y-2">{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : undefined} panelLabel="看提醒">
        {pending.flow === 2
          ? <Button variant="seal" disabled={segmentReview.submitting} loading={segmentReview.submitting} onClick={() => void act('redo')}>按新写法重出</Button>
          : <>
            <Button variant="outline" disabled={segmentReview.submitting} onClick={requestFeedback}>提意见</Button>
            <Button variant="ghost" loading={segmentReview.submitting && segmentReview.action === 'delegate'} disabled={segmentReview.submitting} onClick={() => void act('delegate')}>交给编辑部定</Button>
            <Button variant="seal" loading={segmentReview.submitting && segmentReview.action === 'confirm'} disabled={segmentReview.submitting} onClick={() => void act('confirm')}>确认这一篇</Button>
          </>}
      </Bar>
    }

    const copy = decisionCopy(pending, bookId)
    const volume = pending.kind === 'volume_review' ? pending : null
    const conflicts = [...new Set([...(volume?.issues ?? []).filter(issue => /^节点冲突[：:]/.test(issue)), ...(volume?.node_conflict ? [`节点冲突：${volume.node_conflict}`] : [])])]
    const issues = (pending.kind === 'volume_review' || pending.kind === 'chapter_stuck' ? copy.issues ?? [] : []).filter(issue => !/^节点冲突[：:]/.test(issue) && !(volume?.node_update && issue.startsWith('节点调整：')))
    const approve = async () => {
      if (decisionPending) return
      try { await decide.mutateAsync({ jobId: job.id, action: 'approve' }); celebrate() } catch { /* ErrorText 保留失败；没成功不盖章。 */ }
    }
    const notes = conflicts.length + issues.length + (volume?.node_update ? 1 : 0)
    return <Bar tone="wait" title={`待你拍板：${label ?? '开书方案'}`} onTitle={goTarget} error={decide.error}
      detail={notes ? `${notes} 条提醒${conflicts.length ? '，其中有节点冲突' : ''}` : onTarget ? copy.hint : '先去看看'}
      panel={<div className="space-y-3">
        <p>{copy.hint}</p>
        {conflicts.map((conflict, index) => <div key={index} role="alert" className="flex items-start gap-2 rounded-lg border border-reviewer/35 bg-reviewer-soft px-3 py-2 text-seal-dark"><AlertTriangle className="mt-0.5 size-4 shrink-0" /><p>{conflict}</p></div>)}
        {volume?.node_update && <NodeUpdateComparison proposal={volume.node_update} />}
        {!!issues.length && <ul aria-label="卷纲与章节提醒" className="space-y-1.5">{issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
      </div>} panelLabel={notes ? '看提醒' : '说明'}>
      <Button variant="outline" onClick={requestFeedback}>提意见</Button>
      <Button variant="seal" onClick={() => void approve()} disabled={decisionPending} loading={decide.isPending && decide.variables?.action === 'approve'}><Stamp className="size-3.5" />{copy.approve}</Button>
    </Bar>
  }
}
