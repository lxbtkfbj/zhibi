/** 真书：读出来转成工作台的样子，改了就存回服务器。 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef } from 'react'
import { del, get, patch, post, put } from '../../api/client'
import type { LibraryItem, LibrarySnapshot } from '../../api/library'
import type { ChapterBrief } from '../../api/types'
import type { OutlineTree } from '../../lib/outlineTree'
import type { WorkspaceActions } from './actions'
import { type ApiParts, CHARACTER_COLUMNS, ENTRY_CATEGORY, WORLD_OVERVIEW, bookFromApi, contentKey } from './fromApi'
import type { VEntry } from './model'

export const workspaceKey = (bookId: string) => ['workspace', bookId] as const

async function loadParts(bookId: string): Promise<ApiParts> {
  const [book, library, outline, bible, chapters] = await Promise.all([
    get<ApiParts['book']>(`/books/${bookId}`),
    get<LibrarySnapshot>(`/books/${bookId}/library`),
    get<OutlineTree>(`/books/${bookId}/outline-tree`),
    get<{ relationships: ApiParts['relationships'] }>(`/books/${bookId}/bible`),
    get<ChapterBrief[]>(`/books/${bookId}/chapters?with_outline=true`),
  ])
  return { book, library, outline, relationships: bible.relationships ?? [], chapters }
}

const splitNames = (value: string) => value.split(/[、,，;；\s]+/).map((v) => v.trim()).filter(Boolean)

/** 角色的几栏 → 角色那一行的列；没有专门一列的放 extra。 */
function characterBody(fields: Record<string, string>): Partial<LibraryItem> & { extra?: Record<string, string> } {
  const body: Record<string, unknown> = {}
  const extra: Record<string, string> = {}
  for (const [key, value] of Object.entries(fields)) {
    const column = CHARACTER_COLUMNS[key]
    if (column === 'role_type') body.role_type = value.trim() || '配角'
    else if (column === 'aliases') body.aliases = splitNames(value)
    else if (column) body[column] = value
    else extra[key] = value
  }
  if (Object.keys(extra).length) body.extra = extra
  return body
}

/** 设定条目的几栏 → 「内容」进 content，其余按栏目名合进 fields。 */
function entryBody(category: string, fields: Record<string, string>): { content?: string; field_values?: Record<string, string> } {
  const body: { content?: string; field_values?: Record<string, string> } = {}
  for (const [key, value] of Object.entries(fields)) {
    if (key === contentKey(category)) body.content = value
    else body.field_values = { ...body.field_values, [key]: value }
  }
  return body
}

/** 章纲三栏 → 章节的 outline：「发生什么」第一行是目标，下面每行一个场景。 */
function chapterOutline(sections: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if ('发生什么' in sections) {
    const lines = sections['发生什么'].split('\n').map((line) => line.trim()).filter(Boolean)
    out.goal = lines[0] ?? ''
    out.scenes = lines.slice(1)
  }
  if ('看点' in sections) out.cool_point = sections['看点']
  if ('结尾钩子' in sections) out.hook = sections['结尾钩子']
  return out
}

/** 新加的卷排在哪一卷后面：这一篇（和它前面的篇）最后一卷；没分篇的书就是全书最后一卷。 */
function lastVolume(tree: OutlineTree | undefined, nodeId?: string): string | null {
  if (!tree) return null
  const upTo = nodeId ? tree.arcs.findIndex((a) => a.node_id === nodeId) : tree.arcs.length - 1
  const volumes = tree.arcs.slice(0, upTo + 1).flatMap((a) => a.volumes)
  return volumes.at(-1)?.id ?? null
}

/** 卡片上所有栏目的内容，按 key。 */
function fieldsOf(entry: VEntry): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of entry.facts) out[f[3] ?? f[0]] = f[1]
  for (const s of entry.sections) out[s.key ?? s.label] = s.text
  return out
}

