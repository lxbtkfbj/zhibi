/** 工作台上的每一次改动都走这里：真书存到服务器，原型只改这一页里的那份。界面只管调，不管存到哪。 */

import { type Dispatch, type SetStateAction, createContext, useContext, useMemo, useState } from 'react'
import {
  CHARACTER_FIELDS, applyTemplate, chapterNumberOf, cn, findEntry, findNode, numberChapters, splitTitle,
  type CardTemplate, type VBook, type VCategory, type VEntry, type VNode,
} from './model'
import { sampleSplit } from './sampleChapters'

export type CategoryStyle = NonNullable<VCategory['custom']>['style']

/** 一条设定改了什么。fields 的键是栏目的 key（改了名也不变）。 */
export interface EntryChange {
  name?: string
  oneLine?: string
  fields?: Record<string, string>
  overview?: string
  levels?: VEntry['levels']
  locked?: boolean
}

/** 编辑部帮写的一条候选：values 的键是栏目的 key；阶梯类另有总说明（values.总说明）和各级。 */
export interface DraftItem {
  name: string
  values: Record<string, string>
  levels: { name: string; text: string }[]
}

/** 选中文字让编辑部改：直接改好的带回撤销用的版本；给几个写法的带回候选。 */
export interface RewriteOutcome {
  revertVersionId?: string | null
  candidate?: { id: string; options: { label: string; text: string }[] }
}

export type RewriteMode = 'instruction' | 'options' | 'expand'

/** 编辑部帮拆出来的一条：章是名字加章纲三栏，单元是名字、一段话、章数。 */
export interface SplitDraft {
  name: string
  /** 单元的那段话 */
  text?: string
  /** 章纲：发生什么、看点、结尾钩子 */
  sections?: Record<string, string>
  /** 单元几章，0 是还没定 */
  chapters?: number
  /** 模型原来给的全部字段：收下时带回去，作者改过的名字和几栏写回去 */
  raw?: Record<string, unknown>
}

/** 编辑部帮拆的一版：还没放进大纲。first 是第一章的章号；keeps、replaces 是收下以后不动的、会被换掉的（章的名字）。 */
export interface SplitResult {
  drafts: SplitDraft[]
  note: string
  first?: number
  keeps: string[]
  replaces: string[]
  /** 拆卷时整份卷纲里单元以外的部分（这一卷想做成什么、新埋的伏笔……），收下时一起带回去 */
  plan?: Record<string, unknown>
}

export interface BookChange {
  title?: string
  blurb?: string
  channel?: string
  genre?: string
  tags?: string[]
  length?: number | null
}

