export type JobStatus = 'queued' | 'running' | 'waiting_author' | 'succeeded' | 'failed' | 'cancelled'
export type BookStatus = 'setting_up' | 'awaiting_approval' | 'ready' | 'writing'
export type Speaker = 'chief' | 'lorekeeper' | 'writer' | 'reviewer' | 'author' | 'system'

export interface InterviewQuestion {
  question: string
  options: string[]
  recommended: number
}

/** 等作者处理的内容：setup_questions 动笔前的提问；setup_review 开书方案拍板。 */
export type Pending =
  | { kind: 'setup_questions'; questions: InterviewQuestion[] }
  | { kind: 'setup_review'; round: number; title?: string }

export interface Job {
  id: string
  book_id: string
  kind: string
  status: JobStatus
  pending: Pending | null
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
  /** 全书计划总字数，单位万字 */
  target_length?: number
  target_volumes?: number
  chapter_words?: number
}

export interface Milestone {
  index: number
  title: string
  volume: number
  event: string
  change: string
}

/** 主线骨架：开篇、结局与中间的关键转折。 */
export interface Spine {
  core_conflict?: string
  theme?: string
  protagonist_arc?: string
  opening?: string
  ending?: string
  milestones?: Milestone[]
}

export interface BookSummary {
  id: string
  title: string
  source: 'new' | 'imported'
  genre: string
  status: BookStatus
  idea: string
  logline: string
  job_status: JobStatus | null
  created_at: string
  updated_at: string
}

export interface BookDetail extends BookSummary {
  style_reference: string
  concept: Concept
  spine: Spine
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
  /** 本卷预计章数（拆剧情单元之前的规划） */
  chapter_count: number
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
  /** note：作者在编辑部工作时插的话 */
  kind: 'speech' | 'artifact' | 'status' | 'decision' | 'error' | 'note'
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
