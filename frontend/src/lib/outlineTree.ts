export interface OutlineChapter { index: number; title: string; status: 'planned' | 'drafting' | 'final'; word_count?: number }
export interface OutlineUnit { id: string; index: number | null; title: string; summary: string; chapter_count: number; status: string; locked: boolean; virtual?: boolean; chapters: OutlineChapter[] }
export interface OutlineVolume { id: string; index: number; title: string; summary: string; chapter_count: number; status: string; locked: boolean; open?: boolean; units: OutlineUnit[] }
export interface OutlineArc {
  virtual?: boolean
  node_id: string | null
  title: string
  text: string
  status: string
  locked: boolean
  planned: boolean
  end: { title: string; event: string; kind: 'milestone' | 'ending' } | null
  volumes: OutlineVolume[]
}
export interface OutlineTree { arcs: OutlineArc[]; ending: { node_id: string; title: string; event: string } | null; segmented: boolean }
export type OutlineItem =
  | { key: string; kind: 'pending'; name: string; status: string; locked: boolean; pending: import('./outlineWriting').PendingArc; children: OutlineItem[] }
  | { key: string; kind: 'book'; name: string; status: string; locked: false; children: OutlineItem[] }
  | { key: string; kind: 'segment'; name: string; status: string; locked: boolean; arc: OutlineArc; children: OutlineItem[] }
  | { key: string; kind: 'volume'; name: string; status: string; locked: boolean; arc: OutlineArc; volume: OutlineVolume; children: OutlineItem[] }
  | { key: string; kind: 'unit'; name: string; status: string; locked: boolean; arc: OutlineArc; volume: OutlineVolume; unit: OutlineUnit; children: OutlineItem[] }
  | { key: string; kind: 'chapter'; name: string; status: string; locked: false; volume: OutlineVolume; chapter: OutlineChapter; children: OutlineItem[] }
  | { key: string; kind: 'ending'; name: string; status: string; locked: false; ending: NonNullable<OutlineTree['ending']>; children: OutlineItem[] }

export const isLaterEnding = (arc: OutlineArc) => !arc.planned && arc.end?.kind === 'ending'
export const arcText = (arc: OutlineArc) => isLaterEnding(arc) ? '' : (arc.text ?? '').trim() ? arc.text : (arc.planned ? arc.end?.event ?? '' : '')
export const outlineStatusText = (status: string) => ({ pending: '待你确认', done: '已写完', final: '已写完', writing: '正在写', drafting: '正在写', later: '写到再定' })[status] ?? '已规划'
export const unitStarted = (unit: OutlineUnit) => unit.chapters.some(chapter => ['final', 'drafting'].includes(chapter.status))
export const volumeStarted = (volume: OutlineVolume) => volume.units.some(unitStarted) || ['writing', 'done'].includes(volume.status)
export const arcStarted = (arc: OutlineArc) => arc.volumes.some(volumeStarted)

export function unitStatus(unit: OutlineUnit): string {
  if (unit.chapters.some(chapter => chapter.status === 'drafting')) return 'writing'
  if (unit.chapters.length >= unit.chapter_count && unit.chapter_count > 0 && unit.chapters.every(chapter => chapter.status === 'final')) return 'done'
  if (unit.chapters.some(chapter => chapter.status === 'final')) return 'writing'
  return unit.status === 'done' && !unit.chapters.length ? 'done' : 'planned'
}

export function buildOutlineTree(tree: OutlineTree, title = '全书'): OutlineItem {
  let number = 0
  const children: OutlineItem[] = tree.arcs.map((arc, i) => {
    const later = isLaterEnding(arc)
    const name = !tree.segmented ? '全书' : later ? '后面的篇' : `第 ${++number} 篇${arc.title ? ` · ${arc.title}` : ''}`
    return {
      key: `segment-${arc.node_id ?? i + 1}`, kind: 'segment', name, status: arc.status, locked: arc.locked, arc,
      children: arc.volumes.map(volume => ({
        key: `volume-${volume.index}`, kind: 'volume', name: `第 ${volume.index} 卷 · ${volume.title || '未命名'}`, status: volume.status, locked: volume.locked, arc, volume,
        children: volume.units.map(unit => ({
          key: `unit-${unit.id}`, kind: 'unit', name: `${unit.index}. ${unit.title || '未命名单元'}`, status: unitStatus(unit), locked: unit.locked, arc, volume, unit,
          children: unit.chapters.map(chapter => ({ key: `chapter-${chapter.index}`, kind: 'chapter', name: `第 ${chapter.index} 章 · ${chapter.title || '待定'}`, status: chapter.status, locked: false, volume, chapter, children: [] })),
        })),
      })),
    }
  })
  if (tree.ending) children.push({ key: 'ending', kind: 'ending', name: `结局 · ${tree.ending.title}`, status: 'planned', locked: false, ending: tree.ending, children: [] })
  return { key: 'book', kind: 'book', name: title, status: 'planned', locked: false, children }
}

export function flattenOutline(root: OutlineItem): OutlineItem[] { return [root, ...root.children.flatMap(flattenOutline)] }

/** 默认只展开当前篇、当前卷；不把未来卷的章纲提前铺开。 */
export function defaultOutlineExpanded(root: OutlineItem): string[] {
  const arcs = root.children.filter((item): item is Extract<OutlineItem, { kind: 'segment' }> => item.kind === 'segment')
  const current = arcs.find(arc => arc.status === 'writing') ?? arcs.find(arc => arc.status !== 'done' && arc.arc.planned) ?? arcs[0]
  const volume = current?.children.find(item => item.status === 'writing') ?? current?.children.find(item => item.status !== 'done') ?? current?.children[0]
  return ['book', ...(current ? [current.key] : []), ...(volume ? [volume.key] : [])]
}

export function outlineAncestors(root: OutlineItem, key: string): string[] {
  for (const child of root.children) {
    if (child.key === key) return [root.key]
    const result = outlineAncestors(child, key)
    if (result.length) return [root.key, ...result]
  }
  return []
}

export function outlineRange(item: OutlineItem): string {
  if (item.kind === 'chapter') return `第 ${item.chapter.index} 章`
  const chapters = flattenOutline(item).filter((node): node is Extract<OutlineItem, { kind: 'chapter' }> => node.kind === 'chapter').map(node => node.chapter.index)
  const volumeCount = (volume: OutlineVolume) => volume.units.length ? volume.units.reduce((sum, unit) => sum + unit.chapter_count, 0) : volume.chapter_count
  const count = item.kind === 'unit' ? item.unit.chapter_count : item.kind === 'volume' ? volumeCount(item.volume) : flattenOutline(item).reduce((sum, node) => sum + (node.kind === 'volume' ? volumeCount(node.volume) : 0), 0)
  if (chapters.length) return `第 ${Math.min(...chapters)}–${Math.max(...chapters)} 章${count > chapters.length ? ` · 共 ${count} 章` : ''}`
  return count ? `${count} 章` : ''
}
