import clsx from 'clsx'
import { Check, ChevronDown } from 'lucide-react'
import type { ChapterBrief, SegmentPlan, Volume } from '../api/types'
import { plannedVolumeChapters, type SegmentBand, type WritingPosition } from '../lib/storyMap'
import { EditableText } from './Editable'
import { FactTable } from './FactTable'
import { Button } from './ui'

const statusLabels = { done: '已写完', writing: '正在写', planned: '已规划', later: '写到再定' } as const

export function WritingSegmentBand({ band, position, chapterList, locked, onSave, onVolumeSelect, onPlan }: {
  band: SegmentBand
  position: WritingPosition
  chapterList: ChapterBrief[]
  locked: boolean
  onSave: (patch: Partial<SegmentPlan>) => Promise<unknown>
  onVolumeSelect: (volume: Volume) => void
  onPlan?: () => void
}) {
  const { number, plan, volumes, chapters, status, auto } = band
  if (!plan) return <section data-testid="unplanned-segment" data-segment-end={band.to.id} className="mt-4 rounded-lg border border-dashed border-line-2 bg-paper/40 p-3 text-sm leading-relaxed text-ink-2">
    <p>写到再定 · 写到这里之前，主编会先来定下一篇</p>
    {onPlan && <Button type="button" size="sm" variant="soft" className="mt-3" disabled={locked} onClick={onPlan}>现在就规划下一篇</Button>}
  </section>
  const first = volumes[0]?.index
  const last = volumes.at(-1)?.index
  // 横向地图在首章定稿前不显示，但正在写首章的段带仍要显示本卷 0/N 章。
  const activeVolume = volumes.find(volume => volume.index === position.volume)
    ?? volumes.find(volume => chapterList.some(chapter => chapter.volume_id === volume.id && chapter.status === 'drafting'))
  const doneInVolume = activeVolume ? chapterList.filter(chapter => chapter.volume_id === activeVolume.id && chapter.status === 'final').length : 0
  return <details className={clsx('group/segment mt-4 rounded-lg border text-sm', status === 'writing' ? 'border-chief/45 bg-chief-soft/30' : 'border-line bg-paper/70')} data-testid="writing-segment-band" data-segment-number={number} data-segment-status={status}>
    <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-3 focus-visible:outline-2 focus-visible:outline-chief">
      <ChevronDown className="size-4 shrink-0 text-chief transition-transform group-open/segment:rotate-180 motion-reduce:transition-none" />
      <span className="font-medium">第 {number} 篇{first != null && <> · 第 {first === last ? first : `${first}-${last}`} 卷</>} · 约 {chapters} 章</span>
      <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs', status === 'done' ? 'bg-lore-soft text-lore' : status === 'writing' ? 'bg-chief-soft text-chief' : 'bg-line/65 text-ink-2')}>{status === 'done' && <Check className="size-3" />}{statusLabels[status]}</span>
      {auto && <span className="rounded-full border border-chief/25 px-2 py-0.5 text-xs text-chief">自动通过</span>}
      {status === 'writing' && activeVolume && <span className="basis-full pl-6 text-xs font-medium text-chief">正在写：第 {activeVolume.index} 卷 {doneInVolume}/{plannedVolumeChapters(activeVolume)} 章</span>}
    </summary>
    <div className="space-y-5 border-t border-line p-3 @lg/manuscript:p-4">
      {plan.text ? <div><p className="mb-2 font-serif text-base font-bold">{plan.title}</p><EditableText value={plan.text} locked={locked} multiline onSave={text => onSave({ text })} /></div> : <><FactTable rows={([
        ['goal', '目标'], ['wait', '读者在等'], ['reveal', '揭开什么'], ['map', '地图'],
      ] as const).map(([field, label]) => ({ label, value: <EditableText value={plan[field] ?? ''} locked={locked} multiline onSave={value => onSave({ [field]: value })} /> }))} />
      <details className="group/context rounded-lg border border-line bg-card/50 p-3">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-xs text-ink-2"><ChevronDown className="size-3.5 transition-transform group-open/context:rotate-180 motion-reduce:transition-none" />定下一篇时的四件事</summary>
        <div className="mt-4"><FactTable rows={([
          ['carried', '上一篇的线头'], ['pursuit', '主角的追求'], ['finger_next', '金手指下一阶段'], ['answers', '定下的谜底'],
        ] as const).map(([field, label]) => ({ label, value: <p className="whitespace-pre-wrap">{plan[field] || '（暂无）'}</p> }))} /></div>
      </details></>}
      <div className="space-y-2">{volumes.map(volume => <button type="button" key={volume.id} onClick={() => onVolumeSelect(volume)} className="block w-full rounded-lg border border-line bg-card p-3 text-left hover:border-chief/50 focus-visible:outline-2 focus-visible:outline-chief">
        <span className="flex flex-wrap justify-between gap-2"><span className="font-serif font-bold text-ink">第 {volume.index} 卷 · {volume.title}</span><span className="text-xs text-ink-2">约 {plannedVolumeChapters(volume)} 章 →</span></span>
        <span className="mt-1 block text-ink-2">{volume.summary || `卷末目标：${volume.goal || volume.climax || '待确定'}`}</span>
      </button>)}</div>
    </div>
  </details>
}