export interface WorkspaceActions {
  /** 真书：改了就存到服务器 */
  live: boolean
  saveBook(change: BookChange): Promise<void>
  saveWorld(text: string): Promise<void>
  saveEntry(entry: VEntry, change: EntryChange): Promise<void>
  /** 新建一条（draft 是作者在空卡片上写好的，或从编辑部帮写的候选里收下的），返回新的 id */
  createEntry(category: VCategory, draft: VEntry, options?: { fromCandidate?: boolean }): Promise<string>
  deleteEntry(entry: VEntry): Promise<void>
  /** 角色置顶、取消置顶 */
  pinEntry?(entry: VEntry, pinned: boolean): Promise<void>
  saveRelation(entry: VEntry, relation: NonNullable<VEntry['relations']>[number], text: string): Promise<void>
  addRelation(entry: VEntry, to: string, kind: string, text: string): Promise<void>
  deleteRelation(entry: VEntry, relation: NonNullable<VEntry['relations']>[number]): Promise<void>
  saveTemplate(category: VCategory, template: CardTemplate, dropped: string[]): Promise<void>
  resetTemplate(category: VCategory): Promise<void>
  createCategory(name: string, style: CategoryStyle, fields: string[], about: string): Promise<void>
  /** sections 是章纲那几栏，键是栏目名（发生什么、看点、结尾钩子） */
  saveNode(node: VNode, change: NodeChange): Promise<void>
  /** 在这个节点下面加一个下一层，返回新节点的 id */
  addNode(parent: VNode): Promise<string | undefined>
  deleteNode(node: VNode): Promise<void>
  /** 在这一个的前面或后面插一个同一层的，返回新的 id */
  insertNode(sibling: VNode, where: 'before' | 'after'): Promise<string | undefined>
  /** 往前或往后挪一格，返回挪完以后的 id（章挪了章号会变） */
  moveNode(node: VNode, direction: 'up' | 'down'): Promise<string | undefined>
  /** 能不能在它前后插、能不能挪 */
  canArrange(node: VNode): boolean
  canAdd(parent: VNode): boolean
  canEdit(node: VNode, part: 'name' | 'text'): boolean
  canDelete(node: VNode): boolean
  /* 下面几样要叫编辑部，只有真书有；原型里不填，界面照旧给原型的样子 */
  /** 编辑部帮写：在这一类里照这本书的栏目写几条候选，不存 */
  draft?(category: VCategory, template: CardTemplate, request: string): Promise<{ entries: DraftItem[]; note: string }>
  /** 选中文字让编辑部改。spot 是页面上那一栏的记号（见 Editable 的 spot），start/end 是选中的字在这一栏里的位置，quote 是选中的字（位置对不上时按它找） */
  rewrite?(spot: string, start: number, end: number, mode: RewriteMode, instruction?: string, quote?: string): Promise<RewriteOutcome>
  /** 从几个写法里挑一个换上，带回撤销用的版本 */
  chooseOption?(candidateId: string, index: number): Promise<string | null>
  /** 退回到某一版（撤销编辑部刚改的） */
  revert?(versionId: string): Promise<void>
  /** 让编辑部把这一条空着的栏目补上，写过的不动 */
  /** 编辑部帮写大纲上的这一段（结局、篇、卷、单元写名字和一段话，章写章纲），直接写进去；before 是改之前的样子，撤销就存回去 */
  writeNode?(node: VNode, request: string): Promise<{ note: string; before: NodeChange }>
  /** 这一段能不能让编辑部写：开写了的不行 */
  canWrite?(node: VNode): boolean
  /** 编辑部帮拆：单元出章纲、卷拆成单元。只出一版给作者看，不存；round 是第几版，current 是上一版（再出一版时） */
  splitNode?(node: VNode, request: string, round: number, current?: SplitDraft[]): Promise<SplitResult>
  /** 收下帮拆的这一版：放进大纲，带回撤销的办法 */
  acceptSplit?(node: VNode, drafts: SplitDraft[], plan?: Record<string, unknown>): Promise<() => Promise<void>>
}

/** 大纲上一段要改的地方。sections 是章纲那几栏，键是栏目名（发生什么、看点、结尾钩子）；chapters 是章数，0 是还没定 */
export interface NodeChange { name?: string; text?: string; sections?: Record<string, string>; chapters?: number }

interface WorkspaceTools {
  actions: WorkspaceActions
  /** 存不上时在页面底下说一声 */
  report: (error: unknown) => void
  /** 编辑部做完一件事在页面底下说一声；带版本（或带怎么换回去）的可以撤销 */
  notify?: (text: string, undo?: string | (() => Promise<void>) | null) => void
}

export const ActionsContext = createContext<WorkspaceTools | null>(null)

export function useWorkspace(): WorkspaceTools {
  const value = useContext(ActionsContext)
  if (!value) throw new Error('useWorkspace 必须在工作台里用')
  return value
}

/** 存一下：失败了报出来，不打断作者。 */
export function useSave() {
  const { report } = useWorkspace()
  return (task: Promise<unknown>) => { task.catch(report) }
}

/* ---------------- 原型：改的都只在这一页 ---------------- */

const NEXT_KIND: Partial<Record<VNode['kind'], VNode['kind']>> = { 全书: '篇', 篇: '卷', 卷: '单元', 单元: '章' }

/** 在这个节点下面加的是哪一层：已经有下一层就照着它，没有就按默认。 */
export function childKind(node: VNode): VNode['kind'] | undefined {
  return node.children?.[0]?.kind ?? node.childKind ?? NEXT_KIND[node.kind]
}

let nextLocal = 1

function patchEntry(book: VBook, id: string, change: (entry: VEntry) => VEntry): VBook {
  return { ...book, categories: book.categories.map((c) => ({ ...c, entries: c.entries.map((e) => (e.id === id ? change(e) : e)) })) }
}

