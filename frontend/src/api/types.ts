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

export type PieceKey = 'concept' | 'protagonist' | 'world' | 'segment' | 'first_volume'
export type SetupPiece = PieceKey
export type PieceStatus = 'todo' | 'drafting' | 'waiting' | 'confirmed' | 'done'
export type SetupTarget = 'concept' | 'protagonist' | 'world' | 'segment' | 'volumes' | 'first_volume'

export interface AuthorChoice {
  topic: string
  chosen: string
  alternatives: string[]
  why: string
}

export interface BookDirection {
  name: string
  titles?: string[]
  logline: string
  protagonist: string
  drive?: string
  golden_finger: string
  core_loop?: string
  opening: string
  selling_points: string[]
  stage_ladder: string
  tone: string
  reader: string
  difference: string
  editor_note: string
  techniques: string[]
}

export interface SetupSuggestion {
  target: SetupTarget
  problem: string
  suggestion: string
  severity?: 'high' | 'medium' | 'low'
}

export type NodeCandidate = Pick<StoryNode, 'title' | 'event' | 'prerequisite' | 'consequence' | 'volume' | 'editor_note' | 'techniques'>

export interface NodeUpdateProposal {
  node_id: string
  index: number
  current: Pick<StoryNode, 'title' | 'event' | 'prerequisite' | 'consequence'>
  proposed: Pick<StoryNode, 'title' | 'event' | 'prerequisite' | 'consequence'>
  reason: string
}

/** 下一段尚未落库的规划快照；确认页以后沿用这些字段，不拿已保存节点冒充待确认内容。 */
export interface NextSegmentPlan {
  carried: string
  pursuit: string
  finger_next: string
  answers: string
  map: string
  new_map: NonNullable<World['maps']>[number] | null
  power: string
  trouble: string
  opponent: string
  new_characters: { name: string; role_type: string; goal: string; want: string; [key: string]: unknown }[]
  relationships: Record<string, unknown>[]
  goal: string
  goal_link: string
  wait: { description: string; plant_plan?: string; payoff_plan?: string; plant_volume?: number; payoff_volume?: number; [key: string]: unknown }
  reveal: string
  secrets: { title: string; truth: string; knowers: string[]; [key: string]: unknown }[]
  end: NodeCandidate & { adopted: boolean; status?: StoryNode['status']; ref?: number }
  ending: string
  finale: boolean
  decisions?: AuthorChoice[]
  nodes_view?: { index: number; title: string }[]
}

export interface NextSegmentSplit {
  volumes: { index: number; title: string; chapter_count: number; want: string; goal: string; antagonist: string }[]
  anchors?: { node: number; character: string; kind: string; note?: string }[]
  threads?: { name: string; beats: { volume: number; beat: string }[] }[]
}

/**
 * 等作者处理的内容：setup_questions 动笔前的提问；setup_review 开书方案拍板；
 * segment_review 下一段确认；volume_review 某一卷的卷纲拍板；trial_read 前几章试读；chapter_stuck 某章重写两次仍未通过。
 */
export type Pending =
  | { kind: 'setup_questions'; flow?: number; questions: InterviewQuestion[] }
  | { kind: 'setup_review'; flow?: number; round: number; title?: string }
  | { kind: 'setup_directions'; flow?: number; reference?: string; directions: BookDirection[]; recommended: number; length: InterviewQuestion & { chapter_words?: number } }
  | { kind: 'setup_piece'; flow?: number; flags?: Record<string, string[]>; review?: { question: string; problem: string; suggestion: string }[]; piece: PieceKey; round: number; warnings?: string[]; decisions?: AuthorChoice[]; suggestions?: SetupSuggestion[]; unlock_requests?: { target: SetupTarget; reason: string }[]; candidates?: { node_id: string; nodes: NodeCandidate[] } | null }
  | { kind: 'segment_review'; flow: 2; number: number; round: number; plan: NextSegmentPlan; split: NextSegmentSplit; warnings: string[]; flags: Record<string, string[]>; decisions: AuthorChoice[] }
  | { kind: 'volume_review'; volume: number; title: string; issues?: string[]; node_update?: NodeUpdateProposal | null; node_conflict?: string }
  | { kind: 'trial_read'; chapters: number }
  | { kind: 'chapter_stuck'; chapter: number; title: string; issues: string[] }

export type DecisionKind = 'setup_review' | 'segment_review' | 'volume_review' | 'trial_read' | 'chapter_stuck'

export interface Job {
  id: string
  book_id: string
  kind: string
  /** 开书流程版本；非开书任务为空。 */
  setup_flow: number | null
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
  core_loop?: string
  benchmark?: string
  tone?: string
  /** 全书计划总字数，单位万字 */
  target_length?: number
  target_volumes?: number
  chapter_words?: number
  stage_ladder?: string
  target_reader?: string
  decisions?: AuthorChoice[]
}

/** 主角卡；旧书为空，逐步填写时允许只提供部分回答。 */
export interface Protagonist {
  name?: string
  start?: string
  trigger?: string
  pursuit?: string
  root?: string
  escalation?: string
  personality?: string
  style?: string
  bottom_line?: string
  voice?: string
  finger?: string
  finger_later?: string
  flaw?: string
  arc_end?: string
  cared?: { name?: string; relation?: string; why?: string }[]
  interlock?: string
}

/** 世界与地图；小麻烦和大对手只属于第一段。 */
export interface World {
  surface?: string
  power?: string
  maps?: { name?: string; powers?: string; ceiling?: string; rules?: string; start?: string; gains?: string }[]
  trouble?: string
  opponent?: string
  far_maps?: { name?: string; line?: string }[]
  shadow?: string
  mystery?: string
  mystery_answer?: string
}

/** 一段的规划，保存在这一段的终点节点上。 */
export interface SegmentPlan {
  number: number
  status: 'confirmed' | 'auto'
  planned_at: number
  map: string
  trouble: string
  opponent: string
  goal: string
  goal_link: string
  wait: string
  reveal: string
  opening: { scene?: string; pressure?: string; first_win?: string; finger?: string; hook?: string } | null
  carried: string
  pursuit: string
  finger_next: string
  answers: string
  finale: boolean
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
  segment: SegmentPlan | null
  volume: number | null
  status: 'pinned' | 'pencil' | 'empty'
  origin: 'ai' | 'author'
  updated_by_volume?: number | null
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
  current?: PieceKey | null
  pieces?: Partial<Record<PieceKey, PieceStatus>>
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
  protagonist: Protagonist
  world: World
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
  loop: string
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
  editor_note?: string
  techniques?: string[]
  reveals?: { ref: string; to: string; how: string }[]
  plan_issues?: string[]
}

export interface Volume {
  id: string
  index: number
  title: string
  want: string
  pressure: string
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
  target_node_id: string | null
  reaches_node: boolean
  editor_note: string
  techniques: string[]
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
  emotion?: number
  mood?: '爽' | '燃' | '甜' | '虐' | '悬' | '笑' | '暖' | '惊'
  reveals?: { ref: string; to: string; how: string }[]
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
  want: string
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
