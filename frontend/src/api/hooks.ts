import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { del, get, patch, post, put } from './client'
import { initialWriteRequest, waitForSetupCompletion } from '../lib/setupThree'
import type {
  Bible,
  BookDetail,
  BookSummary,
  Chapter,
  ChapterBrief,
  Character,
  Foreshadowing,
  Health,
  Job,
  LlmProfile,
  LlmProfileInput,
  MeetingMessage,
  NodeAnchor,
  Outline,
  PlotUnit,
  Protagonist,
  Relationship,
  RoleAssignments,
  Secret,
  SegmentPlan,
  SetupPiece,
  StoryNode,
  StoryThread,
  TeamRole,
  Usage,
  Volume,
  WorldEntry,
  World,
  WriteUntil,
} from './types'

const decisionRequests = new Map<string, Promise<Job>>()

export const keys = {
  books: ['books'] as const,
  book: (id: string) => ['book', id] as const,
  outline: (id: string) => ['outline', id] as const,
  bible: (id: string) => ['bible', id] as const,
  threads: (id: string) => ['threads', id] as const,
  nodes: (id: string) => ['nodes', id] as const,
  secrets: (id: string) => ['secrets', id] as const,
  /** 前缀：失效时连同按卷筛选的目录、单章一起刷新 */
  chapters: (id: string) => ['chapters', id] as const,
  chapterList: (id: string, volume?: number) => ['chapters', id, 'list', volume ?? 'all'] as const,
  chapter: (id: string, index: number) => ['chapters', id, 'one', index] as const,
  usage: (id: string) => ['usage', id] as const,
  profiles: ['profiles'] as const,
  roles: ['roles'] as const,
  health: ['health'] as const,
  glossary: ['glossary'] as const,
}

export const useBooks = () => useQuery({ queryKey: keys.books, queryFn: () => get<BookSummary[]>('/books') })
export const useBook = (id: string) => useQuery({ queryKey: keys.book(id), queryFn: () => get<BookDetail>(`/books/${id}`) })
export const useOutline = (id: string) =>
  useQuery({ queryKey: keys.outline(id), queryFn: () => get<Outline>(`/books/${id}/outline`) })
export const useBible = (id: string) => useQuery({ queryKey: keys.bible(id), queryFn: () => get<Bible>(`/books/${id}/bible`) })
export const useThreads = (id: string) =>
  useQuery({ queryKey: keys.threads(id), queryFn: () => get<StoryThread[]>(`/books/${id}/threads`) })
export const useNodes = (id: string) =>
  useQuery({ queryKey: keys.nodes(id), queryFn: () => get<StoryNode[]>(`/books/${id}/nodes`) })
export const useSecrets = (id: string) =>
  useQuery({ queryKey: keys.secrets(id), queryFn: () => get<Secret[]>(`/books/${id}/secrets`) })
export const useGlossary = () => useQuery({ queryKey: keys.glossary, queryFn: () => get<{ terms: { term: string; explanation: string }[] }>('/glossary'), staleTime: Infinity, gcTime: Infinity })
/** 章节目录；指定 volume 时只列这一卷，并带上章纲。 */
export const useChapters = (id: string, volume?: number) =>
  useQuery({
    queryKey: keys.chapterList(id, volume),
    queryFn: () => get<ChapterBrief[]>(`/books/${id}/chapters${volume ? `?volume=${volume}` : ''}`),
  })
export const useChapter = (id: string, index: number) =>
  useQuery({ queryKey: keys.chapter(id, index), queryFn: () => get<Chapter>(`/books/${id}/chapters/${index}`), retry: false })
export const useUsage = (id: string) => useQuery({ queryKey: keys.usage(id), queryFn: () => get<Usage>(`/books/${id}/usage`) })
export const useHealth = () =>
  useQuery({ queryKey: keys.health, queryFn: () => get<Health>('/health'), refetchInterval: 30_000, retry: false })

export function useCreateBook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { idea: string; style_reference: string; ask?: boolean; prefill?: boolean; mode?: 'puzzle' | 'oneshot' }) =>
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
      body: Partial<{ title: string; style_reference: string; concept: Record<string, unknown>; spine: Record<string, unknown>; protagonist: Partial<Protagonist>; world: Partial<World> }>,
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

type NodeFields = 'title' | 'event' | 'prerequisite' | 'consequence' | 'volume' | 'status'

export function useNodeMutations(bookId: string) {
  const qc = useQueryClient()
  const refresh = () => {
    for (const queryKey of [keys.nodes(bookId), keys.outline(bookId), keys.bible(bookId), keys.secrets(bookId)]) {
      void qc.invalidateQueries({ queryKey })
    }
  }
  const create = useMutation({
    mutationFn: (body: Pick<StoryNode, 'title'> & Partial<Pick<StoryNode, Exclude<NodeFields, 'title'>>> & { after_node_id?: string }) =>
      post<StoryNode>(`/books/${bookId}/nodes`, body),
    onSuccess: refresh,
  })
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; segment?: Partial<SegmentPlan> } & Partial<Pick<StoryNode, NodeFields | 'editor_note'>>) =>
      patch<StoryNode>(`/nodes/${id}`, body),
    onSuccess: (node) => qc.setQueryData<StoryNode[]>(keys.nodes(bookId), (old) => patchInCache(old, node)),
  })
  const remove = useMutation({ mutationFn: (id: string) => del(`/nodes/${id}`), onSuccess: refresh })
  const reorder = useMutation({
    mutationFn: (ids: string[]) => post<StoryNode[]>(`/books/${bookId}/nodes/order`, { ids }),
    onSuccess: refresh,
  })
  return { create, update, remove, reorder }
}

