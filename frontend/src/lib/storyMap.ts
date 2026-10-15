import type { StoryNode } from '../api/types'

export const NODE_STATUS: Record<StoryNode['status'], string> = { pinned: '铁钉', pencil: '暂定', empty: '留空' }

export interface SpineArtifactNode {
  kind: StoryNode['kind']
  title: string
  event: string
  volume: number | null
  prerequisite?: string
  consequence?: string
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
      const kind = node.kind === 'opening' || node.kind === '开篇' ? 'opening' : node.kind === 'ending' || node.kind === '结局' ? 'ending' : 'milestone'
      return {
        kind,
        title: text(node.title) || (kind === 'opening' ? '开篇' : kind === 'ending' ? '结局' : '（未命名节点）'),
        event: text(node.event),
        volume: typeof node.volume === 'number' ? node.volume : null,
        ...(text(node.prerequisite) ? { prerequisite: text(node.prerequisite) } : {}),
        ...(text(node.consequence) ? { consequence: text(node.consequence) } : {}),
      }
    })
  }
  const nodes: SpineArtifactNode[] = []
  if (text(spine.opening)) nodes.push({ kind: 'opening', title: '开篇', event: text(spine.opening), volume: null })
  if (Array.isArray(spine.milestones)) {
    for (const item of [...spine.milestones].sort((a, b) => Number(object(a).index ?? 0) - Number(object(b).index ?? 0))) {
      const node = object(item)
      nodes.push({ kind: 'milestone', title: text(node.title) || '（未命名节点）', event: text(node.event), volume: typeof node.volume === 'number' ? node.volume : null, ...(text(node.change) ? { consequence: text(node.change) } : {}) })
    }
  }
  if (text(spine.ending)) nodes.push({ kind: 'ending', title: '结局', event: text(spine.ending), volume: null })
  return nodes
}

const rows = (value: unknown) => Array.isArray(value) ? value.filter(item => item && typeof item === 'object').map(object) : []
const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null

/** 新旧产出都可能缺某一组字段；只格式化快照，不补造事实或编号。 */
export function loreArtifact(data: unknown) {
  const lore = object(data)
  return {
    characters: rows(lore.characters).map(c => ({ name: text(c.name), role_type: text(c.role_type), abilities: text(c.abilities) })),
    world_entries: rows(lore.world_entries).map(w => ({ name: text(w.name) })),
    anchors: rows(lore.anchors).map(a => ({ character: text(a.character) || text(a.character_name), node: number(a.node), kind: text(a.kind), note: text(a.note) })),
    secrets: rows(lore.secrets).map(s => ({
      code: text(s.code) || (number(s.seq) ? `S${s.seq}` : ''), title: text(s.title), truth: text(s.truth),
      knowers: Array.isArray(s.knowers) ? s.knowers.map(k => typeof k === 'string' ? k : text(object(k).name)).filter(Boolean) : [],
      reader_knows: text(s.reader_knows) || '未标注', reveal_plan: text(s.reveal_plan),
    })),
  }
}

export function outlineArtifact(data: unknown) {
  const outline = object(data)
  const ledger = (value: unknown, prefix: string) => rows(value).map(f => ({
    code: text(f.code) || (number(f.seq) ? `${prefix}${f.seq}` : ''), description: text(f.description),
    plant_volume: number(f.plant_volume), payoff_volume: number(f.payoff_volume),
  }))
  return {
    volumes: rows(outline.volumes).map((v, i) => ({ index: number(v.index) ?? i + 1, title: text(v.title), summary: text(v.summary), stage: text(v.stage), chapter_count: number(v.chapter_count), target_node: number(v.target_node), reaches_node: v.reaches_node === true })),
    foreshadowings: ledger(outline.foreshadowings, 'F'), expectations: ledger(outline.expectations, 'E'),
  }
}

export function directionsArtifact(data: unknown) {
  const draft = object(data)
  return rows(draft.directions).map(d => ({
    name: text(d.name), logline: text(d.logline), protagonist: text(d.protagonist), golden_finger: text(d.golden_finger),
    opening: text(d.opening), stage_ladder: text(d.stage_ladder), tone: text(d.tone), reader: text(d.reader), difference: text(d.difference),
    selling_points: Array.isArray(d.selling_points) ? d.selling_points.filter((p): p is string => typeof p === 'string') : [],
  }))
}
