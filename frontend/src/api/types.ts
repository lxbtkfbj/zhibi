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
export type SetupPiece = PieceKey | 'settings' | 'outline'
export type PieceStatus = 'todo' | 'drafting' | 'waiting' | 'confirmed' | 'done'
export type SetupTarget = 'concept' | 'protagonist' | 'world' | 'segment' | 'volumes' | 'first_volume'

export interface AuthorChoice {
  topic: string
  chosen: string
  alternatives: string[]
  why: string
}

export interface BookPitch {
  name: string
  text: string
  titles: string[]
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

export interface NextArcPlan {
  title: string
  text: string
  end: { ref: number; title: string; event: string; adopted?: boolean; status?: StoryNode['status'] }
  fill_entries: { name: string; content: string }[]
  new_entries: { name: string; category?: string; one_line?: string; content?: string }[]
  new_characters: { name: string; role_type?: string; one_line?: string }[]
  secret?: string
  ending_change?: string
  finale?: boolean
}

export interface NextSegmentSplit {
  wait?: { description: string } | null
  secrets?: { title: string; truth?: string; knowers?: string[] }[]
  volumes: { index: number; title: string; chapter_count: number; summary?: string; want: string; goal: string; antagonist: string }[]
  anchors?: { node: number; character: string; kind: string; note?: string }[]
  threads?: { name: string; beats: { volume: number; beat: string }[] }[]
}

/**
 * 等作者处理的内容：setup_questions 动笔前的提问；setup_review 开书方案拍板；
 * segment_review 下一段确认；volume_review 某一卷的卷纲拍板；trial_read 前几章试读；chapter_stuck 某章重写两次仍未通过。
 */
export type Pending =
  | { kind?: never; teardown: TeardownProgressData }
  | { kind: 'setup_prefill'; flow: 3 }
  | { kind: 'setup_questions'; flow?: number; questions: InterviewQuestion[] }
  | { kind: 'setup_review'; flow?: number; round: number; title?: string }
  | { kind: 'setup_directions'; flow?: number; reference?: string; directions: BookDirection[]; recommended: number; length: InterviewQuestion & { chapter_words?: number } }
  | { kind: 'setup_pitches'; flow: 3; round: number; benchmark: string; pitches: BookPitch[]; recommended: number; length: InterviewQuestion & { chapter_words?: number } }
  | { kind: 'setup_piece'; flow?: number; flags?: Record<string, string[]>; review?: { question: string; problem: string; suggestion: string }[]; piece: SetupPiece; summary?: string; concept_warnings?: string[]; concept_decisions?: AuthorChoice[]; round: number; warnings?: string[]; decisions?: AuthorChoice[]; suggestions?: SetupSuggestion[]; unlock_requests?: { target: SetupTarget; reason: string }[]; candidates?: { node_id: string; nodes: NodeCandidate[] } | null }
  | { kind: 'segment_review'; flow: 2; number: number; round: number; plan: NextSegmentPlan; split: NextSegmentSplit; warnings: string[]; flags: Record<string, string[]>; decisions: AuthorChoice[] }
  | { kind: 'segment_review'; flow: 3; number: number; round: number; plan: NextArcPlan; split: NextSegmentSplit; warnings: string[]; decisions: AuthorChoice[] }
  | { kind: 'chapters_review'; volume: number; unit_id: string; unit_title: string; first: number; last: number }
  | { kind: 'volume_review'; volume: number; title: string; issues?: string[]; node_update?: NodeUpdateProposal | null; node_conflict?: string }
  | { kind: 'trial_read'; chapters: number }
  | { kind: 'chapter_stuck'; chapter: number; title: string; issues: string[] }

export type DecisionKind = 'setup_review' | 'segment_review' | 'volume_review' | 'chapters_review' | 'trial_read' | 'chapter_stuck'

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
  story?: string
  pitches?: BookPitch[]
  secret_entry_id?: string | null
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
  title?: string
  text?: string
  /** 第二包保存的篇号；第三包只有标题和一段话时由节点顺序计算显示编号。 */
  number?: number
  status?: 'confirmed' | 'auto'
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
  current?: SetupPiece | null
  pieces?: Partial<Record<SetupPiece, PieceStatus>>
}

