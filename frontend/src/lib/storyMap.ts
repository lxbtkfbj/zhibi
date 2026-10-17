import type { BookStatus, ChapterBrief, Concept, JobStatus, PieceKey, PieceStatus, SegmentPlan, SetupProgress, SetupTarget, StoryNode, Volume } from '../api/types'

export const PIECES = [
  { key: 'concept', name: '定调', path: '/concept', number: '①' },
  { key: 'protagonist', name: '主角', path: '/protagonist', number: '②' },
  { key: 'world', name: '世界与人', path: '/world', number: '③' },
  { key: 'segment', name: '第一段', path: '/spine', number: '④' },
  { key: 'first_volume', name: '第一卷', path: '/volume/1', number: '⑤' },
] as const satisfies readonly { key: PieceKey; name: string; path: string; number: string }[]

export const THREE_PIECES = [
  { key: 'concept', name: '定调', path: '/concept', number: '①' },
  { key: 'settings', name: '设定库', path: '/world', number: '②' },
  { key: 'outline', name: '大纲', path: '/spine', number: '③' },
] as const

export const setupPieces = (flow?: number | null) => flow === 3 ? THREE_PIECES : PIECES

export const PIECE_STATUS_LABELS: Record<PieceStatus, string> = {
  todo: '未开始', drafting: '正在做', waiting: '等你确认', confirmed: '已确认', done: '已做完',
}

export const targetPiece: Record<SetupTarget, PieceKey> = {
  concept: 'concept', protagonist: 'protagonist', world: 'world', segment: 'segment', volumes: 'segment', first_volume: 'first_volume',
}

/** 旧书没有进度时五块均未开始，不从产出或章数臆测确认状态。 */
export function pieceStatuses(progress: SetupProgress | null | undefined, flow?: number | null) {
  return {
    current: progress?.current ?? null,
    pieces: setupPieces(flow).map(piece => ({ ...piece, status: progress?.pieces?.[piece.key] ?? 'todo' as PieceStatus, current: piece.key === progress?.current })),
  }
}

export function nodeCounts(nodes: Pick<StoryNode, 'status'>[]) {
  return nodes.reduce((counts, node) => {
    counts.total += 1
    counts[node.status] += 1
    return counts
  }, { total: 0, pinned: 0, pencil: 0, empty: 0 })
}

export interface NodeSegment {
  from: StoryNode | null
  to: StoryNode | null
  volumes: Volume[]
  chapters: number
  unassigned: boolean
  unassignedVolumes: Volume[]
}

/** 目标节点是这一段的右端点。旧卷缺少目标时保留在最后一段，并明确标记。 */
export function segments(nodes: StoryNode[], volumes: Volume[]): NodeSegment[] {
  const ordered = [...nodes].sort((a, b) => a.index - b.index)
  const result: NodeSegment[] = ordered.slice(1).map((to, index) => ({ from: ordered[index], to, volumes: [], chapters: 0, unassigned: false, unassignedVolumes: [] }))
  if (!result.length && volumes.length) result.push({ from: ordered[0] ?? null, to: null, volumes: [], chapters: 0, unassigned: false, unassignedVolumes: [] })
  for (const volume of [...volumes].sort((a, b) => a.index - b.index)) {
    const matching = result.find(segment => !!volume.target_node_id && segment.to?.id === volume.target_node_id)
    const destination = matching ?? result.at(-1)
    if (!destination) continue
    destination.volumes.push(volume)
    destination.chapters += plannedVolumeChapters(volume)
    if (!matching) {
      destination.unassigned = true
      destination.unassignedVolumes.push(volume)
    }
  }
  return result
}


export const NODE_STATUS: Record<StoryNode['status'], string> = { pinned: '铁钉', pencil: '暂定', empty: '留空' }

/** 已拆单元以单元章数为准，不再沿用总纲的粗略章数。 */
export function plannedVolumeChapters(volume: Pick<Volume, 'chapter_count' | 'units'>): number {
  return volume.units?.length
    ? volume.units.reduce((sum, unit) => sum + Math.max(0, unit.chapter_count || 0), 0)
    : Math.max(0, volume.chapter_count || 0)
}

export interface SegmentBand {
  number: number | null
  from: StoryNode | null
  to: StoryNode
  plan: SegmentPlan | null
  volumes: Volume[]
  chapters: number
  status: 'done' | 'writing' | 'planned' | 'later'
  auto: boolean
}

