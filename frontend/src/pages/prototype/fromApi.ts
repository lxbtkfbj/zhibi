/** 把真书（书架上读的，或旧书快照）转成原型的数据形状。只读，不改任何东西。 */

import type { LibraryItem, LibrarySnapshot } from '../../api/library'
import type { ChapterBrief, Relationship } from '../../api/types'
import { arcText, isLaterEnding, type OutlineTree } from '../../lib/outlineTree'
import {
  ALL_CATEGORIES, CATEGORY_HINTS, CHARACTER_PLACEHOLDERS, LEGACY_ROLES, cn, defaultCategories, linkMentions,
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

function characterEntry(item: LibraryItem, relations: Relationship[], names: Map<string, string>): VEntry {
  const role = LEGACY_ROLES[item.role_type ?? ''] ?? item.role_type ?? '配角'
  const long: [string, string][] = [
    ['外貌', text(item.appearance)],
    ['性格与说话方式', text(item.personality)],
    ['身世', text(item.background)],
    ['想要什么', text(item.goal)],
    ['能力', text(item.abilities)],
    ...(role === '主角' ? [] : [['和主角的关系', text(item.relation)] as [string, string]]),
    ['备注', text(item.notes)],
  ]
  const now: [string, string][] = [
    ['想要', text(item.want)],
    ['在哪', text(item.location)],
    ['处境', text(item.condition)],
    ['活着', item.is_alive === false ? '已经死了' : ''],
  ]
  return {
    id: item.id, kind: 'character', category: '角色', name: item.name, oneLine: text(item.one_line), tags: item.tags ?? [], locked: item.locked, role,
    facts: [['别名', (item.aliases ?? []).join('、')], ['定位', role], ['性别', text(item.gender)], ['年龄', text(item.age)]],
    sections: long.map(([label, value]) => ({ label, text: value, placeholder: CHARACTER_PLACEHOLDERS[label] })),
    now: now.some(([, value]) => value) ? now : undefined,
    relations: relations
      .filter((r) => r.source_id === item.id || r.target_id === item.id)
      .map((r) => ({ to: r.source_id === item.id ? r.target_id : r.source_id, kind: r.kind, text: r.description }))
      .filter((r) => names.has(r.to)),
    appears: [],
  }
}

function settingEntry(item: LibraryItem, category: string, hints: string[]): VEntry {
  const base = {
    id: item.id, category, name: item.name, oneLine: text(item.one_line), tags: item.tags ?? [], locked: item.locked,
    parent: item.parent_id ?? undefined, facts: [] as VEntry['facts'], appears: [],
  }
  if (item.style === 'ladder') {
    return { ...base, kind: 'ladder', sections: [], overview: text(item.content), levels: (item.levels ?? []).map((l) => ({ name: l.name, text: l.text })) }
  }
  const fields = (item.fields ?? []).filter((f) => f.name)
  return {
    ...base,
    kind: 'paragraph',
    sections: fields.length
      ? fields.map((f) => ({ label: f.name, text: text(f.value) }))
      : [{ label: '详细', text: text(item.content), placeholder: `一段话写清：${hints.join('；')}。` }],
  }
}

function outlineNodes(tree: OutlineTree, chapters: ChapterBrief[]): VNode {
  const byIndex = new Map(chapters.map((c) => [c.index, c]))
  const chapterNode = (index: number, title: string): VNode => {
    const brief = byIndex.get(index)
    const o = brief?.outline
    const happen = [text(o?.goal), ...(o?.scenes ?? []).map(text)].filter(Boolean).join('\n')
    const sections = o && (happen || o.cool_point || o.hook)
      ? [{ label: '发生什么', text: happen }, { label: '看点', text: text(o.cool_point) }, { label: '结尾钩子', text: text(o.hook) }]
      : [{ label: brief?.summary ? '这一章写了什么' : '发生什么', text: text(brief?.summary), placeholder: '发生什么；看点；结尾的钩子' }]
    return { id: `c${index}`, kind: '章', title: `第${index}章　${title || '待定'}`, text: '', sections, uses: [] }
  }
  const volumes = (arcVolumes: OutlineTree['arcs'][number]['volumes']) =>
    arcVolumes.map((v): VNode => ({
      id: `v${v.index}`, kind: '卷', title: `第${cn(v.index)}卷　${v.title || '未命名'}`, text: text(v.summary), locked: v.locked, uses: [],
      chapters: v.units.length ? v.units.reduce((sum, u) => sum + Math.max(0, u.chapter_count), 0) : v.chapter_count || undefined,
      later: v.status === 'later',
      children: v.units.map((u): VNode => ({
        id: `u${u.id}`, kind: '单元', title: `单元${cn(u.index)}　${u.title || '未命名'}`, text: text(u.summary), locked: u.locked, uses: [],
        chapters: u.chapter_count || undefined,
        children: u.chapters.map((c) => chapterNode(c.index, c.title)),
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
  return { id: 'book', kind: '全书', title: '全书', text: text(tree.ending?.event), uses: [], children }
}

export function bookFromApi(parts: ApiParts): VBook {
  const concept = parts.book.concept ?? {}
  const genre = text(concept.genre) || parts.book.genre || ''
  const { library } = parts
  const names = new Map(library.characters.map((c) => [c.id, c.name]))
  const characters = library.characters.map((c) => characterEntry(c, parts.relationships, names))

  // 金手指单独一类：带「金手指」标签的条目都收过来；角色卡上标了金手指的，在这一类里留个指向
  const goldfinger: VEntry[] = []
  const byCategory = new Map<string, VEntry[]>()
  const catName = (key: string) => library.categories.find((c) => c.key === key)?.name ?? key
  for (const item of library.entries) {
    const category = item.tags?.includes('金手指') ? '金手指' : catName(item.category ?? '')
    const hints = CATEGORY_HINTS[category] ?? (library.categories.find((c) => c.name === category)?.hint ?? '').split(/[；;。]/).filter(Boolean)
    const entry = settingEntry(item, category, hints)
    if (category === '金手指') goldfinger.push(entry)
    else byCategory.set(category, [...(byCategory.get(category) ?? []), entry])
  }
  for (const c of characters.filter((c) => c.tags.includes('金手指'))) {
    goldfinger.push({
      id: `gf-${c.id}`, kind: 'goldfinger', category: '金手指', name: `${c.name}的本事`, oneLine: c.sections.find((s) => s.label === '能力')?.text ?? '', tags: ['金手指'], locked: c.locked,
      facts: [], sections: [{ label: '能做什么', text: c.sections.find((s) => s.label === '能力')?.text ?? '' }], holder: c.id, appears: [],
    })
  }

  const custom = library.categories.filter((c) => !c.builtin && c.key !== '角色卡片').map((c) => c.name)
  const shown = defaultCategories(genre)
  const order = [...ALL_CATEGORIES, ...custom]
  const categories: VCategory[] = []
  const folded: string[] = []
  for (const name of order) {
    const entries = name === '角色' ? characters : name === '金手指' ? goldfinger : byCategory.get(name) ?? []
    // 有内容的类别永远显示；空的按题材决定显示还是先收起
    if (!entries.length && !shown.includes(name) && !custom.includes(name)) {
      folded.push(name)
      continue
    }
    const hint = library.categories.find((c) => c.name === name)?.hint ?? ''
    categories.push({ name, hints: CATEGORY_HINTS[name] ?? hint.split(/[；;。]/).filter(Boolean), entries })
  }

  const length = typeof concept.target_length === 'number' ? concept.target_length : undefined
  const book: VBook = {
    id: parts.book.id,
    title: text(concept.title) || parts.book.title || '未命名',
    channel: text(concept.channel),
    genre,
    tags: Array.isArray(concept.tags) ? (concept.tags as string[]) : [],
    length,
    chapterWords: typeof concept.chapter_words === 'number' && concept.chapter_words > 0 ? concept.chapter_words : 2500,
    blurb: text(concept.story) || text(concept.logline),
    categories,
    folded,
    outline: outlineNodes(parts.outline, parts.chapters),
    pending: library.suggestions_pending ?? 0,
  }
  linkMentions(book)
  return book
}
