import type { LibraryItem, LibrarySnapshot, LibrarySuggestion } from '../api/library'

export type LibraryRow = LibraryItem & { targetType: 'character' | 'entry'; categoryKey: string; depth: number }
export interface LibraryFilters { category?: string | null; focus?: boolean; mustOnly?: boolean; suggestionsOnly?: boolean; search?: string }
export function suggestionTargetId(suggestion: LibrarySuggestion): string | null {
  return suggestion.target_id ?? (typeof suggestion.payload.target_id === 'string' ? suggestion.payload.target_id : null) ?? (typeof suggestion.origin.target_id === 'string' ? suggestion.origin.target_id : null)
}
export function libraryRows(snapshot: LibrarySnapshot): LibraryRow[] {
  return [
    ...snapshot.characters.map(item => ({ ...item, targetType: 'character' as const, categoryKey: '角色卡片', depth: 0 })),
    ...snapshot.entries.map(item => ({ ...item, targetType: 'entry' as const, categoryKey: item.category ?? '', depth: 0 })),
  ]
}
export function sortLibraryRows(rows: LibraryRow[], statusOrder: string[]): LibraryRow[] {
  const rank = (status: string) => { const index = statusOrder.indexOf(status); return index < 0 ? statusOrder.length : index }
  return [...rows].sort((a, b) => rank(a.status) - rank(b.status) || a.position - b.position || a.name.localeCompare(b.name, 'zh-Hans-CN') || a.id.localeCompare(b.id))
}
/** 先排序同级，再展开地方树；孤儿和旧数据中的环也不会丢条目。 */
export function worldTree(rows: LibraryRow[]): LibraryRow[] {
  const ids = new Set(rows.map(row => row.id))
  const seen = new Set<string>()
  const output: LibraryRow[] = []
  function visit(row: LibraryRow, depth: number) {
    if (seen.has(row.id)) return
    seen.add(row.id)
    output.push({ ...row, depth })
    for (const child of rows.filter(item => item.parent_id === row.id)) visit(child, depth + 1)
  }
  for (const root of rows.filter(row => !row.parent_id || !ids.has(row.parent_id))) visit(root, 0)
  for (const row of rows) visit(row, 0)
  return output
}
export function filterLibraryRows(snapshot: LibrarySnapshot, suggestions: LibrarySuggestion[], filters: LibraryFilters, statusOrder: string[]): LibraryRow[] {
  const focus = new Set([...snapshot.focus.characters, ...snapshot.focus.entries])
  const suggested = new Set(suggestions.filter(row => row.status === 'pending').map(suggestionTargetId))
  const query = (filters.search ?? '').trim().toLocaleLowerCase()
  const rows = sortLibraryRows(libraryRows(snapshot).filter(item => {
    if (filters.focus && !focus.has(item.id)) return false
    if (!filters.focus && filters.category && item.categoryKey !== filters.category) return false
    if (filters.mustOnly && item.status !== statusOrder[0]) return false
    if (filters.suggestionsOnly && !suggested.has(item.id)) return false
    if (query && ![item.name, item.one_line, item.content, ...(item.aliases ?? []), ...item.tags, ...(item.fields ?? []).map(field => `${field.name} ${field.value}`), ...(item.levels ?? []).map(level => `${level.name} ${level.text}`), item.appearance, item.personality, item.background, item.abilities, item.goal, item.relation, item.notes].join('\n').toLocaleLowerCase().includes(query)) return false
    return true
  }), statusOrder)
  return filters.category === '世界与地图' && !filters.focus ? worldTree(rows) : rows
}
/** 父级不能选自己或后代；服务端仍会再次检查引用。 */
export function parentChoices(items: LibraryItem[], item: LibraryItem): LibraryItem[] {
  const excluded = new Set([item.id])
  let changed = true
  while (changed) {
    changed = false
    for (const row of items) if (row.parent_id && excluded.has(row.parent_id) && !excluded.has(row.id)) { excluded.add(row.id); changed = true }
  }
  return items.filter(row => row.category === item.category && !excluded.has(row.id))
}
export function suggestionAction(suggestion: LibrarySuggestion): string {
  const operation = suggestion.payload.op
  if (operation === 'create_entry' || operation === 'create_character' || operation === 'create_category') return '建'
  if (suggestion.kind === 'gap' || suggestion.kind === 'fill_gap' || suggestion.kind === 'fill_gaps') return '补'
  if (operation === 'replace_in_chapters') return '前文也一起换'
  if (operation === 'note') return '知道了'
  return '改'
}
