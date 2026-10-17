import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { post } from '../../../api/client'
import { useBible, useChapters, useJobActions, useNodes } from '../../../api/hooks'
import { useInvalidateLibrary } from '../../../api/library'
import { usePlanSegment } from '../../../api/segmentPlanning'
import type { ChapterBrief, PlotUnit, Volume } from '../../../api/types'
import { EmotionCurve } from '../../../components/EmotionCurve'
import { ForeshadowChips } from '../../../components/ForeshadowChips'
import { EditorAnnotations, RevealChips } from '../../../components/WritingLabels'
import { Button, ErrorText } from '../../../components/ui'
import { nextOutlineUnit, outlineReviewMatches } from '../../../lib/outlineWriting'
import { unitStarted, volumeStarted, type OutlineItem, type OutlineTree } from '../../../lib/outlineTree'
import { canPlanNextSegment, segmentBands } from '../../../lib/storyMap'
import { useBookContext } from '../context'
import { NodeUpdateComparison } from '../Decision'

export function OutlineChapterCards({ chapters }: { chapters: ChapterBrief[] }) {
  const { bookId, manualNavigate } = useBookContext()
  const { data: bible } = useBible(bookId)
  return <div className="space-y-3" data-testid="unit-chapter-outlines">{chapters.map(chapter => <article key={chapter.id} className="rounded-lg border border-line bg-paper/50 p-3"><h4 className="font-serif font-bold">第 {chapter.index} 章 · {chapter.title}</h4>{[['要完成的剧情', chapter.outline?.goal], ['场景', chapter.outline?.scenes?.join('\n')], ['爽点', chapter.outline?.cool_point], ['钩子', chapter.outline?.hook]].map(([label, text]) => text && <p key={label} className="mt-2 whitespace-pre-wrap text-sm leading-7"><span className="mr-2 text-xs text-ink-2">{label}</span>{text}</p>)}<ForeshadowChips actions={chapter.outline?.foreshadow_actions ?? []} ledger={bible?.foreshadowings ?? []} /><RevealChips reveals={chapter.outline?.reveals} />{chapter.status !== 'planned' && <Button size="sm" variant="ghost" className="mt-2" onClick={() => manualNavigate(`/books/${bookId}/chapter/${chapter.index}`)}>去看正文</Button>}</article>)}</div>
}

