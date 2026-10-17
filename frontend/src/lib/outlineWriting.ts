import type { Pending, StoryNode } from '../api/types'
import type { OutlineItem, OutlineTree } from './outlineTree'
import { flattenOutline } from './outlineTree.ts'

export type PendingArc = Extract<Pending, { kind: 'segment_review' }>
/** 勾选只属于当前书、任务、篇和轮次。 */
export function segmentReviewKey(jobId: string | undefined, pending: Pending | null | undefined): string {
  return jobId && pending?.kind === 'segment_review' ? `${jobId}:${pending.number}:${pending.round}:${pending.flow}` : ''
}

/** 待确认是任务快照投影：只替换已有终点的那一篇；新终点插在已规划篇之后。 */
export function writingOutline(root: OutlineItem, pending: Pending | null, nodes: StoryNode[]): OutlineItem {
  if (pending?.kind === 'segment_review') {
    const candidate: OutlineItem = { key: 'pending', kind: 'pending', name: `第 ${pending.number} 篇${pending.flow === 3 ? ` · ${pending.plan.title}` : ''}`, status: 'pending', locked: pending.plan.end.status === 'pinned', pending, children: [] }
    const endpoint = nodes.find(node => node.index === pending.plan.end.ref)
    const replace = endpoint ? root.children.findIndex(item => item.kind === 'segment' && item.arc.node_id === endpoint.id) : -1
    const children = [...root.children]
    if (replace >= 0) children.splice(replace, 1, candidate)
    else {
      const after = children.findLastIndex(item => item.kind === 'segment' && item.arc.planned)
      children.splice(after + 1, 0, candidate)
      // 新终点是额外的一篇，后面的远景篇在投影视图中顺延，不能出现两个“第 N 篇”。
      for (let index = after + 2; index < children.length; index++) {
        const item = children[index]
        if (item.kind === 'segment' && /^第 \d+ 篇/.test(item.name)) children[index] = { ...item, name: item.name.replace(/^第 (\d+) 篇/, (_, number: string) => `第 ${Number(number) + 1} 篇`) }
      }
    }
    return { ...root, children }
  }
  const mark = (item: OutlineItem): OutlineItem => {
    const selected = pending?.kind === 'volume_review' && ((item.kind === 'volume' && item.volume.index === pending.volume) || (item.kind === 'unit' && item.volume.index === pending.volume)) || pending?.kind === 'chapters_review' && (item.kind === 'unit' && item.unit.id === pending.unit_id || item.kind === 'chapter' && item.chapter.index >= pending.first && item.chapter.index <= pending.last)
    return { ...item, ...(selected ? { status: 'pending' } : {}), children: item.children.map(mark) }
  }
  return mark(root)
}

export function nextOutlineUnit(tree: OutlineTree): string | null {
  const volumes = tree.arcs.flatMap(arc => arc.volumes).sort((a, b) => a.index - b.index)
  return volumes.flatMap(volume => [...volume.units].sort((a, b) => a.index - b.index)).find(unit => !unit.chapters.length)?.id ?? null
}

export function outlineReviewMatches(item: OutlineItem, pending: Pending | null) {
  return pending?.kind === 'volume_review' && item.kind === 'volume' && item.volume.index === pending.volume || pending?.kind === 'chapters_review' && item.kind === 'unit' && item.unit.id === pending.unit_id
}

/** 默认打开当前拍板处；显式点开的旧稿件位置优先，不把作者拉回等待节点。 */
export function selectOutlineItem(root: OutlineItem, requested: string | null, pending: Pending | null): OutlineItem {
  const items = flattenOutline(root)
  const explicit = requested === 'first-arc' ? root.children.find(item => item.kind === 'segment') : items.find(item => item.key === requested)
  const review = !requested ? items.find(item => item.kind === 'pending' || outlineReviewMatches(item, pending)) : undefined
  return explicit ?? review ?? root.children.find(item => item.kind === 'segment' && item.status === 'writing') ?? root.children[0] ?? root
}