export function withFields(entry: VEntry, fields: Record<string, string>): VEntry {
  const facts = entry.facts.map((f) => {
    const key = f[3] ?? f[0]
    return key in fields ? ([f[0], fields[key], f[2], key] as VEntry['facts'][number]) : f
  })
  const known = new Set([...facts.map((f) => f[3] ?? f[0]), ...entry.sections.map((s) => s.key ?? s.label)])
  const sections = [
    ...entry.sections.map((s) => ((s.key ?? s.label) in fields ? { ...s, text: fields[s.key ?? s.label] } : s)),
    ...Object.entries(fields).filter(([key]) => !known.has(key)).map(([key, text]) => ({ key, label: key, text })),
  ]
  const role = fields['定位']
  return { ...entry, facts, sections, ...(role !== undefined && entry.kind === 'character' ? { role: role || '配角' } : {}) }
}

/** 原型用：书放在这一页的状态里，改动直接改这份。第三个是直接换书的办法（演示写作用）。 */
export function useLocalBook(initial: VBook): [VBook, WorkspaceActions, Dispatch<SetStateAction<VBook>>] {
  const [book, setBook] = useState(initial)
  const actions = useMemo<WorkspaceActions>(() => {
    const update = (change: (book: VBook) => VBook) => { setBook(change); return Promise.resolve() }
    return {
      live: false,
      saveBook: (change) => update((b) => ({ ...b, ...change, length: change.length === undefined ? b.length : change.length ?? undefined })),
      saveWorld: (text) => update((b) => ({ ...b, world: text })),
      saveEntry: (entry, change) => update((b) => patchEntry(b, entry.id, (e) => {
        let next = change.fields ? withFields(e, change.fields) : e
        if (change.name !== undefined) next = { ...next, name: change.name }
        if (change.oneLine !== undefined) next = { ...next, oneLine: change.oneLine }
        if (change.overview !== undefined) next = { ...next, overview: change.overview }
        if (change.levels !== undefined) next = { ...next, levels: change.levels }
        if (change.locked !== undefined) next = { ...next, locked: change.locked }
        return next
      })),
      createEntry: async (category, draft) => {
        const id = `local-${nextLocal++}`
        setBook((b) => ({ ...b, categories: b.categories.map((c) => (c.key === category.key ? { ...c, entries: [...c.entries, { ...draft, id }] } : c)) }))
        return id
      },
      deleteEntry: (entry) => update((b) => ({ ...b, categories: b.categories.map((c) => ({ ...c, entries: c.entries.filter((e) => e.id !== entry.id) })) })),
      saveRelation: (entry, relation, text) => update((b) => patchEntry(b, entry.id, (e) => ({ ...e, relations: e.relations?.map((r) => (r === relation || (r.to === relation.to && r.kind === relation.kind) ? { ...r, text } : r)) }))),
      addRelation: (entry, to, kind, text) => update((b) => patchEntry(b, entry.id, (e) => ({ ...e, relations: [...(e.relations ?? []), { to, kind, text }] }))),
      deleteRelation: (entry, relation) => update((b) => patchEntry(b, entry.id, (e) => ({ ...e, relations: e.relations?.filter((r) => !(r.to === relation.to && r.kind === relation.kind)) }))),
      saveTemplate: (category, template) => update((b) => ({ ...b, layouts: { ...b.layouts, [category.key]: template } })),
      resetTemplate: (category) => update((b) => {
        const layouts = { ...b.layouts }
        delete layouts[category.key]
        return { ...b, layouts }
      }),
      createCategory: (name, style, fields, about) => update((b) => ({
        ...b, categories: [...b.categories, { key: `custom:${name}`, name, about, entries: [], custom: { style, fields } }],
      })),
      saveNode: (node, change) => update((b) => {
        const outline = structuredClone(b.outline)
        const target = findNode(outline, node.id)?.at(-1)
        if (!target) return b
        if (change.text !== undefined) target.text = change.text
        if (change.name !== undefined) target.title = `${splitTitle(target.title)[0]}　${change.name}`
        if (change.sections) target.sections = target.sections?.map((f) => (f.label in change.sections! ? { ...f, text: change.sections![f.label] } : f))
        if (change.chapters !== undefined) {
          target.count = change.chapters
          target.chapters = Math.max(change.chapters, target.children?.length ?? 0) || undefined
          numberChapters(outline, true)
        }
        return { ...b, outline }
      }),
      addNode: async (parent) => {
        const result = addOutlineChild(book.outline, parent.id)
        if (!result) return undefined
        setBook((b) => ({ ...b, outline: result.root }))
        return result.id
      },
      deleteNode: (node) => update((b) => {
        const outline = structuredClone(b.outline)
        const path = findNode(outline, node.id)
        const parent = path?.at(-2)
        if (!parent?.children) return b
        parent.children = parent.children.filter((c) => c.id !== node.id)
        numberChapters(outline, true)
        return { ...b, outline }
      }),
      insertNode: async (sibling, where) => {
        const result = insertOutlineSibling(book.outline, sibling.id, where)
        if (!result) return undefined
        setBook((b) => ({ ...b, outline: result.root }))
        return result.id
      },
      moveNode: async (node, direction) => {
        setBook((b) => {
          const outline = structuredClone(b.outline)
          const parent = findNode(outline, node.id)?.at(-2)
          const list = parent?.children
          const i = list?.findIndex((c) => c.id === node.id) ?? -1
          const j = i + (direction === 'up' ? -1 : 1)
          if (!list || i < 0 || j < 0 || j >= list.length) return b
          ;[list[i], list[j]] = [list[j], list[i]]
          numberChapters(outline, true)
          return { ...b, outline }
        })
        return node.id
      },
      canArrange: (node) => node.kind !== '全书',
      canAdd: (parent) => !!childKind(parent),
      canEdit: () => true,
      canDelete: (node) => node.kind !== '全书',
      splitNode: async (node, request, round) => {
        await new Promise((resolve) => setTimeout(resolve, 2400))
        const plan = sampleSplit(node.id, round, request)
        if (!plan) throw new Error('原型里只有示例书的单元和第二卷能演示帮拆')
        if (node.kind !== '单元') return { ...plan, keeps: [], replaces: [] }
        const chapters = node.children ?? []
        const kept = chapters.filter((c) => c.body && c.body.status !== 'planned')
        const last = kept.at(-1)
        const first = last ? chapterNumberOf(last) + 1 : node.range?.[0] ?? lastChapterBefore(book.outline, node.id) + 1
        return { ...plan, first, keeps: kept.map((c) => c.title), replaces: chapters.filter((c) => !kept.includes(c)).map((c) => c.title) }
      },
      acceptSplit: async (node, drafts) => {
        const before = findNode(book.outline, node.id)?.at(-1)
        const snapshot = before ? structuredClone(before) : undefined
        setBook((b) => {
          const outline = structuredClone(b.outline)
          const target = findNode(outline, node.id)?.at(-1)
          if (!target) return b
          if (target.kind === '单元') {
            numberChapters(outline, true)
            const kept = (target.children ?? []).filter((c) => c.body && c.body.status !== 'planned')
            const last = kept.at(-1)
            const first = last ? chapterNumberOf(last) + 1 : target.range?.[0] ?? lastChapterBefore(outline, target.id) + 1
            target.children = [...kept, ...drafts.map((d, i): VNode => ({
              id: `split-${nextLocal++}`, kind: '章', title: `第${first + i}章　${d.name}`, text: '', uses: [],
              sections: ['发生什么', '看点', '结尾钩子'].map((label) => ({ label, text: d.sections?.[label] ?? '' })),
              body: { status: 'planned', words: 0 },
            }))]
            target.chapters = Math.max(target.count ?? 0, target.children.length) || undefined
          } else {
            target.later = false
            target.children = drafts.map((d, i): VNode => ({
              id: `added-${nextLocal++}`, kind: '单元', title: `单元${cn(i + 1)}　${d.name}`, text: d.text ?? '', uses: [],
              chapters: d.chapters || undefined, count: d.chapters ?? 0, children: [],
            }))
          }
          numberChapters(outline, true)
          return { ...b, outline }
        })
        return async () => {
          if (!snapshot) return
          setBook((b) => {
            const outline = structuredClone(b.outline)
            const target = findNode(outline, node.id)?.at(-1)
            if (!target) return b
            Object.assign(target, structuredClone(snapshot))
            numberChapters(outline, true)
            return { ...b, outline }
          })
        }
      },
    }
  }, [book.outline])
  return [book, actions, setBook]
}