function UnitDetails({ unit, chapters }: { unit: PlotUnit; chapters: ChapterBrief[] }) {
  const { bookId } = useBookContext()
  const { data: bible } = useBible(bookId)
  return <div className="space-y-4">
    {!!unit.plan_issues?.length && <section data-testid="unit-plan-issues" className="rounded-lg border border-reviewer/30 bg-reviewer-soft p-3 text-sm"><h4 className="font-medium">章纲还有 {unit.plan_issues.length} 处节奏问题</h4><ul className="mt-2 list-disc space-y-2 pl-4">{unit.plan_issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul></section>}
    <EmotionCurve chapters={chapters} />
    <dl className="grid gap-4 @lg/manuscript:grid-cols-2">{[['目标', unit.goal], ['冲突', unit.conflict], ['高潮与爽点', unit.climax], ['结果与钩子', unit.outcome], ['核心循环', unit.loop]].map(([label, value]) => <div key={label}><dt className="mb-1 text-xs text-ink-2">{label}</dt><dd className="whitespace-pre-wrap text-sm leading-7">{value || '（还没写）'}</dd></div>)}</dl>
    <section><h4 className="mb-2 text-xs text-ink-2">关键事件</h4><ol className="list-decimal space-y-1 pl-5 text-sm leading-7">{unit.key_events.map((event, index) => <li key={index}>{event}</li>)}</ol></section>
    {!!unit.thread_beats.length && <section><h4 className="mb-2 text-xs text-ink-2">推进线索</h4>{unit.thread_beats.map((step, index) => <p key={index} className="text-sm leading-7"><span className="mr-2 text-chief">{step.thread}</span>{step.beat}</p>)}</section>}
    {!!unit.tropes?.length && <section><h4 className="mb-2 text-xs text-ink-2">套路与破局</h4><p className="text-sm leading-7">{unit.tropes.join('、')}</p></section>}{unit.resolution && <p className="text-sm leading-7">破局 · {unit.resolution}</p>}
    <ForeshadowChips actions={unit.foreshadow_actions} ledger={bible?.foreshadowings ?? []} /><RevealChips reveals={unit.reveals} />
    <EditorAnnotations note={unit.editor_note} techniques={unit.techniques} />
    {unit.recap && <section><h4 className="mb-2 text-xs text-lore">单元回顾</h4><p className="whitespace-pre-wrap text-sm leading-7">{unit.recap}</p></section>}
  </div>
}

function VolumeDetails({ volume }: { volume: Volume }) {
  const { bookId, manualNavigate } = useBookContext()
  const { data: nodes = [] } = useNodes(bookId)
  const target = nodes.find(node => node.id === volume.target_node_id)
  return <div className="space-y-4">{target && <section aria-label="本卷走向" className="flex flex-wrap items-center gap-2 text-sm"><span className="text-ink-2">走向：</span><button className="text-chief underline underline-offset-4" onClick={() => manualNavigate(`/books/${bookId}/outline?view=map#story-node-${target.id}`)}>节点 {target.index}「{target.title}」</button><span className="text-xs">{target.status === 'pinned' ? '已锁' : '没锁'}</span>{volume.reaches_node && <span className="text-xs text-seal">本卷发生</span>}</section>}
    <dl className="space-y-3">{[['舞台', volume.stage], ['想做成什么', volume.want], ['压力', volume.pressure], ['卷末高潮', volume.climax], ['卷末结果', volume.goal], ['对手', volume.antagonist], ['成长', volume.power_range]].map(([label, value]) => value && <div key={label}><dt className="mb-1 text-xs text-ink-2">{label}</dt><dd className="whitespace-pre-wrap text-sm leading-7">{value}</dd></div>)}</dl>
    {!!volume.thread_beats.length && <section><h4 className="mb-2 text-xs text-ink-2">本卷推进的线索</h4>{volume.thread_beats.map((step, index) => <p key={index} className="text-sm leading-7"><span className="mr-2 text-chief">{step.thread}</span>{step.beat}</p>)}</section>}
    <EditorAnnotations note={volume.editor_note} techniques={volume.techniques} />{volume.recap && <section><h4 className="mb-2 text-xs text-lore">卷回顾</h4><p className="whitespace-pre-wrap text-sm leading-7">{volume.recap}</p></section>}
  </div>
}

export function OutlineWritingDetails({ item }: { item: Extract<OutlineItem, { kind: 'volume' | 'unit' }> }) {
  const { bookId, outline, job } = useBookContext()
  const chapters = useChapters(bookId, item.volume.index)
  const volume = outline?.volumes.find(volume => volume.id === item.volume.id)
  const unit = item.kind === 'unit' ? volume?.units.find(unit => unit.id === item.unit.id) : null
  const own = chapters.data?.filter(chapter => chapter.unit_id === unit?.id) ?? []
  const pending = job?.status === 'waiting_author' ? job.pending : null
  const reviewing = outlineReviewMatches(item, pending)
  return <div className="space-y-5">
    <details className="rounded-lg border border-line bg-paper/40 p-3" data-testid="outline-writing-details"><summary className="cursor-pointer text-sm font-medium">细节</summary><div className="mt-4">{unit ? <UnitDetails unit={unit} chapters={own} /> : volume ? <VolumeDetails volume={volume} /> : <p className="text-sm text-ink-2">正在读取细节…</p>}</div></details>
    {item.kind === 'unit' && own.length > 0 && <section><h3 className="mb-3 font-serif font-bold">章纲{reviewing && <span className="ml-2 text-xs text-chief">待你确认</span>}</h3><OutlineChapterCards chapters={own} /></section>}
    {reviewing && item.kind === 'volume' && <section className="space-y-3" aria-label="待确认的单元"><h3 className="font-serif font-bold">单元 · 待你确认</h3>{item.volume.units.map(unit => <article key={unit.id} className="rounded-lg border border-line p-3"><h4 className="font-medium">{unit.title}<span className="ml-2 text-xs font-normal text-ink-2">{unit.chapter_count} 章</span></h4><p className="mt-2 whitespace-pre-wrap text-sm leading-7">{unit.summary}</p></article>)}</section>}
    {reviewing && pending?.kind === 'volume_review' && <><ul className="space-y-2 text-sm text-seal">{[...new Set([...(pending.issues ?? []), ...(pending.node_conflict ? [pending.node_conflict] : [])])].map((issue, index) => <li key={index}>{issue}</li>)}</ul>{pending.node_update && <NodeUpdateComparison proposal={pending.node_update} />}</>}
    {reviewing && <OutlineReviewFooter />}
    <ErrorText error={chapters.error} />
  </div>
}

function OutlineReviewFooter() {
  const { bookId, job, requestFeedback, celebrate } = useBookContext()
  const { decide, decisionPending } = useJobActions(bookId)
  return <footer className="space-y-3 border-t border-line pt-5"><div className="flex flex-wrap gap-2"><Button variant="seal" disabled={decisionPending} loading={decide.isPending} onClick={async () => { if (!job || decisionPending) return; try { await decide.mutateAsync({ jobId: job.id, action: 'approve' }); celebrate() } catch { /* 保留本轮等待。 */ } }}>批准开写</Button><Button variant="ghost" disabled={decisionPending} onClick={requestFeedback}>提意见</Button></div><ErrorText error={decide.error} /></footer>
}

export function ExpandOutline({ item, tree }: { item: OutlineItem; tree: OutlineTree }) {
  const { bookId, book, job, outline, working, resumeFollow } = useBookContext()
  const { data: nodes = [] } = useNodes(bookId)
  const { data: chapters = [] } = useChapters(bookId)
  const invalidate = useInvalidateLibrary(bookId)
  const expand = useMutation({ mutationKey: ['outline-expand', bookId], mutationFn: (target: { kind: 'volume' | 'unit'; id: string }) => post(`/${target.kind === 'volume' ? 'volumes' : 'units'}/${target.id}/expand`), onSettled: invalidate })
  const plan = usePlanSegment(bookId)
  const [notice, setNotice] = useState('')
  const busy = working || expand.isPending || plan.isPending || job?.status === 'waiting_author'
  const eligible = item.kind === 'volume' && !item.volume.units.length && !volumeStarted(item.volume) || item.kind === 'unit' && item.unit.id === nextOutlineUnit(tree) && !item.unit.chapters.length && !unitStarted(item.unit)
  const planning = item.kind === 'segment' && !!item.arc.node_id && canPlanNextSegment(book.status, job?.status, segmentBands(nodes, outline?.volumes ?? [], chapters), item.arc.node_id)
  if (!eligible && !planning) return null
  return <section className="space-y-2 border-t border-line pt-4">{eligible && (item.kind === 'volume' || item.kind === 'unit') && <Button size="sm" variant="soft" disabled={busy} loading={expand.isPending} onClick={async () => { setNotice(''); try { await expand.mutateAsync({ kind: item.kind, id: item.kind === 'unit' ? item.unit.id : item.volume.id }); setNotice('已经展开，可以在大纲里查看和修改。') } catch { /* 展开失败不动原稿。 */ } }}>展开这一个</Button>}{planning && <Button size="sm" variant="soft" disabled={busy} loading={plan.isPending} onClick={async () => { try { await plan.mutateAsync(); resumeFollow() } catch { /* 错误保留在此。 */ } }}>现在就规划下一篇</Button>}{notice && <p role="status" className="text-xs text-lore">{notice}</p>}<ErrorText error={expand.error ?? plan.error} /></section>
}
