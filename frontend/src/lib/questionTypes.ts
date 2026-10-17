export type AnswerWhen = 'before' | 'later'
export interface SetupQuestionRow { name: string; when: AnswerWhen }
export interface SetupQuestion { key: string; title: string; focus: boolean; rows: SetupQuestionRow[] }
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