/** 某个节点前面最后一章的章号：前面还没有章就是 0。 */
function lastChapterBefore(root: VNode, id: string): number {
  let last = 0
  let found = false
  const walk = (node: VNode) => {
    if (found) return
    if (node.id === id) {
      found = true
      return
    }
    if (node.kind === '章') last = node.range?.[1] ?? chapterNumberOf(node)
    else if (node.range && !node.children?.length) last = Math.max(last, node.range[1])
    node.children?.forEach(walk)
  }
  walk(root)
  return last
}

/** 在节点下面加一个下一层，返回新的大纲树和新节点 id。 */
function addOutlineChild(root: VNode, parentId: string): { root: VNode; id: string } | null {
  const copy: VNode = structuredClone(root)
  const parent = findNode(copy, parentId)?.at(-1)
  const kind = parent && childKind(parent)
  if (!parent || !kind) return null
  const siblings = parent.children ?? []
  const all = (k: VNode['kind']) => {
    let n = 0
    const walk = (x: VNode) => { if (x.kind === k) n++; x.children?.forEach(walk) }
    walk(copy)
    return n
  }
  const title = kind === '篇' ? `第${cn(siblings.length + 1)}篇　` : kind === '卷' ? `第${cn(all('卷') + 1)}卷　` : kind === '单元' ? `单元${cn(siblings.length + 1)}　` : '新的一章'
  const id = `added-${nextLocal++}`
  parent.children = [...siblings, { id, kind, title, text: '', uses: [], ...(kind === '章' ? { sections: [{ label: '发生什么', text: '' }, { label: '看点', text: '' }, { label: '结尾钩子', text: '' }] } : {}) }]
  numberChapters(copy, true)
  return { root: copy, id }
}