/** 只把已经保存的段规划当作计划；旧书仍由 segments() 显示原来的卷带。 */
export function segmentBands(nodes: StoryNode[], volumes: Volume[], chapters: ChapterBrief[]): SegmentBand[] {
  if (!nodes.some(node => node.segment)) return []
  const ordered = [...nodes].sort((a, b) => a.index - b.index)
  return ordered.filter(node => node.kind !== 'opening').map(to => {
    const plan = to.segment ?? null
    const own = [...volumes].filter(volume => volume.target_node_id === to.id).sort((a, b) => a.index - b.index)
    const started = chapters.some(chapter => own.some(volume => volume.id === chapter.volume_id) && ['final', 'drafting'].includes(chapter.status))
    const done = own.length > 0 && own.every(volume => volumeWritingComplete(volume, chapters))
    return {
      number: plan?.number ?? null, from: ordered[ordered.indexOf(to) - 1] ?? null, to, plan,
      volumes: own, chapters: own.reduce((sum, volume) => sum + plannedVolumeChapters(volume), 0),
      status: !plan ? 'later' : done ? 'done' : started ? 'writing' : 'planned', auto: plan?.status === 'auto',
    }
  })
}

export function nextUnplanned(bands: SegmentBand[]): SegmentBand | null {
  return bands.find(band => band.status === 'later') ?? null
}

/** 等作者处理的任务同样占用编辑部，不能在拍板中另起一轮规划。 */
export function canPlanNextSegment(status: BookStatus, jobStatus: JobStatus | null | undefined, bands: SegmentBand[], nodeId: string): boolean {
  return ['ready', 'writing'].includes(status) && !['queued', 'running', 'waiting_author'].includes(jobStatus ?? '') &&
    !bands.some(band => band.to.kind === 'ending' && band.plan) && nextUnplanned(bands)?.to.id === nodeId
}

/** 分段规划没有列出全书卷卡片，剩余篇幅以概念中的计划估算；旧书保持原算法。 */
export function writingTotalChapters(nodes: StoryNode[], volumes: Volume[], concept?: Concept): number {
  const planned = volumes.reduce((sum, volume) => sum + plannedVolumeChapters(volume), 0)
  if (!nodes.some(node => node.segment)) return planned
  const words = concept?.chapter_words || 3000
  const intended = concept?.target_length ? Math.round(concept.target_length * 10000 / words) : 0
  return Math.max(planned, intended)
}

export interface WritingPosition {
  volume: number | null
  doneInVolume: number
  volumeChapters: number
  nextNode: StoryNode | null
  chaptersToNode: number | null
  passed: string[]
  ratio: number
}

function volumeWritingComplete(volume: Volume, chapters: ChapterBrief[]): boolean {
  const own = chapters.filter(chapter => chapter.volume_id === volume.id)
  // 重写中的旧卷可能仍保留 done，不能因此跳过正在写的卷或提前勾上节点。
  if (own.some(chapter => chapter.status !== 'final')) return false
  const planned = plannedVolumeChapters(volume)
  return volume.status === 'done' || (planned > 0 && own.length >= planned)
}

/** 计划章数可能偏少；比例达到 1 不代表仍有草稿或未写章节的书已经完结。 */
export function isWritingComplete(volumes: Volume[], chapters: ChapterBrief[], nodes: StoryNode[] = []): boolean {
  const last = [...volumes].sort((a, b) => a.index - b.index).at(-1)
  if (nodes.some(node => node.segment) && nodes.find(node => node.id === last?.target_node_id)?.kind !== 'ending') return false
  return volumes.length > 0 && chapters.some(chapter => chapter.status === 'final') &&
    chapters.every(chapter => chapter.status === 'final') && volumes.every(volume => volumeWritingComplete(volume, chapters))
}

/** 只报已经写完的卷所走向的段，不把远景节点或待确认方案算成已完成。 */
export function segmentFinishedText(nodes: StoryNode[], volumes: Volume[]): string {
  const last = [...volumes].sort((a, b) => a.index - b.index).at(-1)
  const end = nodes.find(node => node.id === last?.target_node_id)
    ?? [...nodes].sort((a, b) => a.index - b.index).findLast(node => node.segment)
  return `第 ${end?.segment?.number ?? nodes.filter(node => node.segment).length} 段写完了 · 下一段写到再定`
}

