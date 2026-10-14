import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { del, get, patch, post, put } from './client'
import type {
  Bible,
  BookDetail,
  BookSummary,
  Character,
  Foreshadowing,
  Health,
  Job,
  LlmProfile,
  LlmProfileInput,
  MeetingMessage,
  Outline,
  PlotUnit,
  Relationship,
  RoleAssignments,
  Usage,
  Volume,
  WorldEntry,
} from './types'

export const keys = {
  books: ['books'] as const,
  book: (id: string) => ['book', id] as const,
  outline: (id: string) => ['outline', id] as const,
  bible: (id: string) => ['bible', id] as const,
  usage: (id: string) => ['usage', id] as const,
  profiles: ['profiles'] as const,
  roles: ['roles'] as const,
  health: ['health'] as const,
}

export const useBooks = () => useQuery({ queryKey: keys.books, queryFn: () => get<BookSummary[]>('/books') })
export const useBook = (id: string) => useQuery({ queryKey: keys.book(id), queryFn: () => get<BookDetail>(`/books/${id}`) })
export const useOutline = (id: string) =>
  useQuery({ queryKey: keys.outline(id), queryFn: () => get<Outline>(`/books/${id}/outline`) })
export const useBible = (id: string) => useQuery({ queryKey: keys.bible(id), queryFn: () => get<Bible>(`/books/${id}/bible`) })
export const useUsage = (id: string) => useQuery({ queryKey: keys.usage(id), queryFn: () => get<Usage>(`/books/${id}/usage`) })
export const useHealth = () =>
  useQuery({ queryKey: keys.health, queryFn: () => get<Health>('/health'), refetchInterval: 30_000, retry: false })

export function useCreateBook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { idea: string; style_reference: string; ask: boolean }) =>
      post<{ book: BookDetail; job: Job }>('/books', body),
    onSuccess: (data) => {
      qc.setQueryData(keys.book(data.book.id), data.book)
      qc.invalidateQueries({ queryKey: keys.books })
    },
  })
}

export function useDeleteBook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => del(`/books/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.books }),
  })
}

export function useUpdateBook(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (
      body: Partial<{ title: string; style_reference: string; concept: Record<string, unknown>; spine: Record<string, unknown> }>,
    ) =>
      patch<BookDetail>(`/books/${bookId}`, body),
    onSuccess: (data) => {
      qc.setQueryData(keys.book(bookId), data)
      qc.invalidateQueries({ queryKey: keys.outline(bookId) })
    },
  })
}

function patchInCache<T extends { id: string }>(list: T[] | undefined, item: T): T[] | undefined {
  return list?.map((x) => (x.id === item.id ? item : x))
}

export function useUpdateVolume(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<Pick<Volume, 'title' | 'summary' | 'goal' | 'chapter_count'>>) =>
      patch<Volume>(`/volumes/${id}`, body),
    onSuccess: (volume) =>
      qc.setQueryData<Outline>(keys.outline(bookId), (old) =>
        old ? { ...old, volumes: patchInCache(old.volumes, volume)! } : old,
      ),
  })
}

export function useUpdateUnit(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<Omit<PlotUnit, 'id' | 'index'>>) =>
      patch<PlotUnit>(`/units/${id}`, body),
    onSuccess: (unit) =>
      qc.setQueryData<Outline>(keys.outline(bookId), (old) =>
        old
          ? { ...old, volumes: old.volumes.map((v) => ({ ...v, units: patchInCache(v.units, unit)! })) }
          : old,
      ),
  })
}

type BibleList = 'characters' | 'world_entries' | 'foreshadowings' | 'relationships'
const bibleRoutes: Record<BibleList, { create: string; item: string }> = {
  characters: { create: 'characters', item: 'characters' },
  world_entries: { create: 'world-entries', item: 'world-entries' },
  foreshadowings: { create: 'foreshadowings', item: 'foreshadowings' },
  relationships: { create: 'relationships', item: 'relationships' },
}

type BibleItem = {
  characters: Character
  world_entries: WorldEntry
  foreshadowings: Foreshadowing
  relationships: Relationship
}

export function useBibleMutations<K extends BibleList>(bookId: string, list: K) {
  const qc = useQueryClient()
  const route = bibleRoutes[list]
  const refresh = () => qc.invalidateQueries({ queryKey: keys.bible(bookId) })
  const create = useMutation({
    mutationFn: (body: Partial<BibleItem[K]>) => post<BibleItem[K]>(`/books/${bookId}/${route.create}`, body),
    onSuccess: refresh,
  })
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<BibleItem[K]>) =>
      patch<BibleItem[K]>(`/${route.item}/${id}`, body),
    onSuccess: (item) =>
      qc.setQueryData<Bible>(keys.bible(bookId), (old) =>
        old ? { ...old, [list]: patchInCache(old[list] as BibleItem[K][], item) } : old,
      ),
  })
  const remove = useMutation({ mutationFn: (id: string) => del(`/${route.item}/${id}`), onSuccess: refresh })
  return { create, update, remove }
}

export function useJobActions(bookId: string) {
  const qc = useQueryClient()
  const setJob = (job: Job) =>
    qc.setQueryData<BookDetail>(keys.book(bookId), (old) => (old ? { ...old, active_job: job } : old))
  return {
    decide: useMutation({
      mutationFn: ({ jobId, action, feedback }: { jobId: string; action: 'approve' | 'revise'; feedback?: string }) =>
        post<Job>(`/jobs/${jobId}/decision`, { action, feedback: feedback ?? '' }),
      onSuccess: setJob,
    }),
    answer: useMutation({
      mutationFn: ({ jobId, answers, extra }: { jobId: string; answers: { index: number; answer: string }[]; extra: string }) =>
        post<Job>(`/jobs/${jobId}/answers`, { answers, extra }),
      onSuccess: setJob,
    }),
    note: useMutation({ mutationFn: (content: string) => post<MeetingMessage>(`/books/${bookId}/notes`, { content }) }),
    resume: useMutation({ mutationFn: (jobId: string) => post<Job>(`/jobs/${jobId}/resume`), onSuccess: setJob }),
    cancel: useMutation({ mutationFn: (jobId: string) => post<Job>(`/jobs/${jobId}/cancel`), onSuccess: setJob }),
  }
}

export const useProfiles = () => useQuery({ queryKey: keys.profiles, queryFn: () => get<LlmProfile[]>('/llm/profiles') })
export const useRoles = () => useQuery({ queryKey: keys.roles, queryFn: () => get<RoleAssignments>('/llm/roles') })

export function useProfileMutations() {
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.profiles })
    qc.invalidateQueries({ queryKey: keys.roles })
  }
  return {
    create: useMutation({ mutationFn: (body: LlmProfileInput) => post<LlmProfile>('/llm/profiles', body), onSuccess: refresh }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: string } & Partial<LlmProfileInput>) => patch<LlmProfile>(`/llm/profiles/${id}`, body),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: string) => del(`/llm/profiles/${id}`), onSuccess: refresh }),
    test: useMutation({ mutationFn: (id: string) => post<{ ok: boolean; message: string }>(`/llm/profiles/${id}/test`) }),
    setRoles: useMutation({
      mutationFn: (body: Partial<RoleAssignments>) => put<RoleAssignments>('/llm/roles', body),
      onSuccess: (data) => qc.setQueryData(keys.roles, data),
    }),
  }
}
