import { cn, splitTitle, type VBook, type VNode } from '../model.ts'

export const ESSENCE_NAMES = {
  source: '情节怎么想', skeleton: '剧情骨架', link: '剧情衔接', fresh: '保持新鲜', longline: '长线布局',
  setting: '设定设计', shuang: '爽点类型', scene: '爽点戏怎么写', hero: '主角', cast: '配角与对手', rhythm: '节奏与钩子', opening: '开篇',
} as const
export type EssenceSectionKey = keyof typeof ESSENCE_NAMES
export type EssenceKey = 'overview' | EssenceSectionKey
export const ESSENCE_LEADS: Record<EssenceKey, string> = {
  overview: '如果只学几件事，先学这几件', source: '想不出下一件事时，作者是怎么想的',
  skeleton: '主线、大段落，一个单元通常什么形状', link: '一件事怎么接到下一件事', fresh: '写这么多章为什么不重复',
  longline: '这么长的书，前后怎么理顺', setting: '设定怎么想出来、为什么这么设', shuang: '读者过瘾的是哪几类，每一类怎么造出来',
  scene: '这几类爽点戏，一拍一拍怎么写', hero: '主角是什么人设，怎么让人愿意跟着读', cast: '配角和对手各是什么人设、起什么作用',
  rhythm: '为什么一章接一章停不下来', opening: '开头几章怎么把人留住',
}
export const ESSENCE_GROUPS: [string, EssenceSectionKey[]][] = [
  ['剧情', ['source', 'skeleton', 'link', 'fresh', 'longline']], ['设定', ['setting']], ['爽点', ['shuang', 'scene']],
  ['人物', ['hero', 'cast']], ['节奏与开篇', ['rhythm', 'opening']],
]

export interface EssencePoint { title: string; steps: string[]; evidence: string; note: string; chapters?: number[] }
export interface EssenceFigure { name: string; archetype: string; build: string; role: string; arc: string; chapters?: number[] }
export interface EssenceSection { points: EssencePoint[]; figures?: EssenceFigure[]; missing?: string[] }
export interface EssenceOverview { genre: string; engine: string; points: EssencePoint[] }
export interface EssenceUnit { n: number; title: string; first: number; last: number }
export type EssenceBars = [string, number][]
export interface EssenceRails {
  units: EssenceUnit[]; tail: [number, number] | null; feel: Record<string, number>; strip: string[]
  waits: { total: number; open: number }; open: { at: number; what: string }[]
  tags: EssenceBars; triggers: EssenceBars; stakes: EssenceBars; things: EssenceBars; people: EssenceBars; hooks: EssenceBars
  crowd: number; hero: string; merges: { names: string[]; keep: string; why: string }[]
}
export interface TeardownEssence {
  upto: number; at?: string; overview: EssenceOverview | null
  sections: Partial<Record<EssenceSectionKey, EssenceSection>>; rails: EssenceRails
}

/** 首次整理尚未给出 upto 时，只走无精髓页面；0 仍是已有值。 */
export function hasEssence<T extends { upto?: number | null }>(value: T | null | undefined): value is T & { upto: number } {
  return typeof value?.upto === 'number'
}

export const essenceNumber = cn
export function essenceCount(essence: TeardownEssence | null, key: EssenceKey, query = ''): number {
  if (!hasEssence(essence)) return 0
  const q = query.trim()
  const section = key === 'overview' ? essence?.overview : essence?.sections[key]
  if (!section) return 0
  const points = section.points.filter(p => !q || [p.title, ...p.steps, p.evidence, p.note].some(s => s?.includes(q)))
  const figures = key !== 'overview' && 'figures' in section ? section.figures ?? [] : []
  return points.length + figures.filter(f => !q || [f.name, f.archetype, f.build, f.role, f.arc].some(s => s?.includes(q))).length
}

export function emptyEssenceText(book: VBook, active: boolean): string {
  const last = book.teardown?.last_read ?? 0
  if (!last) return '还没开拆。拆过的章会整理成一条条知识点：情节怎么想、设定怎么设、爽点怎么造、人物怎么立。'
  if (active) return '拆书收尾时整理精髓，到时这里就有了。'
  if (book.teardown?.stage === 'done') return '还没整理精髓：点右上角「补上整理」，不重读原文。'
  return `还没整理精髓：点右上角「接着拆」，选「只整理前 ${last} 章」，不重读原文。`
}

export function introOutline(book: VBook): { units: EssenceUnit[]; tail: [number, number] | null } {
  const units: EssenceUnit[] = []
  let tail: [number, number] | null = null
  const walk = (node: VNode) => {
    if (node.kind === '单元' && node.range) {
      if (node.virtual) {
        const read = (node.children ?? []).filter(c => c.teardown?.read).map(c => c.range?.[0] ?? 0).filter(Boolean)
        if (read.length) tail = [Math.min(...read), Math.max(...read)]
      } else units.push({ n: units.length + 1, title: node.title.replace(/^单元[一二三四五六七八九十百\d]+[ ·　]*/, ''), first: node.range[0], last: node.range[1] })
    } else node.children?.forEach(walk)
  }
  walk(book.outline)
  return { units, tail }
}

export interface IntroVolume extends EssenceUnit { id: string; units: number }
export interface IntroVolumeGroup {
  arc?: { title: string; first: number; last: number }
  volumes: IntroVolume[]
}

/** 卷格只取已归好的卷；主编还在归的部分合成一张尾卡。 */
export function introVolumes(book: VBook): { groups: IntroVolumeGroup[]; tail: [number, number] | null } {
  const groups: IntroVolumeGroup[] = []
  const read = book.teardown?.last_read ?? 0
  const openId = book.teardown?.open_volume_id
  let n = 0, last = 0
  const add = (nodes: VNode[], arc?: VNode) => {
    const volumes: IntroVolume[] = []
    for (const node of nodes) {
      if (node.kind !== '卷' || !node.range || node.range[1] > read || node.open
        || (openId && (node.ref?.id === openId || node.id === `v:${openId}`))
        || (splitTitle(node.title)[1] || node.title) === '还没分卷') continue
      volumes.push({ id: node.id, n: ++n, title: splitTitle(node.title)[1] || node.title.replace(/^第[一二三四五六七八九十百\d]+卷[ ·　]*/, ''),
        first: node.range[0], last: node.range[1], units: (node.children ?? []).filter(unit => unit.kind === '单元' && !unit.virtual).length })
      last = node.range[1]
    }
    if (volumes.length) groups.push({ ...(arc ? { arc: { title: arc.title.replace('　', ' '), first: volumes[0].first, last: volumes.at(-1)!.last } } : {}), volumes })
  }
  for (const node of book.outline.children ?? []) {
    if (node.kind === '篇') add(node.children ?? [], node)
    else if (node.kind === '卷') add([node])
  }
  return { groups, tail: last < read ? [last + 1, read] : null }
}

export function introSteps(point: EssencePoint): string {
  return point.steps.map(s => s.replace(/[；;。，,]+$/, '')).join(' → ')
}