/** 只使用真实定稿与卷目标计算位置，不把预先生成的章纲算成已写。 */
export function writingPosition(nodes: StoryNode[], volumes: Volume[], chapters: ChapterBrief[], concept?: Concept): WritingPosition {
  const ordered = [...volumes].sort((a, b) => a.index - b.index)
  const finals = chapters.filter(chapter => chapter.status === 'final')
  const total = writingTotalChapters(nodes, ordered, concept)
  const done = (volume: Volume) => finals.filter(chapter => chapter.volume_id === volume.id).length
  const complete = (volume: Volume) => volumeWritingComplete(volume, chapters)
  const result: WritingPosition = {
    volume: null, doneInVolume: 0, volumeChapters: 0, nextNode: null, chaptersToNode: null, passed: [],
    ratio: total ? Math.min(1, finals.length / total) : 0,
  }
  if (!finals.length) return result

  result.passed = [...nodes].sort((a, b) => a.index - b.index).filter(node =>
    (node.kind === 'opening' && finals.some(chapter => chapter.index === 1)) ||
    ordered.some(volume => volume.target_node_id === node.id && volume.reaches_node && complete(volume)),
  ).map(node => node.id)
  const active = [...chapters].sort((a, b) => b.index - a.index).find(chapter => chapter.status === 'drafting' && ordered.some(volume => volume.id === chapter.volume_id))
  const last = [...finals].sort((a, b) => b.index - a.index).find(chapter => ordered.some(volume => volume.id === chapter.volume_id))
  let at = ordered.findIndex(volume => volume.id === (active ?? last)?.volume_id)
  if (at < 0) return result
  if (!active && complete(ordered[at]) && at + 1 < ordered.length) at += 1
  const current = ordered[at]
  result.volume = current.index
  result.doneInVolume = done(current)
  result.volumeChapters = plannedVolumeChapters(current)
  if (complete(current) && at === ordered.length - 1) return result
  result.nextNode = nodes.find(node => node.id === current.target_node_id) ?? null
  if (result.nextNode) {
    const lastTarget = ordered.findLastIndex(volume => volume.target_node_id === result.nextNode!.id)
    result.chaptersToNode = Math.max(0, ordered.slice(at, lastTarget + 1).reduce((sum, volume) => sum + plannedVolumeChapters(volume), 0) - result.doneInVolume)
  }
  return result
}

export function writingSegmentNumber(nodes: StoryNode[], volumes: Volume[], position: WritingPosition): number | null {
  const current = volumes.find(volume => volume.index === position.volume)
  return nodes.find(node => node.id === current?.target_node_id)?.segment?.number ?? null
}

export function writingPositionText(position: WritingPosition, volumes: Volume[], chapters: ChapterBrief[], nodes: StoryNode[] = []): string {
  if (position.volume == null) return ''
  const total = volumes.reduce((sum, volume) => sum + plannedVolumeChapters(volume), 0)
  const done = chapters.filter(chapter => chapter.status === 'final').length
  if (isWritingComplete(volumes, chapters, nodes)) return '全书完结'
  if (isWritingComplete(volumes, chapters)) return segmentFinishedText(nodes, volumes)
  const segment = writingSegmentNumber(nodes, volumes, position)
  const current = `${segment == null ? '' : `第 ${segment} 段 · `}第 ${position.volume} 卷 ${position.doneInVolume}/${position.volumeChapters} 章`
  if (position.nextNode) return `${current} · 离「${position.nextNode.title}」还有 ${position.chaptersToNode ?? 0} 章`
  // 历史卷没有目标节点时只呈现确实知道的章数，不臆测正在接近哪个节点。
  if (!volumes.some(volume => volume.target_node_id)) return `${current} · 全书已定稿 ${done}/${total} 章`
  return `${current} · 正在写最后一段，离结局还有 ${Math.max(0, total - done)} 章`
}

