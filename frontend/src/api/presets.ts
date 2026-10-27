import { ApiError } from './client.ts'

export type PresetSource = 'system' | 'mine'
export type PresetRole = 'system' | 'user' | 'assistant'
export type PresetWhen = 'always' | 'can_act' | 'ask_only' | 'skills' | 'teardowns' | 'web'
export interface PresetHistory { version: number; date: string; change: string }
export interface PresetBlock {
  id: string; title: string; role: PresetRole; enabled: boolean; required: boolean
  when: PresetWhen; content: string
  without?: string; origin?: string; change?: string; history?: PresetHistory[]
}
export interface PresetIssue {
  severity: 'error' | 'warning'; code: string; block_id: string | null; title: string | null; message: string
}
export interface PresetVersion { kind: string; name: string; version: number; date: string; note: string; source?: 'system' }
export interface SystemPreset extends PresetVersion { source: 'system'; blocks: PresetBlock[] }
export type PresetBasis = { source: 'system'; version: number } | { source: 'mine'; id: string; saved: number; system_version?: number } | { source: 'import' }
export interface MinePresetSummary {
  id: string; source: 'mine'; kind: string; name: string; based_on: PresetBasis
  block_count: number; enabled_count: number; saved: number; created_at: string; updated_at: string
}
export interface MinePreset extends MinePresetSummary {
  blocks: PresetBlock[]; issues: PresetIssue[]; system_newer?: Pick<PresetVersion, 'version' | 'date' | 'note'>
}
export type PresetDetail = SystemPreset | MinePreset
export interface PresetSelection { source: PresetSource; id?: string }
export interface PresetList {
  kinds: { kind: string; label: string }[]; kind: string; active: PresetSelection
  system: SystemPreset; versions: PresetVersion[]; mine: MinePresetSummary[]
}
export interface PresetSave { id: string; preset_id: string; saved: number; name: string; saved_at: string }
export interface PresetSaveSnapshot extends PresetSave { blocks: PresetBlock[] }
export interface PresetCondition { when: PresetWhen; label: string }
export interface PresetPlaceholder { name: string; description: string; preview?: string }
export interface CallPreset {
  kind: string; source: PresetSource; id?: string; name: string; version: number
  blocks: { id: string; title: string; role: PresetRole }[]
}

/** 活动预设的 422 还带检查条目；局部保留它，不改变其他页面的 API 错误格式。 */
export class PresetApiError extends ApiError {
  issues: PresetIssue[]
  constructor(status: number, message: string, issues: PresetIssue[] = []) {
    super(status, message)
    this.issues = issues
  }
}

async function request<T>(path: string, options?: { method?: string; json?: unknown; file?: File }): Promise<T> {
  const body = options?.file ? new FormData() : undefined
  if (options?.file) body!.append('file', options.file)
  const response = await fetch(`/api/presets${path}`, {
    method: options?.method ?? 'GET',
    ...(options?.json !== undefined ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options.json) } : { body }),
  })
  if (response.status === 204) return undefined as T
  const result = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = result?.detail
    let message = `请求失败（${response.status}）`
    if (typeof detail === 'string') message = detail
    else if (detail && typeof detail === 'object' && !Array.isArray(detail) && 'message' in detail) message = String(detail.message)
    else if (Array.isArray(detail) && detail.length) message = `参数不正确：${detail[0].loc?.slice(1).join('.') ?? ''} ${detail[0].msg ?? ''}`.trim()
    throw new PresetApiError(response.status, message, Array.isArray(detail?.issues) ? detail.issues : [])
  }
  return result as T
}

const kind = 'chief_group'
const minePath = (id: string) => `/mine/${encodeURIComponent(id)}`
export const presetApi = {
  list: () => request<PresetList>(`?kind=${kind}`),
  system: (version?: number) => request<SystemPreset>(`/system/${kind}${version ? `?version=${version}` : ''}`),
  create: (input: { source?: PresetSource; id?: string; version?: number; name?: string } = {}) => request<MinePreset>('/mine', { method: 'POST', json: { kind, ...input } }),
  detail: (id: string) => request<MinePreset>(minePath(id)),
  save: (id: string, input: { name: string; blocks: PresetBlock[] }) => request<MinePreset>(minePath(id), { method: 'PUT', json: input }),
  remove: (id: string) => request<{ deleted: boolean }>(minePath(id), { method: 'DELETE' }),
  saves: (id: string) => request<PresetSave[]>(`${minePath(id)}/saves`),
  snapshot: (id: string, saved: number) => request<PresetSaveSnapshot>(`${minePath(id)}/saves/${saved}`),
  restore: (id: string, saved: number) => request<MinePreset>(`${minePath(id)}/saves/${saved}/restore`, { method: 'POST' }),
  activate: (selection: PresetSelection) => request<PresetSelection & { kind: string; issues: PresetIssue[] }>('/active', { method: 'PUT', json: { kind, ...selection } }),
  check: (blocks: PresetBlock[]) => request<{ issues: PresetIssue[] }>('/check', { method: 'POST', json: { kind, blocks } }),
  conditions: () => request<PresetCondition[]>('/conditions'),
  placeholders: (bookId?: string | null) => request<PresetPlaceholder[]>(`/placeholders?${new URLSearchParams({ kind, ...(bookId ? { book_id: bookId } : {}) })}`),
  exportHref: (selection: PresetSelection & { version?: number }) => `/api/presets${selection.source === 'mine' ? `${minePath(selection.id ?? '')}/export` : `/system/${kind}/export${selection.version ? `?version=${selection.version}` : ''}`}`,
  importFile: (file: File) => request<MinePreset>('/import', { method: 'POST', file }),
}
