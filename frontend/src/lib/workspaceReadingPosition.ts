import type { VBook, VNode } from '../pages/workspace/model'
import type { EssenceKey } from '../pages/workspace/desk-v2/essenceData'

/** 仅保存本次浏览器会话的阅读位置，不包含书稿、编辑草稿或写作状态。 */
export interface WorkspaceReadingPosition {
  tab: '简介' | '精髓' | '设定' | '大纲' | '正文'
  essence?: EssenceKey
  directoryVersion?: 1
  entry: string
  node: string
  chapter: string
  open: string[]
}

type ReadingBook = Pick<VBook, 'id' | 'categories' | 'outline'> & Pick<Partial<VBook>, 'source'>
type Options = { live: boolean; manuscript: boolean; explicitStart?: boolean }
const memory = new Map<string, unknown>()
const key = (bookId: string) => `zhibi:workspace-reading:${bookId}`
const tabs: WorkspaceReadingPosition['tab'][] = ['简介', '精髓', '设定', '大纲', '正文']
const essenceKeys = new Set(['overview', 'source', 'skeleton', 'link', 'fresh', 'longline', 'setting', 'shuang', 'scene', 'hero', 'cast', 'rhythm', 'opening'])

/** 书架进简介、导入后进正文首页；仅覆盖这次进入，不改变阅读记忆。 */
export function teardownEntryTab(source: unknown, state: unknown): WorkspaceReadingPosition['tab'] | undefined {
  if (source !== 'teardown' || !state || typeof state !== 'object' || Array.isArray(state)) return undefined
  const entry = state as Record<string, unknown>
  if (entry.teardownIntro === true) return '简介'
  if (entry.teardownHome === true) return '正文'
  return undefined
}

export function clearTeardownEntry(state: unknown): Record<string, unknown> | null {
  if (!state || typeof state !== 'object' || Array.isArray(state)) return null
  const next = { ...state } as Record<string, unknown>
  delete next.teardownIntro
  delete next.teardownHome
  return Object.keys(next).length ? next : null
}

export function resolveWorkspaceReadingPosition(book: ReadingBook, value: unknown, fallback: WorkspaceReadingPosition, manuscript: boolean): WorkspaceReadingPosition {
  const saved = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
  const nodes = new Set<string>(), chapters = new Set<string>()
  const visit = (node: VNode) => {
    nodes.add(node.id)
    if (node.kind === '章') chapters.add(node.id)
    node.children?.forEach(visit)
  }
  visit(book.outline)
  if (book.source === 'teardown') nodes.add('waits')
  const entries = new Set(['overview', 'world', ...book.categories.flatMap(category => [`cat:${category.name}`, ...category.entries.map(entry => entry.id)])])
  const tab = tabs.includes(saved.tab as WorkspaceReadingPosition['tab']) ? saved.tab as WorkspaceReadingPosition['tab'] : fallback.tab
  const essence = book.source === 'teardown' && typeof saved.essence === 'string' && essenceKeys.has(saved.essence) ? saved.essence as EssenceKey : fallback.essence
  const expandables = new Set([...nodes, 'world', ...book.categories.map(category => `cat:${category.name}`)])
  return {
    tab: tab === '精髓' && book.source !== 'teardown' ? fallback.tab === '精髓' ? '设定' : fallback.tab : tab === '正文' && !manuscript ? '设定' : tab,
    ...(essence === undefined ? {} : { essence }),
    ...(saved.directoryVersion === 1 ? { directoryVersion: 1 as const } : {}),
    entry: typeof saved.entry === 'string' && !saved.entry.startsWith('draft-') && entries.has(saved.entry) ? saved.entry : fallback.entry,
    node: typeof saved.node === 'string' && nodes.has(saved.node) ? saved.node : fallback.node,
    chapter: typeof saved.chapter === 'string' && (saved.chapter === 'home' || chapters.has(saved.chapter)) ? saved.chapter : fallback.chapter,
    open: Array.isArray(saved.open) ? [...new Set(saved.open.filter((id): id is string => typeof id === 'string' && expandables.has(id)))] : [...fallback.open],
  }
}

export function readWorkspaceReadingPosition(book: ReadingBook, fallback: WorkspaceReadingPosition, options: Options): WorkspaceReadingPosition {
  // 原型或显式直达链接仍按传入的 start 打开，不读取其他会话位置。
  if (!options.live || options.explicitStart) return { ...fallback, open: [...fallback.open] }
  let value = memory.get(book.id)
  try {
    const stored = sessionStorage.getItem(key(book.id))
    if (stored !== null) value = JSON.parse(stored)
  } catch { /* 浏览器禁用存储、或旧记录损坏时，保留安全的内存/默认回退。 */ }
  return resolveWorkspaceReadingPosition(book, value, fallback, options.manuscript)
}

export function writeWorkspaceReadingPosition(book: ReadingBook, position: WorkspaceReadingPosition, fallback: WorkspaceReadingPosition, options: Options): void {
  if (!options.live) return
  // 只取白名单 UI 字段，并用真书过滤未保存的 draft-* 和已删除的条目。
  const saved = resolveWorkspaceReadingPosition(book, position, fallback, options.manuscript)
  memory.set(book.id, saved)
  try { sessionStorage.setItem(key(book.id), JSON.stringify(saved)) } catch { /* 存储不可用时仍支持本次页面往返。 */ }
}
