import { del, get, put } from './client'

export interface PromptVariable { name: string; label: string }
export interface PromptInfo {
  name: string; title: string; group: string; role: string; when: string
  customized: boolean; updated_at: string | null
  default_changed: boolean; new_variables: PromptVariable[]
  last_call: { id: number; created_at: string } | null
  variables: PromptVariable[]
}
export interface PromptDetail extends PromptInfo { content: string; default_content: string }
export interface LlmCall {
  id: number; book_id: string | null; book_title: string | null
  role: string; purpose: string; model: string; profile_name: string | null
  prompt_tokens: number | null; completion_tokens: number | null
  latency_ms: number | null; ok: boolean; error: string | null; created_at: string
}
export interface LlmCallDetail extends LlmCall {
  request: { system: string; user: string; schema_name: string | null; schema: unknown; method: string } | null
  response: string | null
}
export const promptApi = {
  list: () => get<PromptInfo[]>('/prompts'),
  detail: (name: string) => get<PromptDetail>(`/prompts/${encodeURIComponent(name)}`),
  save: (name: string, content: string) => put<PromptDetail>(`/prompts/${encodeURIComponent(name)}`, { content }),
  reset: (name: string) => del(`/prompts/${encodeURIComponent(name)}`),
  calls: (book: string, role: string, before?: number) => {
    const query = new URLSearchParams({ limit: '50' })
    if (book) query.set('book_id', book)
    if (role) query.set('role', role)
    if (before) query.set('before', String(before))
    return get<{ items: LlmCall[]; next_before: number | null }>(`/llm-calls?${query}`)
  },
  call: (id: number) => get<LlmCallDetail>(`/llm-calls/${id}`),
}
