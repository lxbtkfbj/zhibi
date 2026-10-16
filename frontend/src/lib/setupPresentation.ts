import type { BookDetail, Concept, Job, StoryNode, Volume } from '../api/types'
import { totalChapters } from './status.ts'

/** 分段只规划近处卷卡，不能用这几卷的章数冒充全书篇幅。旧书沿用原统计。 */
export function setupOverviewStats(concept: Concept, volumes: Pick<Volume, 'chapter_count'>[], nodes: Pick<StoryNode, 'segment'>[]) {
  const segmented = nodes.some(node => !!node.segment && Object.keys(node.segment).length > 0)
  return {
    segmented,
    volumeLabel: `${segmented ? '已规划' : '全书'} ${volumes.length} 卷`,
    chapters: segmented ? totalChapters(concept, []) : totalChapters(concept, volumes),
  }
}

export type SetupField = { label: string; value: string }
export const LATER_ANSWER = '先空着，写到这里时主编会来问你'
export const LEGACY_SETUP_NOTICE = '这个开书任务是按旧流程开的，开书流程已经更新。请点「按新流程重开」：保留你的点子、作者要求、已选的方向和已确认的定调，其余按新步骤重做。'

const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const text = (value: unknown) => typeof value === 'string' ? value : ''
const rows = (value: unknown) => Array.isArray(value) ? value.map(record) : []
const field = (source: Record<string, unknown>, label: string, key: string, fallback = '') => ({ label, value: text(source[key]) || fallback })

/** 只读简版；空字段不补造内容，旧书没有主角卡时由页面单独提示。 */
export function protagonistFields(value: unknown): SetupField[] {
  const card = record(value)
  return [
    field(card, '姓名', 'name'), field(card, '起点', 'start'),
    field(card, '开局动机', 'trigger'), field(card, '长线追求', 'pursuit'), field(card, '情感根源', 'root'),
    field(card, '怎么升级', 'escalation', LATER_ANSWER),
    field(card, '性格', 'personality'), field(card, '做事风格', 'style'), field(card, '底线', 'bottom_line'), field(card, '说话方式', 'voice'),
    field(card, '金手指·现在', 'finger'), field(card, '金手指·以后', 'finger_later', LATER_ANSWER),
    field(card, '软肋', 'flaw'), field(card, '成长的终点', 'arc_end'),
    { label: '在乎的人', value: rows(card.cared).map(person => `${text(person.name)}（${text(person.relation)}：${text(person.why)}）`).join('；') },
    field(card, '三件套怎么咬合', 'interlock'),
  ]
}

/** 标题与后端 format_world 一致；兼容会议里的原始 first_map 及入库后的 maps。 */
export function worldFields(value: unknown): SetupField[] {
  const world = record(value)
  const maps = rows(world.maps ?? (world.first_map ? [world.first_map] : []))
  const result = [field(world, '世界的表里', 'surface'), field(world, '力量规则', 'power')]
  for (const map of maps) {
    result.push({ label: `地图「${text(map.name)}」`, value: [
      field(map, '谁说了算', 'powers'), field(map, '天花板', 'ceiling'), field(map, '特有的规矩', 'rules'),
      field(map, '主角从这里起步', 'start'), field(map, '能拿到', 'gains'),
    ].filter(item => item.value).map(item => `${item.label}：${item.value}`).join('\n') })
  }
  return [...result,
    field(world, '第一段·开篇的小麻烦', 'trouble'), field(world, '第一段·大对手', 'opponent'),
    { label: '后面的地图', value: rows(world.far_maps).map(map => text(map.name) + (text(map.line) ? `（${text(map.line)}）` : '')).filter(Boolean).join(' → ') || '写到再定' },
    field(world, '终极敌人的影子', 'shadow'),
    { label: '核心谜团', value: `${text(world.mystery) ? `谜面：${text(world.mystery)}\n` : ''}谜底：${text(world.mystery_answer) || '写到再定'}` },
  ]
}

/** 第一段快照可能是模型原始产出，也可能是节点里已整理的段规划。 */
export function segmentFields(value: unknown): SetupField[] {
  const draft = record(value)
  const segment = rows(draft.nodes).map(node => record(node.segment)).find(item => Object.keys(item).length) ?? draft
  const opening = record(segment.opening)
  return [
    field(opening, '第一章场面', 'scene'), field(opening, '前 3 章的压力', 'pressure'), field(opening, '第一个小爽点', 'first_win'),
    field(opening, '金手指露头', 'finger'), field(opening, '第 3 章钩子', 'hook'),
    field(segment, '这一段的目标', 'goal'), field(segment, '和长线追求的联系', 'goal_link'),
    { label: '让读者等什么', value: text(segment.wait) || text(record(segment.wait).description) },
    field(segment, '这一段揭开什么', 'reveal'), field(draft, '核心矛盾', 'core_conflict'),
    field(draft, '主题', 'theme'), field(draft, '主角成长弧线', 'protagonist_arc'),
  ].filter(item => item.value)
}

export function needsSetupRestart(book: Pick<BookDetail, 'status'>, job: Job | null): boolean {
  return (book.status === 'setting_up' || book.status === 'awaiting_approval') && job?.kind === 'book_setup' &&
    job.setup_flow === 1 && ['waiting_author', 'failed', 'cancelled'].includes(job.status)
}
