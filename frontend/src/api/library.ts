import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { del, get, patch, post } from './client'
import { keys } from './hooks'

export type TargetType = 'entry' | 'character' | 'concept' | 'segment' | 'volume' | 'unit'
export type RewriteMode = 'options' | 'instruction' | 'expand' | 'shorten'
export type LibraryStyle = 'card' | 'ladder' | 'paragraph'
export interface LibraryField { name: string; value: string }
export interface LibraryLevel { name: string; text: string }
export interface LibraryItem {
  id: string
  name: string
  one_line: string
  content?: string
  category?: string
  role_type?: string
  /** 置顶的时间（角色） */
  pinned_at?: string | null
  status: string
  tags: string[]
  locked: boolean
  style?: LibraryStyle
  position: number
  source: string
  aliases: string[]
  fields?: LibraryField[]
  levels?: LibraryLevel[]
  parent_id?: string | null
  secret_id?: string | null
  gender?: string
  age?: string
  appearance?: string
  personality?: string
  background?: string
  abilities?: string
  goal?: string
  relation?: string
  notes?: string
  want?: string
  location?: string
  condition?: string
  is_alive?: boolean
  /** 角色没有专门一列的栏目：所属、软肋、作者自己加的…… */
  extra?: Record<string, string>
}
export interface LibraryCategory {
  id?: string
  key: string
  name: string
  style: LibraryStyle
  hint: string
  builtin: boolean
  fields?: string[]
  count: number
  must_count: number
}
export interface LibraryConfig {
  statuses: Record<string, string>
  styles: Record<string, string>
  sources: Record<string, string>
  common_tags: string[]
  focus_tags: string[]
  role_types: string[]
  legacy_role_types: Record<string, string>
  character_category: { key: string; name: string; style: LibraryStyle; hint: string; fields: { name: string; column: keyof LibraryItem }[]; state_fields: { name: string; column: keyof LibraryItem }[] }
  builtin_categories: LibraryCategory[]
}
export interface LibrarySnapshot {
  categories: LibraryCategory[]
  characters: LibraryItem[]
  entries: LibraryItem[]
  focus: { characters: string[]; entries: string[] }
  suggestions_pending: number
}
export interface LibraryCandidate {
  id: string
  target_type: TargetType
  target_id: string
  path: string
  base: string
  chosen: number | null
  created_at: string
  options: { label: string; text: string; why?: string; recommended?: boolean }[]
}
export interface LibrarySuggestion {
  id: string
  title: string
  kind: string
  target_type: TargetType | null
  target_id: string | null
  payload: Record<string, unknown>
  origin: Record<string, unknown>
  status: string
  created_at?: string
  resolved_at?: string | null
}
export interface LibraryVersion { id: string; version: number; source: string; note: string; created_at: string; snapshot: Record<string, unknown> }
export interface RewriteInput { target_type: TargetType; target_id: string; path: string; mode: RewriteMode; instruction?: string }
export interface RewriteResult { candidate?: LibraryCandidate; applied?: { path: string; before: string; after: string }; version?: number; suggestions?: LibrarySuggestion[] }
export interface ChooseResult { candidate: LibraryCandidate; target: unknown; suggestions: LibrarySuggestion[] }
export interface AcceptAllResult { accepted: string[]; skipped: { id: string; reason: string }[]; accepted_count: number; skipped_count: number }
export interface CategoryInput { name: string; style: 'card' | 'paragraph'; fields: string[]; hint: string }
export type LibraryItemPatch = Partial<Omit<LibraryItem, 'id' | 'source'>>
export const libraryKeys = {
  config: ['library-config'] as const,
  snapshot: (id: string) => ['library', id] as const,
  suggestions: (id: string) => ['library-suggestions', id] as const,
  candidates: (id: string) => ['library-candidates', id] as const,
  versions: (id: string) => ['library-versions', id] as const,
}
export const useLibraryConfig = () => useQuery({ queryKey: libraryKeys.config, queryFn: () => get<LibraryConfig>('/library-config'), staleTime: Infinity })
export const useLibrary = (id: string) => useQuery({ queryKey: libraryKeys.snapshot(id), queryFn: () => get<LibrarySnapshot>(`/books/${id}/library`) })
export const useLibrarySuggestions = (id: string) => useQuery({ queryKey: libraryKeys.suggestions(id), queryFn: () => get<LibrarySuggestion[]>(`/books/${id}/suggestions?status=pending`) })
export const useTargetCandidates = (id: string, targetType: TargetType, targetId: string, enabled = true) => useQuery({ queryKey: [...libraryKeys.candidates(id), targetType, targetId], enabled: enabled && !!targetId, queryFn: () => get<LibraryCandidate[]>(`/books/${id}/candidates?target_type=${targetType}&target_id=${targetId}`) })
export const useTargetVersions = (id: string, targetType: TargetType, targetId: string, enabled = true) => useQuery({ queryKey: [...libraryKeys.versions(id), targetType, targetId], enabled: enabled && !!targetId, queryFn: () => get<LibraryVersion[]>(`/books/${id}/versions?target_type=${targetType}&target_id=${targetId}`) })

