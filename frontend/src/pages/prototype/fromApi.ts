/** 把真书（书架上读的，或旧书快照）转成原型的数据形状。只读，不改任何东西。 */

import type { LibraryItem, LibrarySnapshot } from '../../api/library'
import type { ChapterBrief, Relationship } from '../../api/types'
import { arcText, isLaterEnding, outlineStatusText, unitStatus, type OutlineTree } from '../../lib/outlineTree'
import {
  CATEGORY_DEFS, CHARACTER_FIELDS, CHARACTER_PLACEHOLDERS, LEGACY_ROLES, cn, emptyCategory, linkMentions, numberChapters,
  type VBook, type VCategory, type VEntry, type VNode,
} from './model'

export interface ApiParts {
  book: { id: string; title: string; genre: string; concept: Record<string, unknown> }
  library: LibrarySnapshot
  outline: OutlineTree
  relationships: Relationship[]
  chapters: ChapterBrief[]
}

const text = (value: unknown) => (typeof value === 'string' ? value.trim() : '')

function characterEntry(item: LibraryItem, relations: Relationship[], names: Map<string, string>, lead?: string): VEntry {
  const role = LEGACY_ROLES[item.role_type ?? ''] ?? item.role_type ?? '配角'
  // 真实设定库还没有软肋、成长与结局、所属、实力与地位，原型里先空着
  const values: Record<string, string> = {
    外貌: text(item.appearance), 性格与说话方式: text(item.personality), 身世: text(item.background),
    想要什么: text(item.goal), 能力: text(item.abilities), 备注: text(item.notes),
  }
  const now: [string, string][] = [
    ['实力与地位', ''],
    ['在哪', text(item.location)],
    ['处境', text(item.condition)],
    ['想要', text(item.want)],
  ]
  // 「和主角的关系」并进关系：当成和主角的一条
  const toLead = text(item.relation) && lead && lead !== item.id ? [{ to: lead, kind: '和主角', text: text(item.relation) }] : []
  return {
    id: item.id, kind: 'character', category: '角色列表', name: item.name, oneLine: text(item.one_line), tags: item.tags ?? [], locked: item.locked, role,
    dead: item.is_alive === false,
    facts: [['定位', role], ['所属', '', '哪个宗门、家族、势力'], ['性别', text(item.gender)], ['年龄', text(item.age)], ['别名', (item.aliases ?? []).join('、')]],
    sections: CHARACTER_FIELDS.map((label) => ({ label, text: values[label] ?? '', placeholder: CHARACTER_PLACEHOLDERS[label] })),
    now: now.some(([, value]) => value) ? now : undefined,
    relations: [...toLead, ...relations
      .filter((r) => r.source_id === item.id || r.target_id === item.id)
      .map((r) => ({ to: r.source_id === item.id ? r.target_id : r.source_id, kind: r.kind, text: r.description }))
      .filter((r) => names.has(r.to))],
    appears: [],
  }
}

/** 段落类只要「名字＋一段话」：旧数据的一句话常常就是正文第一句，正文空着才用它。 */
function settingEntry(item: LibraryItem, category: string): VEntry {
  const base = {
    id: item.id, category, name: item.name, oneLine: '', tags: item.tags ?? [], locked: item.locked,
    parent: item.parent_id ?? undefined, facts: [] as VEntry['facts'], sections: [], appears: [],
  }
  if (item.style === 'ladder') {
    return { ...base, kind: 'ladder', overview: text(item.content) || text(item.one_line), levels: (item.levels ?? []).map((l) => ({ name: l.name, text: l.text })) }
  }
  const fields = (item.fields ?? []).filter((f) => f.name)
  if (fields.length) return { ...base, kind: 'paragraph', sections: fields.map((f) => ({ label: f.name, text: text(f.value) })) }
  return { ...base, kind: 'paragraph', body: text(item.content) || text(item.one_line) }
}