/** 在某一个的前面或后面插一个同一层的：原型用。 */
function insertOutlineSibling(root: VNode, siblingId: string, where: 'before' | 'after'): { root: VNode; id: string } | null {
  const copy: VNode = structuredClone(root)
  const path = findNode(copy, siblingId)
  const sibling = path?.at(-1)
  const parent = path?.at(-2)
  if (!sibling || !parent?.children) return null
  const id = `added-${nextLocal++}`
  const kind = sibling.kind
  const title = kind === '章' ? '新的一章' : `${splitTitle(sibling.title)[0]}　`
  const node: VNode = { id, kind, title, text: '', uses: [], ...(kind === '章' ? { sections: [{ label: '发生什么', text: '' }, { label: '看点', text: '' }, { label: '结尾钩子', text: '' }] } : {}) }
  const at = parent.children.indexOf(sibling) + (where === 'after' ? 1 : 0)
  parent.children = [...parent.children.slice(0, at), node, ...parent.children.slice(at)]
  numberChapters(copy, true)
  return { root: copy, id }
}

/** 在某一类里新建一条空的：照这一类的样子。 */
export function blankEntry(category: VCategory): VEntry {
  const id = `draft-${nextLocal++}`
  const base = { id, category: category.name, name: '', oneLine: '', tags: [], locked: false, facts: [] as VEntry['facts'], sections: [] as VEntry['sections'], appears: [] }
  // 栏目由这本书这一类的栏目去摆，这里只定是哪种卡
  if (category.name === '角色列表' && !category.custom) {
    return { ...base, kind: 'character', role: '配角', sections: CHARACTER_FIELDS.map((key) => ({ key, label: key, text: '' })) }
  }
  if (category.name === '金手指' && !category.custom) return { ...base, kind: 'goldfinger', tags: ['金手指'] }
  if ((category.name === '等级体系' && !category.custom) || category.custom?.style === 'ladder') return { ...base, kind: 'ladder', overview: '', levels: [{ name: '', text: '' }, { name: '', text: '' }] }
  return { ...base, kind: 'paragraph' }
}

/** 编辑部帮写的候选变成一条新卡片：照这一类的样子摆，按这本书的栏目放内容。 */
export function draftToEntry(category: VCategory, template: CardTemplate, item: DraftItem): VEntry {
  const blank = blankEntry(category)
  if (blank.kind === 'ladder') return { ...blank, name: item.name, overview: item.values['总说明'] ?? '', levels: item.levels }
  const filled = withFields({ ...applyTemplate(blank, template), name: item.name }, item.values)
  return filled
}

/** 找一条：草稿也算。 */
export function entryIn(book: VBook, drafts: VEntry[], id: string): VEntry | undefined {
  return findEntry(book, id) ?? drafts.find((d) => d.id === id)
}
