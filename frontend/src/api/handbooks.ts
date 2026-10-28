import { del, get, post, put } from './client.ts'

export interface HandbookFields { name: string; when: string; body: string }
export interface HandbookItem {
  key: string; source: 'system' | 'mine'; enabled: boolean; name: string; when: string
  modified: boolean; saved: number; chars: number; complete: boolean; system_updated: boolean
}
export interface HandbookText extends HandbookFields { content: string }
export interface HandbookDetail extends HandbookItem, HandbookText { system: HandbookText | null }
export interface HandbookList { items: HandbookItem[]; catalog: string }
export interface HandbookSave extends HandbookFields {
  saved: number; kind: 'save' | 'create' | 'use_system' | 'restore' | 'migrated'
  saved_at: string; chars: number; restore_saved: number | null
}

const path = (key: string) => `/handbooks/${encodeURIComponent(key)}`
export const handbookApi = {
  list: () => get<HandbookList>('/handbooks'),
  detail: (key: string) => get<HandbookDetail>(path(key)),
  create: () => post<HandbookDetail>('/handbooks'),
  save: (key: string, fields: HandbookFields) => put<HandbookDetail>(path(key), fields),
  enabled: (key: string, enabled: boolean) => put<HandbookDetail>(`${path(key)}/enabled`, { enabled }),
  remove: (key: string) => del(path(key)),
  useSystem: (key: string) => post<HandbookDetail>(`${path(key)}/use-system`),
  seenSystem: (key: string) => post<HandbookDetail>(`${path(key)}/seen-system`),
  saves: (key: string) => get<HandbookSave[]>(`${path(key)}/saves`),
  snapshot: (key: string, saved: number) => get<HandbookSave>(`${path(key)}/saves/${saved}`),
  restore: (key: string, saved: number) => post<HandbookDetail>(`${path(key)}/saves/${saved}/restore`),
}