/** 未规划的远景在已规划章数与全书篇幅之间均分；这只是地图位置，不算已经走到。 */
export function storyMapNodeChapters(nodes: StoryNode[], volumes: Volume[], concept?: Concept): number[] {
  const ordered = [...volumes].sort((a, b) => a.index - b.index)
  let accumulated = 0
  const ends = ordered.map(volume => (accumulated += plannedVolumeChapters(volume)))
  const sorted = [...nodes].sort((a, b) => a.index - b.index)
  const segmented = sorted.some(node => node.segment)
  const total = writingTotalChapters(nodes, volumes, concept)
  const plannedThrough = sorted.findLastIndex(node => ordered.some(volume => volume.target_node_id === node.id))
  let previous = 0
  return sorted.map((node, index) => {
    if (segmented && node.kind !== 'opening' && index > plannedThrough) {
      return accumulated + (total - accumulated) * (index - Math.max(0, plannedThrough)) / Math.max(1, sorted.length - 1 - Math.max(0, plannedThrough))
    }
    let at = ordered.findLastIndex(volume => volume.target_node_id === node.id && volume.reaches_node)
    if (at < 0) at = ordered.findLastIndex(volume => volume.target_node_id === node.id)
    if (at < 0 && node.volume != null) at = ordered.findLastIndex(volume => volume.index <= node.volume!)
    const chapter = node.kind === 'opening' ? Math.min(1, accumulated)
      : node.kind === 'ending' ? total
        : at >= 0 ? ends[at] : accumulated * index / Math.max(1, sorted.length - 1)
    previous = Math.max(previous, chapter)
    return previous
  })
}

/** 返回节点序列里的连续坐标；例如 1.25 表示第二、三个节点之间的四分之一处。 */
export function storyMapWritingIndex(nodeChapters: number[], done: number, plannedThrough = nodeChapters.length - 1, complete = false): number {
  // 概念篇幅只是估计；实际写到结局并完成所有卷后，地图必须抵达结局，而非卡在估计章数中途。
  if (complete) return Math.max(0, nodeChapters.length - 1)
  if (nodeChapters.length < 2 || done < nodeChapters[0]) return 0
  for (let index = 1; index < nodeChapters.length; index += 1) {
    // 篇幅被作者缩短到已规划章数时，远景可能同点；也不能因此宣称走到未来节点。
    if (index > plannedThrough) return Math.max(0, plannedThrough)
    // 远景节点还没有卷卡片，当前位置最多停在最后一个已规划终点。
    if (!Number.isFinite(nodeChapters[index])) return index - 1
    if (done < nodeChapters[index]) {
      const before = nodeChapters[index - 1]
      return index - 1 + (done - before) / Math.max(1, nodeChapters[index] - before)
    }
  }
  return nodeChapters.length - 1
}

/** null 是省略号；窄稿件栏同样保留首尾与当前位置左右各两个节点。 */
export function visibleStoryMapNodes(nodes: StoryNode[], writingIndex: number, width: number): (StoryNode | null)[] {
  const ordered = [...nodes].sort((a, b) => a.index - b.index)
  if (ordered.length <= 8 && width >= 560) return ordered
  const left = Math.floor(Math.max(0, writingIndex))
  const keep = new Set([0, ordered.length - 1, left - 1, left, left + 1, left + 2])
  const result: (StoryNode | null)[] = []
  let previous = -1
  ordered.forEach((node, index) => {
    if (!keep.has(index)) return
    if (previous >= 0 && index > previous + 1) result.push(null)
    result.push(node)
    previous = index
  })
  return result
}

export interface SpineArtifactNode {
  kind: StoryNode['kind']
  title: string
  event: string
  volume: number | null
  prerequisite?: string
  consequence?: string
  editor_note?: string
  techniques?: string[]
}

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const text = (value: unknown) => typeof value === 'string' ? value : ''
const editorialMeta = (value: Record<string, unknown>) => ({
  ...(text(value.editor_note) ? { editor_note: text(value.editor_note) } : {}),
  ...(Array.isArray(value.techniques) ? { techniques: value.techniques.filter((item): item is string => typeof item === 'string') } : {}),
})

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
        ...editorialMeta(node),
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
    volumes: rows(outline.volumes).map((v, i) => ({ index: number(v.index) ?? i + 1, title: text(v.title), summary: text(v.summary), stage: text(v.stage), chapter_count: number(v.chapter_count), target_node: number(v.target_node), reaches_node: v.reaches_node === true, ...editorialMeta(v) })),
    foreshadowings: ledger(outline.foreshadowings, 'F'), expectations: ledger(outline.expectations, 'E'),
  }
}

export function directionsArtifact(data: unknown) {
  const draft = object(data)
  return rows(draft.directions).map(d => ({
    name: text(d.name), logline: text(d.logline), protagonist: text(d.protagonist), drive: text(d.drive), golden_finger: text(d.golden_finger), core_loop: text(d.core_loop),
    opening: text(d.opening), stage_ladder: text(d.stage_ladder), tone: text(d.tone), reader: text(d.reader), difference: text(d.difference),
    selling_points: Array.isArray(d.selling_points) ? d.selling_points.filter((p): p is string => typeof p === 'string') : [],
    ...editorialMeta(d),
  }))
}
