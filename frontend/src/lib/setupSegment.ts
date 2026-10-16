import type { Job, SegmentPlan, StoryNode, Volume } from '../api/types'

export const OPENING_FIELDS = [
  ['scene', '第 1 章的切入场面'],
  ['pressure', '前 3 章被什么压着'],
  ['first_win', '第一个小爽点'],
  ['finger', '金手指露头'],
  ['hook', '第 3 章的钩子'],
] as const satisfies readonly [keyof NonNullable<SegmentPlan['opening']>, string][]

/** 以真实节点上的段信息为准；不能把旧书的第二个节点臆测成第一段。 */
export function firstSegment(nodes: StoryNode[], volumes: Volume[] = []) {
  const ordered = [...nodes].sort((a, b) => a.index - b.index)
  const endpoint = ordered.find(node => node.segment?.number === 1) ?? ordered.find(node => node.segment) ?? null
  const endAt = endpoint ? ordered.findIndex(node => node.id === endpoint.id) : -1
  return {
    endpoint,
    opening: ordered.find(node => node.kind === 'opening') ?? null,
    ending: ordered.find(node => node.kind === 'ending') ?? null,
    castNodes: endAt < 0 ? [] : ordered.slice(0, endAt + 1),
    distant: endAt < 0 ? [] : ordered.slice(endAt + 1).filter(node => node.kind !== 'ending'),
    volumes: endpoint ? [...volumes].filter(volume => volume.target_node_id === endpoint.id).sort((a, b) => a.index - b.index) : [],
  }
}

export function showFirstSegment(nodes: StoryNode[], current: string | null | undefined, job: Job | null | undefined) {
  return nodes.some(node => !!node.segment) || (job?.kind === 'book_setup' &&
    ((['queued', 'running'].includes(job.status) && current === 'segment') ||
      (job.status === 'waiting_author' && job.pending?.kind === 'setup_piece' && job.pending.piece === 'segment')))
}

/** 仅区间未规划时显示静态占位，不引入任务 5 的分段状态或操作。 */
export function isUnplannedSegment(from: StoryNode, to: StoryNode | null, nodes: StoryNode[]) {
  const endpoint = firstSegment(nodes).endpoint
  return !!endpoint && from.index >= endpoint.index && !!to && !to.segment
}