export function useLiveBook(bookId: string) {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: workspaceKey(bookId), queryFn: () => loadParts(bookId) })
  const book = useMemo(() => (query.data ? bookFromApi(query.data) : undefined), [query.data])
  const parts = useRef<ApiParts | undefined>(undefined)
  useEffect(() => { parts.current = query.data }, [query.data])

  const actions = useMemo<WorkspaceActions>(() => {
    const refresh = () => qc.invalidateQueries({ queryKey: workspaceKey(bookId) })
    // 改完刷新整本书；其他页面（旧版书页、书架）下次打开再读
    const done = async <T,>(task: Promise<T>): Promise<T> => {
      const result = await task
      await refresh()
      void qc.invalidateQueries({ queryKey: ['book', bookId] })
      void qc.invalidateQueries({ queryKey: ['books'] })
      return result
    }
    const isCharacter = (entry: VEntry) => entry.kind === 'character'
    const concept = (value: Record<string, unknown>) => done(patch(`/books/${bookId}`, { concept: value, review_changes: false }))
    return {
      live: true,
      saveBook: async (change) => {
        if (change.title !== undefined) await done(patch(`/books/${bookId}`, { title: change.title.trim() || '未命名', review_changes: false }))
        const value: Record<string, unknown> = {}
        if (change.blurb !== undefined) value.story = change.blurb
        if (change.channel !== undefined) value.channel = change.channel
        if (change.genre !== undefined) value.genre = change.genre
        if (change.tags !== undefined) value.tags = change.tags
        if (change.length !== undefined) value.target_length = change.length
        if (Object.keys(value).length) await concept(value)
      },
      saveWorld: async (text) => {
        const row = parts.current?.library.entries.find((e) => e.category === '世界与地图' && e.name.trim() === WORLD_OVERVIEW)
        if (row) await done(patch(`/world-entries/${row.id}`, { content: text }))
        else if (text.trim()) await done(post(`/books/${bookId}/world-entries`, { category: '世界与地图', name: WORLD_OVERVIEW, content: text }))
      },
      saveEntry: async (entry, change) => {
        if (entry.readonly) return
        const body: Record<string, unknown> = {}
        if (change.name !== undefined) body.name = change.name.trim()
        if (change.oneLine !== undefined) body.one_line = change.oneLine
        if (change.locked !== undefined) body.locked = change.locked
        if (isCharacter(entry)) {
          Object.assign(body, characterBody(change.fields ?? {}))
          await done(patch(`/characters/${entry.id}`, body))
          return
        }
        if (change.overview !== undefined) body.content = change.overview
        if (change.levels !== undefined) body.levels = change.levels
        Object.assign(body, entryBody(entry.category, change.fields ?? {}))
        await done(patch(`/world-entries/${entry.id}`, body))
      },
      createEntry: async (category, draft) => {
        const fields = fieldsOf(draft)
        if (isCharacter(draft)) {
          const row = await done(post<LibraryItem>(`/books/${bookId}/characters`, { name: draft.name.trim(), one_line: draft.oneLine, ...characterBody(fields) }))
          return row.id
        }
        const { content, field_values } = entryBody(draft.category, fields)
        const row = await done(post<LibraryItem>(`/books/${bookId}/world-entries`, {
          category: category.custom ? category.key : ENTRY_CATEGORY[category.name] ?? '特殊规则',
          name: draft.name.trim(),
          one_line: draft.oneLine,
          content: draft.kind === 'ladder' ? draft.overview ?? '' : content ?? '',
          fields: Object.entries(field_values ?? {}).filter(([, v]) => v.trim()).map(([name, value]) => ({ name, value })),
          ...(draft.kind === 'ladder' ? { levels: draft.levels ?? [] } : {}),
          tags: draft.tags,
        }))
        return row.id
      },
      deleteEntry: (entry) => done(del(`/${isCharacter(entry) ? 'characters' : 'world-entries'}/${entry.id}`)).then(() => undefined),
      saveRelation: async (entry, relation, text) => {
        if (relation.toLead) await done(patch(`/characters/${entry.id}`, { relation: text }))
        else if (relation.id) await done(patch(`/relationships/${relation.id}`, { description: text }))
      },
      addRelation: (entry, to, kind, text) => done(post(`/books/${bookId}/relationships`, { source_id: entry.id, target_id: to, kind, description: text })).then(() => undefined),
      deleteRelation: async (entry, relation) => {
        if (relation.toLead) await done(patch(`/characters/${entry.id}`, { relation: '' }))
        else if (relation.id) await done(del(`/relationships/${relation.id}`))
      },
      saveTemplate: (category, template, dropped) => done(put(`/books/${bookId}/card-layouts/${encodeURIComponent(category.key)}`, { ...template, dropped })).then(() => undefined),
      resetTemplate: (category) => done(del(`/books/${bookId}/card-layouts/${encodeURIComponent(category.key)}`)).then(() => undefined),
      createCategory: (name, style, fields, about) => done(post(`/books/${bookId}/setting-categories`, { name, style, fields, hint: about })).then(() => undefined),
      saveNode: async (node, change) => {
        const ref = node.ref
        if (!ref) return
        if (ref.type === 'volume') await done(patch(`/volumes/${ref.id}`, { ...(change.name !== undefined ? { title: change.name } : {}), ...(change.text !== undefined ? { summary: change.text } : {}) }))
        else if (ref.type === 'unit') await done(patch(`/units/${ref.id}`, { ...(change.name !== undefined ? { title: change.name } : {}), ...(change.text !== undefined ? { summary: change.text } : {}) }))
        else if (ref.type === 'chapter') {
          const body: Record<string, unknown> = {}
          if (change.name) body.title = change.name
          if (change.sections) body.outline = chapterOutline(change.sections)
          if (Object.keys(body).length) await done(patch(`/books/${bookId}/chapters/${ref.id}`, body))
        }
        else if (ref.type === 'book' && change.text !== undefined) await concept({ ending: change.text })
        else if (ref.type === 'segment' && node.kind === '全书' && change.text !== undefined) await done(patch(`/nodes/${ref.id}`, { event: change.text }))
        // 写到再定的篇：名字和那段话就是节点上的
        else if (ref.type === 'segment' && node.later) await done(patch(`/nodes/${ref.id}`, { ...(change.name !== undefined ? { title: change.name } : {}), ...(change.text !== undefined ? { event: change.text } : {}) }))
        else if (ref.type === 'segment') await done(patch(`/nodes/${ref.id}`, { segment: { ...(change.name !== undefined ? { title: change.name } : {}), ...(change.text !== undefined ? { text: change.text } : {}) } }))
      },
      // 新加的都排在同一层的最后面
      addNode: async (parent) => {
        const ref = parent.ref
        const tree = parts.current?.outline
        if (parent.kind === '全书' && parent.childKind === '篇') return `a:${(await done(post<{ id: string }>(`/books/${bookId}/arcs`, {}))).id}`
        if (parent.kind === '全书' && parent.childKind === '卷') return `v:${(await done(post<{ id: string }>(`/books/${bookId}/volumes`, { after_volume_id: lastVolume(tree) }))).id}`
        if (parent.kind === '篇' && ref?.type === 'segment') return `v:${(await done(post<{ id: string }>(`/books/${bookId}/volumes`, { target_node_id: ref.id, after_volume_id: lastVolume(tree, ref.id) }))).id}`
        if (parent.kind === '卷' && ref) {
          const units = tree?.arcs.flatMap((a) => a.volumes).find((v) => v.id === ref.id)?.units ?? []
          return `u:${(await done(post<{ id: string }>(`/volumes/${ref.id}/units`, { after_unit_id: units.at(-1)?.id ?? null }))).id}`
        }
        if (parent.kind === '单元' && ref) return `c${(await done(post<{ index: number }>(`/units/${ref.id}/chapters`, {}))).index}`
        return undefined
      },
      deleteNode: async (node) => {
        if (node.ref?.type === 'volume') await done(del(`/volumes/${node.ref.id}`))
        else if (node.ref?.type === 'unit') await done(del(`/units/${node.ref.id}`))
        else if (node.ref?.type === 'chapter') await done(del(`/books/${bookId}/chapters/${node.ref.id}`))
        else if (node.ref?.type === 'segment' && node.kind === '篇') await done(del(`/arcs/${node.ref.id}`))
      },
      canAdd: (parent) => {
        if (parent.kind === '全书') return parent.childKind === '篇' || parent.childKind === '卷'
        if (parent.kind === '篇') return parent.ref?.type === 'segment' && (!parent.later || !!parent.next)
        if (parent.kind === '卷') return !!parent.ref
        if (parent.kind === '单元') return !!parent.ref && parent.progress !== '已写完'
        return false
      },
      canEdit: (node, part) => {
        if (!node.ref) return false
        if (node.kind === '全书') return part === 'text'
        // 章纲只有还没开写的能改
        if (node.kind === '章') return part === 'name' || node.progress === '已规划'
        return true
      },
      canDelete: (node) => {
        if (node.ref?.type === 'volume' || node.ref?.type === 'unit') return true
        if (node.kind === '章') return !!node.ref && node.progress === '已规划'
        // 篇下面还有卷的，先删卷
        return node.kind === '篇' && !!node.ref && !node.children?.length
      },
    }
  }, [bookId, qc])

  return { book, actions, loading: query.isPending, error: query.error, raw: query.data }
}