/** 拆书列表与详情的只读摘要；原文件、分章长列表只在确认页接口里返回。 */
export interface TeardownSummary {
  stage: string
  author: string
  intro: string
  chars: number
  chapters: number
  read: number
  volumes: number
  number_issue_total: number
  excluded_count: number
  open_volume_id: string | null
  imported_at: string | null
  original_volumes?: boolean
  upto?: number | null
  stop_reason?: 'author' | 'upto' | 'model' | 'error' | null
  stop_note?: string | null
  settings?: { upto?: number }
  merits?: { points: { topic: string; text: string }[]; missing?: string[]; upto?: number }
}

export interface TeardownProgressData {
  doing: 'queued' | 'read' | 'units' | 'volumes' | 'closing' | 'settings'
  settings?: { done: number; total: number; now: string }
  reading?: [number, number] | number[] | null
  range?: [number, number] | number[]
  read: number
  target: number
  total: number
  units_upto: number
  parallel: number
  eta_seconds: number | null
  failed: number[]
}

/** 目录只带标记；整本书的原始拆书记录不进目录。 */
export interface TeardownChapterFlags { read: boolean; failed: boolean }

export interface TeardownRead {
  feel?: string
  people?: { name: string; shown: string; also_called?: string[]; was?: string; change?: string }[]
  things?: { kind: string; name: string; note: string; belongs?: string; secret?: '' | '埋下' | '揭开' }[]
  moments?: { who: string; what: string; shows: string }[]
  waits?: { action: string; what: string }[]
  tropes?: string[]
}

export interface TeardownChapterData {
  read?: TeardownRead
  read_version?: number | null
  read_at?: string
  read_failed?: { at?: string; error?: string }
  raw_title?: string
  number?: number | null
  flags?: string[]
}

