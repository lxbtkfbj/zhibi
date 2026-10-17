import type { ChapterBrief, Foreshadowing, ForeshadowStep, WriteUntil } from '../api/types'

export const EMOTION_LABELS: Record<number, string> = {
  [-2]: '憋屈压抑', [-1]: '偏压', 0: '平稳或悬着', 1: '偏扬', 2: '爆发爽快',
}

export function emotionText(emotion: unknown): string | null {
  if (typeof emotion !== 'number' || !Number.isInteger(emotion) || !(emotion in EMOTION_LABELS)) return null
  return `${emotion > 0 ? '+' : ''}${emotion} ${EMOTION_LABELS[emotion]}`
}

/** 保留首尾点的半径；单章置中，旧章纲缺值不冒充平稳。 */
export function emotionPoint(emotion: unknown, index: number, count: number, width = 320, height = 32) {
  if (!emotionText(emotion) || count < 1 || index < 0 || index >= count || width <= 0 || height <= 0) return null
  const padding = Math.min(4, width / 2, height / 2)
  return {
    x: count === 1 ? width / 2 : padding + index * (width - padding * 2) / (count - 1),
    y: padding + (2 - (emotion as number)) * (height - padding * 2) / 4,
  }
}

/** 连续四章同主情绪时，整段（不只第四章）都提示；缺值和缺章打断连续。 */
export function repeatedMoodChapters(chapters: Pick<ChapterBrief, 'id' | 'index' | 'outline'>[]): Set<string> {
  const result = new Set<string>()
  const sorted = [...chapters].sort((a, b) => a.index - b.index)
  let start = 0
  for (let i = 0; i <= sorted.length; i += 1) {
    if (i > 0 && i < sorted.length && sorted[i].outline?.mood && sorted[i].outline?.mood === sorted[i - 1].outline?.mood && sorted[i].index === sorted[i - 1].index + 1) continue
    if (i - start >= 4 && sorted[start]?.outline?.mood) sorted.slice(start, i).forEach(chapter => result.add(chapter.id))
    start = i
  }
  return result
}

/** 台账是类型与编号的事实来源；历史消息没有台账时仍可按 E 编号识别期待。 */
export function foreshadowAction(action: ForeshadowStep, ledger: Foreshadowing[] = []) {
  const number = /^[FE](\d+)$/i.exec(action.ref)?.[1]
  const item = ledger.find(entry => entry.code === action.ref) ?? (number ? ledger.find(entry => entry.seq === Number(number)) : undefined)
  const expected = item?.kind === '期待' || (!item && /^E\d+$/i.test(action.ref))
  const label = expected ? ({ 埋下: '立下', 回收: '兑现' }[action.action] ?? action.action) : action.action
  const code = item?.code || action.ref
  return { label, code, hint: [item?.description, action.detail].filter(Boolean).join('；') || `${label} ${code}` }
}

/** 前后共用相同的首尾，只有变动文字加下划线，包含新增与删除。 */
export function changedText(before: string, after: string) {
  const oldText = Array.from(before)
  const newText = Array.from(after)
  let start = 0
  while (start < oldText.length && start < newText.length && oldText[start] === newText[start]) start += 1
  let suffix = 0
  while (suffix < oldText.length - start && suffix < newText.length - start && oldText[oldText.length - 1 - suffix] === newText[newText.length - 1 - suffix]) suffix += 1
  const split = (text: string[]) => ({ prefix: text.slice(0, start).join(''), changed: text.slice(start, text.length - suffix).join(''), suffix: suffix ? text.slice(-suffix).join('') : '' })
  return { before: split(oldText), after: split(newText), differs: before !== after }
}

/** 这一轮写多少：书稿底部操作条和概览共用。 */
export const WRITE_OPTIONS: { key: string; label: string; until: WriteUntil; count: number; hint: string }[] = [
  { key: '1', label: '写 1 章', until: 'count', count: 1, hint: '先写一章看看' },
  { key: '3', label: '写 3 章', until: 'count', count: 3, hint: '新书写完前 3 章会请你试读' },
  { key: '10', label: '写 10 章', until: 'count', count: 10, hint: '中途可以随时插话或停下' },
  { key: 'volume', label: '写完这一卷', until: 'volume', count: 1, hint: '一卷写完就停，等你看看' },
  { key: 'book', label: '一直写到完本', until: 'book', count: 1, hint: '每卷开写前仍会请你拍板卷纲' },
]
