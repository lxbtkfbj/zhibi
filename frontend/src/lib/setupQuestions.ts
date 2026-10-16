import type { Pending, PieceKey } from '../api/types'

export type AnswerWhen = 'before' | 'later'
export interface SetupQuestionRow { name: string; when: AnswerWhen }
export interface SetupQuestion { key: string; title: string; focus: boolean; rows: SetupQuestionRow[] }
const before = (...names: string[]): SetupQuestionRow[] => names.map(name => ({ name, when: 'before' }))
const later = (...names: string[]): SetupQuestionRow[] => names.map(name => ({ name, when: 'later' }))
const question = (key: string, title: string, focus: boolean, rows: SetupQuestionRow[]): SetupQuestion => ({ key, title, focus, rows })

/** 键与问题逐字对应第二包任务 2 第 2 节；不要将界面简称写进这里。 */
export const SETUP_QUESTIONS: Record<PieceKey, SetupQuestion[]> = {
  concept: [
    question('positioning', '写给谁看？', false, before('题材', '标签', '写给谁', '对标')),
    question('logline', '一句话讲什么？', true, before('一句话故事')),
    question('selling_points', '读者会为哪种场面叫好？', true, before('核心卖点')),
    question('core_loop', '主角每个单元反复做什么？', true, before('核心循环')),
    question('tone', '读起来什么味道？', false, before('基调与文风', '人称')),
    question('length_title', '写多长、叫什么？', false, before('全书篇幅', '粗估卷数', '每章字数', '书名', '备选书名', '舞台阶梯')),
  ],
  protagonist: [
    question('start', '他从哪里起步？', false, before('起点')),
    question('drive', '他为什么要往前走？', true, [...before('开局动机', '长线追求', '情感根源'), ...later('怎么升级')]),
    question('person', '他是个什么样的人？', false, before('性格', '做事风格', '底线', '说话方式')),
    question('finger', '他凭什么走得动？', true, [...before('金手指·现在'), ...later('金手指·以后')]),
    question('flaw_arc', '他的软肋是什么，最后变成谁？', false, before('软肋', '成长的终点')),
    question('cared', '他在乎谁？', false, before('开局在乎的人')),
    question('interlock', '三件套咬得上吗？', true, before('咬合检查')),
  ],
  world: [
    question('surface', '超凡的力量是明是暗？', false, before('世界的表里')),
    question('power', '升级靠什么？', false, [...before('力量规则'), ...later('往上的层级')]),
    question('first_map', '第一张地图上谁说了算？', false, before('地图名', '谁说了算', '天花板', '特有的规矩', '主角从哪起步', '能拿到什么')),
    question('opponents', '主角和谁打？', true, before('开篇的小麻烦', '这一段的大对手')),
    question('people', '他身边有谁？', true, before('这里的人')),
    question('shadows', '远处还有什么？', false, [...before('核心谜团的谜面'), ...later('谜底', '后面的地图', '终极敌人的影子')]),
  ],
  segment: [
    question('opening', '开篇怎么开？', true, before('第 1 章的切入场面', '前 3 章被什么压着', '第一个小爽点', '金手指露头', '第 3 章的钩子')),
    question('goal', '这一段主角想做成什么？', true, before('目标', '为什么离长线追求更近')),
    question('wait', '这一段让读者等什么？', false, before('这一段的长线期待')),
    question('reveal', '这一段揭开什么？', false, before('揭开什么', '信息差')),
    question('end', '这一段走到哪里结束？', true, before('这一段的终点')),
    question('cast', '人物什么时候登场？', false, before('人物锚点')),
    question('volumes', '这一段分几卷？', false, before('卷卡片', '线索')),
    question('direction', '结局大概往哪去？', false, [...before('结局方向', '主角成长弧', '核心矛盾', '主题'), ...later('远景节点')]),
  ],
  first_volume: [
    question('want', '这一卷想做成什么？', true, before('这一卷想做成什么')),
    question('pressure', '卷首主角被什么压着？', false, before('卷首处境')),
    question('climax', '卷末最大的场面是什么、结果如何？', true, before('卷末高潮', '卷末结果')),
    question('rival', '这一卷和谁斗？', false, before('这一卷的对手')),
    question('units', '这一卷拆成哪些剧情单元？', true, before('剧情单元', '核心循环')),
    question('growth', '主角这一卷长了什么？', false, before('主角的成长')),
    question('newcomers', '谁第一次登场？', false, before('新登场的人')),
    question('landing', '开篇落在哪里？', false, before('开篇落地')),
  ],
}

export function questionWhen(question: SetupQuestion): AnswerWhen | null {
  const kinds = new Set(question.rows.map(row => row.when))
  return kinds.size === 1 ? question.rows[0].when : null
}

/** 不把空白字符串或仅有空项的远期列表误当成已经定下的内容。 */
export function hasAnswer(value: unknown): boolean {
  if (typeof value === 'string') return !!value.trim()
  if (Array.isArray(value)) return value.some(hasAnswer)
  if (value && typeof value === 'object') return Object.values(value).some(hasAnswer)
  return value !== null && value !== undefined && value !== false
}

export function showLaterPlaceholder(when: AnswerWhen, value: unknown): boolean {
  return when === 'later' && !hasAnswer(value)
}

export function questionFlags(piece: PieceKey, key: string, pending?: Pending | null): string[] {
  if (pending?.kind !== 'setup_piece' || pending.piece !== piece || !SETUP_QUESTIONS[piece].some(question => question.key === key)) return []
  return (pending.flags?.[key] ?? []).filter(flag => typeof flag === 'string' && !!flag.trim())
}