export interface BookSummary {
  id: string
  title: string
  source: 'new' | 'imported' | 'teardown'
  teardown?: TeardownSummary | null
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
  /** 实际按每章多少字写：本书设置填了用它，没填用新建时记下的（2500） */
  chapter_words?: number
  /** 新工作台：这本书每一类设定有哪几栏 */
  card_layouts?: Record<string, { facts: { key: string; label: string }[]; sections: { key: string; label: string }[] }>
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
  summary?: string
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
  teardown?: TeardownChapterFlags | null
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

export interface Chapter extends Omit<ChapterBrief, 'teardown'> {
  teardown?: TeardownChapterData | null
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
  since_chapter?: number | null
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
  kind: 'plan' | 'speech' | 'artifact' | 'status' | 'decision' | 'error' | 'note'
  content: string
  payload: { type?: string; data?: unknown; thread?: Speaker | 'group'; reply_to?: number[]; quote?: { text: string; where: string }; viewing?: ChatViewing; outcome?: ChatOutcome; steps?: ChatOutcome[]; redo_since?: string; plan?: ChatPlan; status?: 'open' | 'superseded' | 'applying' | 'applied'; results?: ChatOutcome[]
    /** 聊天回答：thinking 还没出字、streaming 在写、stopped 作者叫停了、failed 没答上来（error 是原因）；写完了没有这一项 */
    state?: 'thinking' | 'streaming' | 'stopped' | 'failed'; error?: string
    /** 新书页群聊里打 @ 点的名 */
    ask?: TeamRole
    /** 群聊里接话的人自己查、自己动手的那一句（tools）；ask_only 是只查只答 */
    turn?: 'tools'; ask_only?: boolean
    /** 自己查、自己动手的回答：正在做什么（「在查陈默……」），查了什么、做了什么 */
    tools_mode?: boolean; doing?: string; tools?: ChatToolUse[]
    /** 群聊里属于哪一段对话；dropped 是「从这里重来」收起来的 */
    conv?: string; dropped?: boolean } | null
  created_at: string | null
}

/** 群聊里的一段对话：按作者的第一句话起名；current 是最近聊的那一段 */
export interface ChatConv { id: string; title: string; created_at: string; last_at: string; notes: number; current: boolean; archived?: boolean }

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

export type RoleKey = 'default' | 'chief' | 'lorekeeper' | 'writer' | 'reviewer' | 'teardown' | 'router'
export type RoleAssignments = Record<RoleKey, string | null>

export interface Health {
  status: 'ok' | 'error'
  components: Record<string, { ok: boolean; detail: string }>
}

/** 作者发话时正在看的那一页（新书页上带）：群聊里说「帮我写这一篇」「把这一条补齐」就按它来 */
export interface ChatViewing {
  target_type: 'book' | 'segment' | 'volume' | 'unit' | 'chapter' | 'character' | 'entry' | 'concept'
  target_id: string
  label: string
}

export interface ChatOutcome {
  kind: 'requirement' | 'to_job' | 'edit' | 'fill' | 'outline' | 'working' | 'not_found' | 'later' | 'chat' | 'pending' | 'too_late' | 'failed' | 'plan_apply' | 'plan_made' | 'plan_pending' | 'created' | 'suggestion' | 'feedback' | 'saved' | 'agent' | 'deleted'
  reason?: string
  /** 再改一版要照着重做的那个判断：有它才能「再改一版」（删掉的没有） */
  redo?: Record<string, unknown>
  /** plan_made：接话的人要动的多（count 处），或者要删东西，整理成了方案卡 */
  count?: number
  /** chat：明显是在问，没分流直接答的 */
  shortcut?: boolean
  deleting?: boolean
  /** 改完当场的前后对照：每一栏「原来」「改成」（太长截到 2000 字） */
  diff?: ChangeDiff[]
  /** 这一处改了哪几行、改之前改之后的 hash：「换回原来的」「再改一版」用 */
  change?: { table: string; id: string; before: string | null; after: string | null }[]
  /** working：从什么时候开始做的（再改一版时用；没有就按消息的时间算） */
  since?: string
  /** failed：是「再改一版」没做成（这一处已经换回改之前了） */
  redo_failed?: boolean
  /** saved：聊天里说「存个档」存下的那一档 */
  save_id?: number
  title?: string
  /** working：编辑部判断完、正在做的那件事 */
  text?: string
  /** fill：补上的几栏 */
  filled?: string[]
  /** created：群聊里让编辑部新建的几条，撤销就把它们删掉 */
  items?: { target_type: 'character' | 'entry'; target_id: string; name: string }[]
  /** outline：编辑部写大纲上的那一段之前的样子，撤销就存回去 */
  before?: Record<string, unknown>
  /** outline：那一篇是这次新加的，撤销就把整篇删掉 */
  created_id?: string
  plan_id?: number
  label?: string
  undone?: boolean
  snapshot?: Record<string, unknown>
  requirement_id?: string
  target_type?: string
  target_id?: string
  target_label?: string
  /** not_found：没认出来的那个名字 */
  target_name?: string
  mode?: string
  revert_version_id?: string
  candidate_id?: string
  suggestion_id?: string
}


export interface ChangeDiff { label: string; before: string; after: string; truncated?: boolean }

/** 整本书的一档存档 */
export interface BookSave {
  id: number
  created_at: string
  kind: 'auto' | 'manual' | 'restore'
  actor: 'author' | 'chief' | 'lorekeeper' | 'writer' | 'reviewer' | 'system'
  actor_name: string
  title: string
  summary: { items?: { table: string; id: string; op: 'add' | 'del' | 'mod'; group: string; name: string; fields: string[] }[]; more?: number; finished?: { index: number; title: string }[]; first?: boolean }
  count: number
  chapters_final: number
  restored_from: number | null
}

/** 这一档和现在比：add 是现在有、那时没有（回去会删掉）；del 是那时有、现在没有（回去会加回来） */
export interface SaveCompare {
  save: BookSave
  now_final: number
  same: boolean
  groups: { name: string; items: { table: string; id: string; op: 'add' | 'del' | 'mod'; name: string; parts: { label: string; then: string; now: string; then_words: number; now_words: number; long: boolean }[] }[] }[]
}

/** 回答下面「查了：……」点开看的：查到的资料、做了什么 */
export interface ChatToolUse { kind: 'query' | 'act'; label: string; text: string }

export interface PlanItem {
  where: '定调' | '设定库' | '大纲' | '写作要求' | '删除'
  target: string
  part: string
  category: string
  change: string
  scope: '一直有效' | '只管下一章' | '只管这一卷' | '只管下一卷'
  /** 编辑部在聊天里自己动手时出的卡：原来那一条清单；linked 是删了会连带什么 */
  tool?: { kind?: string; shown?: string; linked?: string } & Record<string, unknown>
}
export interface ChatPlan { title: string; summary: string; items: PlanItem[]; open_questions: string[] }
