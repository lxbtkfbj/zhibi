/** 把真书（书架上读的，或旧书快照）转成工作台的数据形状。每一栏记着存回去时认的名字。 */

import type { LibraryItem, LibrarySnapshot } from '../../api/library'
import type { ChapterBrief, Relationship } from '../../api/types'
import { arcText, isLaterEnding, outlineStatusText, unitStatus, type OutlineTree } from '../../lib/outlineTree'
import {
  CATEGORY_DEFS, CHARACTER_FIELDS, CHARACTER_PLACEHOLDERS, LEGACY_ROLES, cn, emptyCategory, linkMentions, numberChapters,
  type CardTemplate, type VBook, type VCategory, type VEntry, type VField, type VNode,
} from './model'

export interface ApiParts {
  book: { id: string; title: string; genre: string; concept: Record<string, unknown>; card_layouts?: Record<string, CardTemplate> }
  library: LibrarySnapshot
  outline: OutlineTree
  relationships: Relationship[]
  chapters: ChapterBrief[]
}

const text = (value: unknown) => (typeof value === 'string' ? value.trim() : '')

/** 角色卡上有专门一列的栏目（和后端 CHARACTER_COLUMNS 一致） */
export const CHARACTER_COLUMNS: Record<string, keyof LibraryItem> = {
  定位: 'role_type', 性别: 'gender', 年龄: 'age', 别名: 'aliases',
  外貌: 'appearance', 性格与说话方式: 'personality', 身世: 'background', 想要什么: 'goal', 能力: 'abilities', 备注: 'notes',
}
/** 角色卡「此刻」那几栏：设定师每章更新，不在卡片上改 */
const NOW_EXTRA = '实力与地位'
/** 工作台上的类别 → 设定库里的类别 */
export const ENTRY_CATEGORY: Record<string, string> = {
  等级体系: '等级体系', 地点列表: '世界与地图', 势力列表: '势力划分', 物品功法: '物品与功法', 往事秘密: '往事与秘密', 特殊规则: '特殊规则', 金手指: '特殊规则',
}
export const WORLD_OVERVIEW = '世界概况'

/** 设定条目哪一栏存在 content 里 */
export function contentKey(category: string): string {
  return category === '金手指' ? '能做什么' : '内容'
}

function characterEntry(item: LibraryItem, relations: Relationship[], names: Map<string, string>, lead?: string): VEntry {
  const role = LEGACY_ROLES[item.role_type ?? ''] ?? item.role_type ?? '配角'
  const extra = item.extra ?? {}
  const column = (key: string) => {
    const value = item[CHARACTER_COLUMNS[key]]
    return Array.isArray(value) ? value.join('、') : text(value)
  }
  const sections: VField[] = CHARACTER_FIELDS.map((label) => ({
    key: label, label, text: CHARACTER_COLUMNS[label] ? column(label) : text(extra[label]), placeholder: CHARACTER_PLACEHOLDERS[label],
  }))
  // 作者自己加的栏目
  for (const [key, value] of Object.entries(extra)) {
    if (!CHARACTER_FIELDS.includes(key) && key !== '所属' && key !== NOW_EXTRA) sections.push({ key, label: key, text: text(value) })
  }
  const now: [string, string][] = [
    [NOW_EXTRA, text(extra[NOW_EXTRA])],
    ['在哪', text(item.location)],
    ['处境', text(item.condition)],
    ['想要', text(item.want)],
  ]
  // 「和主角的关系」那一栏当成和主角的一条关系
  const toLead = text(item.relation) && lead && lead !== item.id ? [{ to: lead, kind: '和主角', text: text(item.relation), toLead: true }] : []
  return {
    id: item.id, kind: 'character', category: '角色列表', name: item.name, oneLine: text(item.one_line), tags: item.tags ?? [], locked: item.locked, role,
    dead: item.is_alive === false,
    facts: [['定位', role], ['所属', text(extra['所属']), '哪个宗门、家族、势力'], ['性别', column('性别')], ['年龄', column('年龄')], ['别名', column('别名')]],
    sections,
    now: now.some(([, value]) => value) ? now : undefined,
    relations: [...toLead, ...relations
      .filter((r) => r.source_id === item.id || r.target_id === item.id)
      .map((r) => ({ id: r.id, to: r.source_id === item.id ? r.target_id : r.source_id, kind: r.kind, text: r.description }))
      .filter((r) => names.has(r.to))],
    appears: [],
  }
}

