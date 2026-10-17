/** 后端 Python 的切片以 Unicode 字符计数，DOM Range 的偏移以 UTF-16 计数。 */
export function characterRange(text: string, start: number, end: number) {
  const left = Math.max(0, Math.min(start, end, text.length))
  const right = Math.max(left, Math.min(Math.max(start, end), text.length))
  return { start: Array.from(text.slice(0, left)).length, end: Array.from(text.slice(0, right)).length }
}

export function selectionPath(path: string, text: string, start: number, end: number) {
  const range = characterRange(text, start, end)
  return range.end > range.start ? `${path}@${range.start}:${range.end}` : null
}

export function selectedTextRange(root: HTMLElement, selection: Selection | null) {
  if (!selection || selection.isCollapsed || !selection.rangeCount) return null
  const range = selection.getRangeAt(0)
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null
  const prefix = range.cloneRange()
  prefix.selectNodeContents(root)
  prefix.setEnd(range.startContainer, range.startOffset)
  const start = prefix.toString().length
  return characterRange(root.textContent ?? '', start, start + range.toString().length)
}

/** 分句不丢标点和换行，DOM 中的原文与数据库逐字一致。 */
export function storySentences(value: string) {
  return value.match(/[^。！？!?\n]+[。！？!?]?|[。！？!?\n]/gu) ?? []
}

/** rewrite 的 applied.before/after 是整个字段，不是选区；候选的 option.text 才是替换片段。 */
export function appliedSelectionText(applied: { path: string; before: string; after: string }) {
  const bounds = applied.path.match(/@(\d+):(\d+)$/)
  if (!bounds) return applied.after
  const start = Number(bounds[1]), end = Number(bounds[2])
  const after = Array.from(applied.after)
  const count = after.length - Array.from(applied.before).length + end - start
  return after.slice(start, start + Math.max(0, count)).join('')
}
