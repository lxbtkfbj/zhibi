import type { StoryNode } from '../api/types'

export const NODE_STATUS: Record<StoryNode['status'], string> = { pinned: '铁钉', pencil: '暂定', empty: '留空' }

export interface SpineArtifactNode {
  kind: StoryNode['kind']
  title: string
  event: string
  volume: number | null
}

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const text = (value: unknown) => typeof value === 'string' ? value : ''

/** 会议记录是历史快照：兼容旧开篇 / 转折 / 结局，不拿当前节点覆盖旧稿。 */
export function spineArtifactNodes(data: unknown): SpineArtifactNode[] {
  const spine = object(data)
  if (Array.isArray(spine.nodes)) {
    return spine.nodes.map((item) => {
      const node = object(item)
      const kind = node.kind === 'opening' || node.kind === 'ending' ? node.kind : 'milestone'
      return {
        kind,
        title: text(node.title) || (kind === 'opening' ? '开篇' : kind === 'ending' ? '结局' : '（未命名节点）'),
        event: text(node.event),
        volume: typeof node.volume === 'number' ? node.volume : null,
      }
    })
  }
  const nodes: SpineArtifactNode[] = []
  if (text(spine.opening)) nodes.push({ kind: 'opening', title: '开篇', event: text(spine.opening), volume: null })
  if (Array.isArray(spine.milestones)) {
    for (const item of [...spine.milestones].sort((a, b) => Number(object(a).index ?? 0) - Number(object(b).index ?? 0))) {
      const node = object(item)
      nodes.push({ kind: 'milestone', title: text(node.title) || '（未命名节点）', event: text(node.event), volume: typeof node.volume === 'number' ? node.volume : null })
    }
  }
  if (text(spine.ending)) nodes.push({ kind: 'ending', title: '结局', event: text(spine.ending), volume: null })
  return nodes
}
