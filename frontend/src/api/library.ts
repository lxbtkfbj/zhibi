import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { get, post } from './client'
import { keys } from './hooks'

export interface LibraryItem {
  id: string
  name: string
  one_line: string
  content?: string
  category?: string
  role_type?: string
  status: string
  tags: string[]
  locked: boolean
}
export interface LibrarySnapshot {
  categories: { key: string; name: string; count: number }[]
  characters: LibraryItem[]
  entries: LibraryItem[]
  focus: { characters: string[]; entries: string[] }
  suggestions_pending: number
}
export interface LibraryCandidate {
  id: string
  target_id: string
  path: string
  chosen: number | null
  options: { label?: string; text?: string; why?: string; recommended?: boolean }[]
}
export interface LibrarySuggestion { id: string; title: string; status: string }
export const libraryKeys = {
  snapshot: (id: string) => ['library', id] as const,
  suggestions: (id: string) => ['library-suggestions', id] as const,
  candidates: (id: string) => ['library-candidates', id] as const,
}
export const useLibrary = (id: string) => useQuery({ queryKey: libraryKeys.snapshot(id), queryFn: () => get<LibrarySnapshot>(`/books/${id}/library`) })
export const useLibrarySuggestions = (id: string) => useQuery({ queryKey: libraryKeys.suggestions(id), queryFn: () => get<LibrarySuggestion[]>(`/books/${id}/suggestions?status=pending`) })

/** 任务 3 的简版只展示已有候选；类别和条目全部从设定库接口读取。 */
export function useLibraryCandidates(id: string, library?: LibrarySnapshot) {
  const targets = library ? [...library.characters.map(item => ({ ...item, target_type: 'character' })), ...library.entries.map(item => ({ ...item, target_type: 'entry' }))] : []
  return useQuery({
    queryKey: [...libraryKeys.candidates(id), targets.map(item => item.id).join(',')],
    enabled: !!library,
    queryFn: async () => (await Promise.all(targets.map(async item => ({ name: item.name, candidates: await get<LibraryCandidate[]>(`/books/${id}/candidates?target_type=${item.target_type}&target_id=${item.id}`) })))).filter(item => item.candidates.length),
  })
}

export function useChooseLibraryCandidate(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, index }: { id: string; index: number }) => post(`/candidates/${id}/choose`, { index }),
    onSuccess: () => {
      for (const key of [libraryKeys.snapshot(bookId), libraryKeys.suggestions(bookId), libraryKeys.candidates(bookId), keys.bible(bookId)]) void qc.invalidateQueries({ queryKey: key })
    },
  })
}