/** 设定条目：「内容」（金手指是「能做什么」）存在 content，其余栏目在 fields。旧数据 content 空着时拿一句话垫上。 */
function settingEntry(item: LibraryItem, category: string): VEntry {
  const base = {
    id: item.id, category, name: item.name, oneLine: '', tags: item.tags ?? [], locked: item.locked,
    parent: item.parent_id ?? undefined, facts: [] as VEntry['facts'], sections: [] as VField[], appears: [],
  }
  if (item.style === 'ladder') {
    return { ...base, kind: 'ladder', overview: text(item.content) || text(item.one_line), levels: (item.levels ?? []).map((l) => ({ name: l.name, text: l.text })) }
  }
  const key = contentKey(category)
  const goldfinger = category === '金手指'
  const sections: VField[] = [
    { key, label: key, text: goldfinger ? text(item.content) : text(item.content) || text(item.one_line) },
    ...(item.fields ?? []).filter((f) => f.name && f.name !== key).map((f) => ({ key: f.name, label: f.name, text: text(f.value) })),
  ]
  return { ...base, kind: goldfinger ? 'goldfinger' : 'paragraph', oneLine: goldfinger ? text(item.one_line) : '', sections }
}

function outlineNodes(tree: OutlineTree, chapters: ChapterBrief[], ending?: string): VNode {
  const byIndex = new Map(chapters.map((c) => [c.index, c]))
  const chapterNode = (index: number, title: string, status: string): VNode => {
    const brief = byIndex.get(index)
    const o = brief?.outline
    const happen = [text(o?.goal), ...(o?.scenes ?? []).map(text)].filter(Boolean).join('\n')
    const sections = o && (happen || o.cool_point || o.hook)
      ? [{ label: '发生什么', text: happen }, { label: '看点', text: text(o.cool_point) }, { label: '结尾钩子', text: text(o.hook) }]
      : [{ label: brief?.summary ? '这一章写了什么' : '发生什么', text: text(brief?.summary), placeholder: '发生什么；看点；结尾的钩子' }]
    return {
      id: `c${index}`, kind: '章', title: `第${index}章　${title || '待定'}`, text: '', sections, progress: outlineStatusText(status), uses: [],
      ...(brief ? { ref: { type: 'chapter' as const, id: String(index) } } : {}),
    }
  }
  const volumes = (arcVolumes: OutlineTree['arcs'][number]['volumes']) =>
    arcVolumes.map((v): VNode => ({
      id: `v:${v.id}`, kind: '卷', title: `第${cn(v.index)}卷　${v.title}`, text: text(v.summary), locked: v.locked, uses: [], ref: { type: 'volume', id: v.id },
      chapters: v.units.length ? v.units.reduce((sum, u) => sum + Math.max(0, u.chapter_count), 0) : v.chapter_count || undefined,
      later: v.status === 'later', progress: outlineStatusText(v.status),
      children: v.units.map((u): VNode => ({
        id: `u:${u.id}`, kind: '单元', title: `单元${cn(u.index)}　${u.title}`, text: text(u.summary), locked: u.locked, uses: [], ref: { type: 'unit', id: u.id },
        chapters: u.chapter_count || undefined, progress: outlineStatusText(unitStatus(u)),
        children: u.chapters.map((c) => chapterNode(c.index, c.title, c.status)),
      })),
    }))
  const children: VNode[] = tree.segmented
    ? tree.arcs.map((arc, i): VNode => {
      const later = isLaterEnding(arc) || !arc.planned
      return {
        id: `a:${arc.node_id ?? i}`, kind: '篇', title: later ? `第${cn(i + 1)}篇` : `第${cn(i + 1)}篇　${arc.title}`, text: arcText(arc), later, locked: arc.locked, uses: [],
        childKind: '卷', children: volumes(arc.volumes),
        ...(arc.node_id && arc.planned ? { ref: { type: 'segment' as const, id: arc.node_id } } : {}),
      }
    })
    : volumes(tree.arcs.flatMap((arc) => arc.volumes))
  // 全书那一段：有结局节点存在节点上，没有就存在书的概念里
  const root: VNode = {
    id: 'book', kind: '全书', title: '全书', text: text(tree.ending?.event) || text(ending), uses: [], children,
    childKind: tree.segmented ? '篇' : '卷',
    ref: tree.ending ? { type: 'segment', id: tree.ending.node_id } : { type: 'book', id: '' },
  }
  numberChapters(root)
  return root
}