export function useUpdateThread(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<Pick<StoryThread, 'name' | 'summary' | 'characters' | 'beats'>>) =>
      patch<StoryThread>(`/threads/${id}`, body),
    onSuccess: (thread) => qc.setQueryData<StoryThread[]>(keys.threads(bookId), (old) => patchInCache(old, thread)),
  })
}

export function useUpdateChapter(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ index, ...body }: { index: number; title?: string; content?: string }) =>
      patch<Chapter>(`/books/${bookId}/chapters/${index}`, body),
    onSuccess: (chapter) => {
      qc.setQueryData(keys.chapter(bookId, chapter.index), chapter)
      qc.invalidateQueries({ queryKey: keys.chapterList(bookId) })
    },
  })
}

type VolumeFields = 'want' | 'pressure' | 'title' | 'stage' | 'summary' | 'goal' | 'climax' | 'antagonist' | 'power_range' | 'chapter_count' | 'new_characters'

export function useUpdateVolume(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<Pick<Volume, VolumeFields>>) =>
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
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.bible(bookId) })
    if (list === 'characters') {
      void qc.invalidateQueries({ queryKey: keys.nodes(bookId) })
      void qc.invalidateQueries({ queryKey: keys.secrets(bookId) })
    }
  }
  const create = useMutation({
    mutationFn: (body: Partial<BibleItem[K]>) => post<BibleItem[K]>(`/books/${bookId}/${route.create}`, body),
    onSuccess: refresh,
  })
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<BibleItem[K]>) =>
      patch<BibleItem[K]>(`/${route.item}/${id}`, body),
    onSuccess: (item) => {
      qc.setQueryData<Bible>(keys.bible(bookId), (old) =>
        old ? { ...old, [list]: patchInCache(old[list] as BibleItem[K][], item) } : old,
      )
      if (list === 'characters') refresh()
    },
  })
  const remove = useMutation({ mutationFn: (id: string) => del(`/${route.item}/${id}`), onSuccess: refresh })
  return { create, update, remove }
}

export function useAnchorMutations(bookId: string) {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.nodes(bookId) })
    void qc.invalidateQueries({ queryKey: keys.bible(bookId) })
  }
  type Fields = Pick<NodeAnchor, 'node_id' | 'character_id' | 'kind' | 'note'>
  const create = useMutation({ mutationFn: (body: Fields) => post<NodeAnchor>(`/books/${bookId}/anchors`, body), onSuccess: refresh })
  const update = useMutation({ mutationFn: ({ id, ...body }: { id: string } & Partial<Fields>) => patch<NodeAnchor>(`/anchors/${id}`, body), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: string) => del(`/anchors/${id}`), onSuccess: refresh })
  return { create, update, remove }
}

export function useSecretMutations(bookId: string) {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.secrets(bookId) })
    void qc.invalidateQueries({ queryKey: keys.bible(bookId) })
  }
  type Fields = Pick<Secret, 'title' | 'truth' | 'knowers' | 'reader_knows' | 'reveal_plan' | 'node_id' | 'status'>
  const create = useMutation({ mutationFn: (body: Partial<Fields>) => post<Secret>(`/books/${bookId}/secrets`, body), onSuccess: refresh })
  const update = useMutation({ mutationFn: ({ id, ...body }: { id: string } & Partial<Fields>) => patch<Secret>(`/secrets/${id}`, body), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: string) => del(`/secrets/${id}`), onSuccess: refresh })
  return { create, update, remove }
}

