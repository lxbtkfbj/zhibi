export type JobStatus = 'queued' | 'running' | 'waiting_author' | 'succeeded' | 'failed' | 'cancelled'
export type BookStatus = 'setting_up' | 'awaiting_approval' | 'ready' | 'writing'
export type Speaker = 'chief' | 'lorekeeper' | 'writer' | 'reviewer' | 'author' | 'system'

export interface Job {
  id: string
  book_id: string
  kind: string
  status: JobStatus
  pending: { kind: string; round: number; title?: string } | null
  error: string
  created_at: string
  updated_at: string
  finished_at: string | null
}

export interface Concept {
  title?: string
  alt_titles?: string[]
  genre?: string
  tags?: string[]
  logline?: string
  selling_points?: string[]
  protagonist_hook?: string
  tone?: string
  target_volumes?: number
  chapter_words?: number
}

export interface BookSummary {
  id: string
  title: string
  source: 'new' | 'imported'
  genre: string
  status: BookStatus
  idea: string
  logline: string
  created_at: string
  updated_at: string
}

export interface BookDetail extends BookSummary {
  style_reference: string
  concept: Concept
  active_job: Job | null
}

export interface PlotUnit {
  id: string
  index: number
  title: string
  chapter_count: number
  goal: string
  conflict: string
  climax: string
  outcome: string
  key_events: string[]
}

export interface Volume {
  id: string
  index: number
  title: string
  summary: string
  goal: string
  status: 'planned' | 'detailed' | 'approved'
  units: PlotUnit[]
}

export interface Outline {
  concept: Concept
  volumes: Volume[]
}

export interface Character {
  id: string
  name: string
  aliases: string[]
  role_type: string
  gender: string
  age: string
  appearance: string
  personality: string
  background: string
  abilities: string
  goal: string
  location: string
  condition: string
  secrets: string[]
  notes: string
  is_alive: boolean
  first_appearance_chapter: number | null
}

export interface WorldEntry {
  id: string
  category: string
  name: string
  content: string
}

export interface Relationship {
  id: string
  source_id: string
  target_id: string
  kind: string
  description: string
}

export type ForeshadowingStatus = 'planned' | 'planted' | 'resolved' | 'abandoned'

export interface Foreshadowing {
  id: string
  description: string
  plant_plan: string
  payoff_plan: string
  status: ForeshadowingStatus
  planted_chapter: number | null
  resolved_chapter: number | null
}

export interface Bible {
  characters: Character[]
  relationships: Relationship[]
  world_entries: WorldEntry[]
  foreshadowings: Foreshadowing[]
}

export interface MeetingMessage {
  id: number
  book_id: string
  job_id: string | null
  speaker: Speaker
  speaker_name: string
  kind: 'speech' | 'artifact' | 'status' | 'decision' | 'error'
  content: string
  payload: { type: string; data: unknown } | null
  created_at: string | null
}

export interface Usage {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  by_role: Record<string, { calls: number; prompt_tokens: number; completion_tokens: number }>
}

export type StructuredMethod = 'function_calling' | 'json_mode' | 'json_schema'

export interface LlmProfile {
  id: string
  name: string
  provider: 'openai_compatible' | 'demo'
  base_url: string
  model: string
  temperature: number
  max_tokens: number | null
  structured_method: StructuredMethod
  timeout_s: number
  reasoning_effort: string | null
  has_key: boolean
}

export interface LlmProfileInput {
  name: string
  provider: 'openai_compatible' | 'demo'
  base_url: string
  api_key: string
  model: string
  temperature: number
  max_tokens: number | null
  structured_method: StructuredMethod
  timeout_s: number
  reasoning_effort: string
}

export type RoleKey = 'default' | 'chief' | 'lorekeeper' | 'writer' | 'reviewer'
export type RoleAssignments = Record<RoleKey, string | null>

export interface Health {
  status: 'ok' | 'error'
  components: Record<string, { ok: boolean; detail: string }>
}