export function useInvalidateLibrary(bookId: string) {
  const qc = useQueryClient()
  return () => Promise.all([
    libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId), libraryKeys.versions(bookId),
    keys.book(bookId), keys.bible(bookId), keys.outline(bookId), keys.nodes(bookId), keys.chapters(bookId), keys.secrets(bookId), ['outline-tree', bookId],
  ].map(queryKey => qc.invalidateQueries({ queryKey })))
}
export function useRewrite(bookId: string) {
  const invalidate = useInvalidateLibrary(bookId)
  return useMutation({ mutationFn: (body: RewriteInput) => post<RewriteResult>(`/books/${bookId}/library/rewrite`, body), onSuccess: invalidate })
}
export function useChooseLibraryCandidate(bookId: string) {
  const invalidate = useInvalidateLibrary(bookId)
  return useMutation({ mutationFn: ({ id, index }: { id: string; index: number }) => post<ChooseResult>(`/candidates/${id}/choose`, { index }), onSuccess: invalidate })
}
export function useRevertVersion(bookId: string) {
  const invalidate = useInvalidateLibrary(bookId)
  return useMutation({ mutationFn: (id: string) => post(`/versions/${id}/revert`), onSuccess: invalidate })
}
export function useLibraryItemActions(bookId: string) {
  const invalidate = useInvalidateLibrary(bookId)
  // 改一处不等其他数据刷新完：保存成功就算完成，刷新在后台进行。
  const update = useMutation({ mutationFn: ({ type, id, body }: { type: 'character' | 'entry'; id: string; body: LibraryItemPatch }) => patch<LibraryItem>(`/${type === 'character' ? 'characters' : 'world-entries'}/${id}`, body), onSuccess: () => { void invalidate() } })
  const create = useMutation({ mutationFn: ({ type, body }: { type: 'character' | 'entry'; body: LibraryItemPatch & { name: string } }) => post<LibraryItem>(`/books/${bookId}/${type === 'character' ? 'characters' : 'world-entries'}`, body), onSuccess: invalidate })
  const remove = useMutation({ mutationFn: ({ type, id }: { type: 'character' | 'entry'; id: string }) => del(`/${type === 'character' ? 'characters' : 'world-entries'}/${id}`), onSuccess: invalidate })
  return { update, create, remove }
}
export function useLibraryCategoryActions(bookId: string) {
  const invalidate = useInvalidateLibrary(bookId)
  const save = useMutation({ mutationFn: ({ id, body }: { id?: string; body: CategoryInput }) => id ? patch<LibraryCategory>(`/setting-categories/${id}`, { name: body.name, fields: body.fields, hint: body.hint }) : post<LibraryCategory>(`/books/${bookId}/setting-categories`, body), onSuccess: invalidate })
  const remove = useMutation({ mutationFn: (id: string) => del(`/setting-categories/${id}`), onSuccess: invalidate })
  return { save, remove }
}
/** 新书页待处理：同意过的（看改前改后、换回原来的），现在还能不能换回 */
export const useAcceptedSuggestions = (id: string, enabled = true) => useQuery({ queryKey: [...libraryKeys.suggestions(id), 'accepted'], enabled, queryFn: () => get<LibrarySuggestion[]>(`/books/${id}/suggestions?status=accepted`) })
export const useSuggestionChanges = (id: string, enabled = true) => useQuery({ queryKey: [...libraryKeys.suggestions(id), 'changes'], enabled, staleTime: 0, queryFn: () => get<Record<string, boolean>>(`/books/${id}/suggestion-changes`) })

export function useLibrarySuggestionActions(bookId: string) {
  const invalidate = useInvalidateLibrary(bookId)
  const resolve = useMutation({ mutationFn: ({ id, action }: { id: string; action: 'accept' | 'ignore' }) => post<LibrarySuggestion>(`/suggestions/${id}/${action}`), onSuccess: invalidate })
  const acceptAll = useMutation({ mutationFn: () => post<AcceptAllResult>(`/books/${bookId}/suggestions/accept-all`), onSuccess: invalidate })
  const inspect = useMutation({ mutationFn: (body: { mode: 'fill-gaps' | 'review' } | { mode: 'check'; target_type: 'entry' | 'character'; target_id: string }) => post(`/books/${bookId}/library/${body.mode}`, body.mode === 'check' ? { target_type: body.target_type, target_id: body.target_id } : {}), onSuccess: invalidate })
  return { resolve, acceptAll, inspect }
}