export function bookFromApi(parts: ApiParts): VBook {
  const concept = parts.book.concept ?? {}
  const { library } = parts
  const names = new Map(library.characters.map((c) => [c.id, c.name]))
  const lead = library.characters.find((c) => (LEGACY_ROLES[c.role_type ?? ''] ?? c.role_type) === '主角')?.id
  const characters = library.characters.map((c) => characterEntry(c, parts.relationships, names, lead))
  const builtinName = (key: string) => CATEGORY_DEFS.find((d) => d.from.includes(key))?.name

  // 世界概况一本书只有一篇，单独拿出来；带「金手指」标签的都归金手指
  let world = ''
  const byCategory = new Map<string, VEntry[]>()
  for (const item of library.entries) {
    const key = item.category ?? ''
    if (key === '世界与地图' && item.name.trim() === WORLD_OVERVIEW && !world) {
      world = text(item.content) || text(item.one_line)
      continue
    }
    const category = item.tags?.includes('金手指') ? '金手指' : builtinName(key) ?? key
    byCategory.set(category, [...(byCategory.get(category) ?? []), settingEntry(item, category)])
  }
  // 带金手指标签的角色：在金手指里也列一条，内容是他的「能力」，到角色卡上去改
  for (const c of characters.filter((c) => c.tags.includes('金手指'))) {
    const ability = c.sections.find((s) => s.key === '能力')?.text ?? ''
    byCategory.set('金手指', [...(byCategory.get('金手指') ?? []), {
      id: `gf-${c.id}`, kind: 'goldfinger', category: '金手指', name: `${c.name}的本事`, oneLine: ability, tags: ['金手指'], locked: c.locked,
      facts: [], sections: [{ key: '能做什么', label: '能做什么', text: ability }], holder: c.id, appears: [], readonly: true,
    }])
  }

  const categories: VCategory[] = CATEGORY_DEFS.map((def) => ({
    ...emptyCategory(def.name),
    entries: def.name === '角色列表' ? characters : byCategory.get(def.name) ?? [],
  }))
  for (const custom of library.categories.filter((c) => !c.builtin && c.key !== '角色卡片')) {
    categories.push({
      key: custom.key, id: custom.id, name: custom.name, about: custom.hint,
      entries: (byCategory.get(custom.key) ?? []).map((e) => ({ ...e, category: custom.name })),
      custom: { style: custom.style, fields: custom.fields ?? [] },
    })
  }

  const length = typeof concept.target_length === 'number' ? concept.target_length : undefined
  const book: VBook = {
    id: parts.book.id,
    title: text(concept.title) || parts.book.title || '未命名',
    channel: text(concept.channel),
    genre: text(concept.genre) || parts.book.genre || '',
    tags: Array.isArray(concept.tags) ? (concept.tags as string[]) : [],
    length,
    chapterWords: typeof concept.chapter_words === 'number' && concept.chapter_words > 0 ? concept.chapter_words : 2500,
    blurb: text(concept.story) || text(concept.logline),
    world,
    categories,
    outline: outlineNodes(parts.outline, parts.chapters, text(concept.ending)),
    pending: library.suggestions_pending ?? 0,
    layouts: parts.book.card_layouts ?? {},
  }
  linkMentions(book)
  return book
}