export function useJobActions(bookId: string) {
  const qc = useQueryClient()
  // 拍板条与对话框共享锁定状态，避免确认和修改意见同时提交。
  const segmentKey = ['segment-decision', bookId]
  const segmentPending = useIsMutating({ mutationKey: segmentKey }) > 0
  const setupKey = ['setup-decision', bookId]
  const setupPending = useIsMutating({ mutationKey: setupKey }) > 0
  const decisionKey = ['writing-decision', bookId]
  const decisionPending = useIsMutating({ mutationKey: decisionKey }) > 0
  const setJob = (job: Job) =>
    qc.setQueryData<BookDetail>(keys.book(bookId), (old) => (old ? { ...old, active_job: job } : old))
  const pitches = useMutation({
    mutationKey: setupKey,
    mutationFn: ({ jobId, ...body }: { jobId: string; action: 'pick' | 'redo' | 'start'; index?: number; title?: string; length?: number; feedback?: string }) => post<Job>(`/jobs/${jobId}/pitches`, body),
    onSuccess: setJob,
  })
  const directions = useMutation({
      mutationFn: ({ jobId, ...body }: { jobId: string; action: 'choose' | 'redo'; choice?: number; title?: string; mix?: string; length?: string; feedback?: string }) =>
        post<Job>(`/jobs/${jobId}/directions`, body),
      onSuccess: setJob,
    })
  const piece = useMutation({
      mutationKey: setupKey,
      mutationFn: ({ jobId, ...body }: { jobId: string; action: 'confirm' | 'delegate' | 'revise' | 'candidates' | 'fill' | 'reopen' | 'unlock'; piece: SetupPiece; feedback?: string; node_id?: string; flips?: { topic: string; choice: string }[] }) =>
        post<Job>(`/jobs/${jobId}/piece`, body),
      onSuccess: setJob,
    })
  const chooseDirection = useMutation({
    mutationFn: ({ jobId, ...body }: { jobId: string; choice: number; title?: string; mix?: string; length?: string }) => post<Job>(`/jobs/${jobId}/directions`, { ...body, action: 'choose' }),
    onSuccess: setJob,
  })
  const redoDirections = useMutation({
    mutationFn: ({ jobId, feedback }: { jobId: string; feedback: string }) => post<Job>(`/jobs/${jobId}/directions`, { action: 'redo', feedback }),
    onSuccess: setJob,
  })
  return {
    pitches, directions, chooseDirection, redoDirections, piece, pieceAction: piece, segmentPending, setupPending, decisionPending,
    confirmSetupAndWrite: useMutation({
      mutationKey: setupKey,
      mutationFn: async ({ jobId, book, action }: { jobId: string; book: BookDetail; action: 'confirm' | 'delegate' }) => {
        setJob(await post<Job>(`/jobs/${jobId}/piece`, { action, piece: 'outline' }))
        await waitForSetupCompletion(() => get<Job>(`/jobs/${jobId}`), () => new Promise(resolve => setTimeout(resolve, 1000)))
        return post<Job>(`/books/${bookId}/write`, initialWriteRequest(book))
      },
      onSuccess: job => {
        qc.setQueryData<BookDetail>(keys.book(bookId), old => old ? { ...old, status: 'writing', active_job: job } : old)
        void qc.invalidateQueries({ queryKey: keys.books })
      },
    }),
    segment: useMutation({
      mutationKey: segmentKey,
      mutationFn: ({ jobId, ...body }: { jobId: string; action: 'confirm' | 'delegate' | 'revise' | 'redo'; feedback?: string; flips?: { topic: string; choice: string }[]; pin_end?: boolean }) =>
        post<Job>(`/jobs/${jobId}/segment`, body),
      onSuccess: setJob,
    }),
    decide: useMutation({
      mutationKey: decisionKey,
      mutationFn: ({ jobId, action, feedback }: { jobId: string; action: 'approve' | 'revise'; feedback?: string }) => {
        const active = decisionRequests.get(jobId)
        if (active) return Promise.reject(new Error('正在提交决定，请等这一步完成'))
        const request = post<Job>(`/jobs/${jobId}/decision`, { action, feedback: feedback ?? '' }).finally(() => decisionRequests.delete(jobId))
        decisionRequests.set(jobId, request)
        return request
      },
      onSuccess: setJob,
    }),
    write: useMutation({
      mutationFn: (body: { until: WriteUntil; count: number }) => post<Job>(`/books/${bookId}/write`, body),
      onSuccess: (job) => {
        qc.setQueryData<BookDetail>(keys.book(bookId), (old) => (old ? { ...old, status: 'writing', active_job: job } : old))
        qc.invalidateQueries({ queryKey: keys.books })
      },
    }),
    answer: useMutation({
      mutationFn: ({ jobId, answers, extra }: { jobId: string; answers: { index: number; answer: string }[]; extra: string }) =>
        post<Job>(`/jobs/${jobId}/answers`, { answers, extra }),
      onSuccess: setJob,
    }),
    note: useMutation({
      mutationFn: (body: string | { content: string; to?: TeamRole }) =>
        post<MeetingMessage>(`/books/${bookId}/notes`, typeof body === 'string' ? { content: body } : body),
      onSuccess: () => qc.invalidateQueries({ queryKey: keys.book(bookId) }),
    }),
    /** 按作者的意见重写一章已定稿的章节；后面还有定稿章节时要 confirm。 */
    rewrite: useMutation({
      mutationFn: ({ index, feedback, confirm }: { index: number; feedback: string; confirm: boolean }) =>
        post<Job>(`/books/${bookId}/chapters/${index}/rewrite`, { feedback, confirm }),
      onSuccess: setJob,
    }),
    restartSetup: useMutation({
      mutationKey: ['restart-setup', bookId],
      mutationFn: (jobId: string) => post<Job>(`/jobs/${jobId}/restart-setup`),
      onSuccess: (job) => {
        setJob(job)
        for (const key of [keys.book(bookId), keys.outline(bookId), keys.bible(bookId), keys.nodes(bookId), keys.threads(bookId), keys.secrets(bookId), keys.books]) void qc.invalidateQueries({ queryKey: key })
      },
    }),
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
