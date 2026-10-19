/** 本书设置和全局「新书默认」共用的说法：选项、白话说明、每章字数怎么算对。 */

import type { WritingSettings } from '../api/settings'

export const PERSON_OPTIONS = [
  { value: 'first', label: '第一人称' },
  { value: 'second', label: '第二人称' },
  { value: 'third', label: '第三人称' },
] as const

export const INTIMACY_OPTIONS = [
  { value: 'heart', label: '只写心动' },
  { value: 'fade', label: '点到为止' },
  { value: 'custom', label: '自己写' },
] as const

export const INTIMACY_HINTS: Record<WritingSettings['intimacy'], string> = {
  heart: '只写心动、暧昧和拉扯，不写亲吻以上',
  fade: '可以写亲吻拥抱，再进一步就一笔带过',
  custom: '写下亲密戏写到哪一步，编辑部照这句来',
}

export const EFFORT_OPTIONS = [
  { value: 'quick', label: '省时' },
  { value: 'balanced', label: '均衡' },
  { value: 'premium', label: '精品' },
] as const

/** 和后台 book_settings.PRESETS 一样：点了哪档，四个参数当场换上，说明跟着变。 */
export const EFFORT_PRESETS = {
  quick: { max_rewrites: 1, pitches: 1, volume_audit: false, review_strictness: 'lenient' },
  balanced: { max_rewrites: 2, pitches: 2, volume_audit: true, review_strictness: 'standard' },
  premium: { max_rewrites: 3, pitches: 3, volume_audit: true, review_strictness: 'strict' },
} as const satisfies Record<string, Pick<WritingSettings, 'max_rewrites' | 'pitches' | 'volume_audit' | 'review_strictness'>>

const EFFORT_HINTS = {
  quick: '审稿只挑大毛病，不过关最多重写 1 次；卷纲只出一版、不再专门查。最快，最省额度。',
  balanced: '审稿照常挑，不过关最多重写 2 次；卷纲出两版挑好的，再专门查一遍。',
  premium: '审稿更严，中等毛病也退回，最多重写 3 次；卷纲出三版挑好的，再专门查一遍。最慢，最费额度。',
}

/** 编辑部写得多仔细：选了哪档，就用白话说哪档会怎样；以前自己调过的照实说。 */
export function effortHint(s: Pick<WritingSettings, 'effort_preset' | 'max_rewrites' | 'pitches' | 'volume_audit' | 'review_strictness'>): string {
  if (s.effort_preset !== 'custom') return EFFORT_HINTS[s.effort_preset]
  const review = { lenient: '只挑大毛病', standard: '照常挑', strict: '更严' }[s.review_strictness]
  const rewrite = s.max_rewrites ? `不过关最多重写 ${s.max_rewrites} 次` : '不过关不重写，直接停下来请你定'
  const volume = s.pitches > 1 ? `卷纲出 ${s.pitches} 版挑好的` : '卷纲只出一版'
  return `现在是以前自己调的：审稿${review}，${rewrite}；${volume}${s.volume_audit ? '，再专门查一遍' : ''}。点上面三档就换掉。`
}

/** 选的不是「自己写」，可是存着自己写过的话：说一声，不然看不出那句没生效。 */
export function unusedCustomNote(selected: string, custom: string): string | null {
  const text = custom.trim()
  if (selected === 'custom' || !text) return null
  return `你写过「${text.length > 30 ? `${text.slice(0, 30)}……` : text}」，选「自己写」才按这句来。`
}

export const CHAPTER_WORDS_HINT = '一章常见 2000～4000 字，番茄偏短，起点偏长'

/** 每章字数：500～20000 的整数；空着、写错了都不算。 */
export function parseChapterWords(value: string): number | null {
  const words = Number(value)
  return value.trim() && Number.isSafeInteger(words) && words >= 500 && words <= 20000 ? words : null
}