function outlineNodes(tree: OutlineTree, chapters: ChapterBrief[]): VNode {
  const byIndex = new Map(chapters.map((c) => [c.index, c]))
  const chapterNode = (index: number, title: string, status: string): VNode => {
    const brief = byIndex.get(index)
    const o = brief?.outline
    const happen = [text(o?.goal), ...(o?.scenes ?? []).map(text)].filter(Boolean).join('\n')
    const sections = o && (happen || o.cool_point || o.hook)
      ? [{ label: '发生什么', text: happen }, { label: '看点', text: text(o.cool_point) }, { label: '结尾钩子', text: text(o.hook) }]
      : [{ label: brief?.summary ? '这一章写了什么' : '发生什么', text: text(brief?.summary), placeholder: '发生什么；看点；结尾的钩子' }]
    return { id: `c${index}`, kind: '章', title: `第${index}章　${title || '待定'}`, text: '', sections, progress: outlineStatusText(status), uses: [] }
  }
  const volumes = (arcVolumes: OutlineTree['arcs'][number]['volumes']) =>
    arcVolumes.map((v): VNode => ({
      id: `v${v.index}`, kind: '卷', title: `第${cn(v.index)}卷　${v.title || '未命名'}`, text: text(v.summary), locked: v.locked, uses: [],
      chapters: v.units.length ? v.units.reduce((sum, u) => sum + Math.max(0, u.chapter_count), 0) : v.chapter_count || undefined,
      later: v.status === 'later', progress: outlineStatusText(v.status),
      children: v.units.map((u): VNode => ({
        id: `u${u.id}`, kind: '单元', title: `单元${cn(u.index)}　${u.title || '未命名'}`, text: text(u.summary), locked: u.locked, uses: [],
        chapters: u.chapter_count || undefined, progress: outlineStatusText(unitStatus(u)),
        children: u.chapters.map((c) => chapterNode(c.index, c.title, c.status)),
      })),
    }))
  const children: VNode[] = tree.segmented
    ? tree.arcs.map((arc, i): VNode => {
      const later = isLaterEnding(arc) || !arc.planned
      return {
        id: `a${arc.node_id ?? i}`, kind: '篇', title: later ? `第${cn(i + 1)}篇` : `第${cn(i + 1)}篇　${arc.title}`, text: arcText(arc), later, locked: arc.locked, uses: [],
        children: volumes(arc.volumes),
      }
    })
    : volumes(tree.arcs.flatMap((arc) => arc.volumes))
  const root: VNode = { id: 'book', kind: '全书', title: '全书', text: text(tree.ending?.event), uses: [], children }
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
    if (key === '世界与地图' && item.name.trim() === '世界概况') {
      world = text(item.content) || text(item.one_line)
      continue
    }
    const category = item.tags?.includes('金手指') ? '金手指' : builtinName(key) ?? library.categories.find((c) => c.key === key)?.name ?? key
    byCategory.set(category, [...(byCategory.get(category) ?? []), settingEntry(item, category)])
  }
  for (const c of characters.filter((c) => c.tags.includes('金手指'))) {
    const ability = c.sections.find((s) => s.label === '能力')?.text ?? ''
    byCategory.set('金手指', [...(byCategory.get('金手指') ?? []), {
      id: `gf-${c.id}`, kind: 'goldfinger', category: '金手指', name: `${c.name}的本事`, oneLine: ability, tags: ['金手指'], locked: c.locked,
      facts: [], sections: [{ label: '能做什么', text: ability }], holder: c.id, appears: [],
    }])
  }

  const categories: VCategory[] = CATEGORY_DEFS.map((def) => ({
    ...emptyCategory(def.name),
    entries: def.name === '角色列表' ? characters : byCategory.get(def.name) ?? [],
  }))
  for (const custom of library.categories.filter((c) => !c.builtin && c.key !== '角色卡片')) {
    categories.push({ name: custom.name, about: custom.hint, entries: byCategory.get(custom.name) ?? [], custom: { style: custom.style, fields: custom.fields ?? [] } })
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
    outline: outlineNodes(parts.outline, parts.chapters),
    pending: library.suggestions_pending ?? 0,
  }
  linkMentions(book)
  return book
}
