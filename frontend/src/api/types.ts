export type JobStatus = 'queued' | 'running' | 'waiting_author' | 'succeeded' | 'failed' | 'cancelled'
export type BookStatus = 'setting_up' | 'awaiting_approval' | 'ready' | 'writing' | 'completed'
export type Speaker = 'chief' | 'lorekeeper' | 'writer' | 'reviewer' | 'author' | 'system'
export type TeamRole = Exclude<Speaker, 'author' | 'system'>
export type Conversation = 'group' | TeamRole

export interface InterviewQuestion {
  question: string
  options: string[]
  recommended: number
}

export type SetupPiece = 'concept' | 'nodes' | 'cast' | 'fill' | 'first_volume'

/**
 * 等作者处理的内容：setup_questions 动笔前的提问；setup_review 开书方案拍板；
 * volume_review 某一卷的卷纲拍板；trial_read 前几章试读；chapter_stuck 某章重写两次仍未通过。
 */
export type Pending =
  | { kind: 'setup_questions'; questions: InterviewQuestion[] }
  | { kind: 'setup_review'; round: number; title?: string }
  | { kind: 'setup_directions'; directions: { name: string; logline: string }[]; recommended: number; length: InterviewQuestion }
  | { kind: 'setup_piece'; piece: SetupPiece; round: number; warnings?: string[]; decisions?: { topic: string; chosen: string; alternatives: string[]; why: string }[]; suggestions?: unknown[]; unlock_requests?: unknown[]; candidates?: unknown }
  | { kind: 'volume_review'; volume: number; title: string; issues?: string[] }
  | { kind: 'trial_read'; chapters: number }
  | { kind: 'chapter_stuck'; chapter: number; title: string; issues: string[] }

export type DecisionKind = 'setup_review' | 'volume_review' | 'trial_read' | 'chapter_stuck'

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

/** 主线元信息；关键节点以节点接口为唯一事实来源。 */
export interface Spine {
  core_conflict?: string
  theme?: string
  protagonist_arc?: string
}

export interface NodeAnchor {
  id: string
  node_id: string
  character_id: string
  character_name: string
  kind: '登场' | '确认关系' | '翻脸' | '高光' | '退场' | '其他'
  note: string
}

export interface StoryNode {
  id: string
  index: number
  kind: 'opening' | 'milestone' | 'ending'
  title: string
  event: string
  prerequisite: string
  consequence: string
  volume: number | null
  status: 'pinned' | 'pencil' | 'empty'
  origin: 'ai' | 'author'
  editor_note: string
  techniques: string[]
  anchors: NodeAnchor[]
}

export interface Secret {
  id: string
  seq: number
  code: string
  title: string
  truth: string
  knowers: { name: string; since_chapter: number | null; how: string }[]
  reader_knows: '知道' | '不知道' | '部分' | null
  reveal_plan: string
  node_id: string | null
  status: 'hidden' | 'public'
  created_chapter: number | null
}

export interface SetupProgress {
  mode?: 'puzzle' | 'oneshot'
  current?: 'concept' | 'nodes' | 'cast' | 'fill' | 'first_volume' | null
  pieces?: Partial<Record<'concept' | 'nodes' | 'cast' | 'fill' | 'first_volume', string>>
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
  setup_progress: SetupProgress
  /** 作者的要求：动笔前的回答、插话、拍板与试读意见 */
  requirements: string[]
  trial_read_done: boolean
  active_job: Job | null
  chapters_final: number
  words_final: number
}

/** 线索在某一段（卷或单元）里走到哪一步。 */
export interface ThreadStep {
  thread: string
  beat: string
}

/** 对伏笔台账的动作，ref 如 F3。 */
export interface ForeshadowStep {
  ref: string
  action: string
  detail: string
}

export interface StoryThread {
  id: string
  index: number
  name: string
  kind: string
  summary: string
  characters: string[]
  beats: { volume: number; beat: string }[]
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
  thread_beats: ThreadStep[]
  foreshadow_actions: ForeshadowStep[]
  /** 本单元用到的套路（核心套路在前）与高潮的破局手法 */
  tropes: string[]
  resolution: string
  /** planned：还没出章纲；outlined：章纲已出；done：写完 */
  status: 'planned' | 'outlined' | 'done'
  /** 单元写完后设定师写的单元回顾 */
  recap: string
}

export interface Volume {
  id: string
  index: number
  title: string
  stage: string
  summary: string
  goal: string
  climax: string
  antagonist: string
  power_range: string
  thread_beats: ThreadStep[]
  new_characters: string[]
  /** 本卷预计章数（拆剧情单元之前的规划） */
  chapter_count: number
  /** planned：只有总纲卡片；detailed：卷纲待拍板；approved：已批准；done：已写完 */
  status: 'planned' | 'detailed' | 'approved' | 'done'
  /** 一卷写完后设定师写的卷回顾 */
  recap: string
  units: PlotUnit[]
}

export interface ChapterOutline {
  title?: string
  goal?: string
  scenes?: string[]
  conflict?: string
  cool_point?: string
  hook?: string
  characters?: string[]
  foreshadow_actions?: ForeshadowStep[]
}

export type ChapterStatus = 'planned' | 'drafting' | 'final'

export interface ChapterBrief {
  id: string
  index: number
  title: string
  volume_id: string | null
  unit_id: string | null
  status: ChapterStatus
  word_count: number
  summary: string
  attempts: number
  outline: ChapterOutline | null
}

export interface ReviewIssue {
  problem: string
  suggestion: string
  severity: 'high' | 'medium' | 'low'
}

/** 写之前设定师为这一章备的资料。 */
export interface ChapterMaterials {
  characters?: string[]
  world?: string[]
  chapters?: number[]
  notes?: string[]
}

export interface Chapter extends ChapterBrief {
  content: string
  materials: ChapterMaterials
  review: {
    review?: { verdict: 'pass' | 'revise'; highlights: string[]; issues: ReviewIssue[]; remark?: string }
    consistency?: { issues: ReviewIssue[]; remark?: string }
  }
  updated_at: string
}

export type WriteUntil = 'count' | 'volume' | 'book'

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
  /** 伏笔与期待共用书内序号；界面用 code 显示 F / E 前缀。 */
  seq: number
  kind: '伏笔' | '期待'
  node_id: string | null
  code: string
  description: string
  /** 短：一个单元内收；中：一卷内收；长：跨卷 */
  span: '短' | '中' | '长'
  plant_plan: string
  payoff_plan: string
  plant_volume: number | null
  payoff_volume: number | null
  status: ForeshadowingStatus
  planted_chapter: number | null
  hint_chapters: number[]
  resolved_chapter: number | null
}

export interface Bible {
  characters: Character[]
  relationships: Relationship[]
  world_entries: WorldEntry[]
  foreshadowings: Foreshadowing[]
  secrets: Secret[]
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
  payload: { type?: string; data?: unknown; thread?: Speaker } | null
  created_at: string | null
}

/** 写手正在写的正文（实时推送，不进数据库）。text 是这一章到目前为止的全文。 */
export interface LiveDraft {
  job_id: string
  chapter: number
  title: string
  /** write 写正文；extend 字数不够接着写；ending 改写结尾 */
  mode: 'write' | 'extend' | 'ending'
  text: string
  done: boolean
}

export interface Usage {
  calls: number
  prompt_tokens: number | null
  completion_tokens: number | null
  by_role: Record<string, { calls: number; prompt_tokens: number | null; completion_tokens: number | null }>
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
  structured_method_auto: boolean
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
