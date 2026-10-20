import type { VNode } from '../pages/workspace/model'

export interface TeardownReading { chapter: number; at: number }
const key = (bookId: string) => `zhibi:teardown-reading:${bookId}`

/** 只记读到哪，不保存原文；浏览器不许存储时就当没读过。 */
export function readTeardownReading(bookId: string): TeardownReading | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key(bookId)) ?? 'null')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null
    const { chapter, at } = value as Partial<TeardownReading>
    return Number.isInteger(chapter) && chapter! > 0 && typeof at === 'number' && Number.isFinite(at)
      ? { chapter: chapter!, at } : null
  } catch { return null }
}

export function writeTeardownReading(bookId: string, chapter: number): void {
  if (!Number.isInteger(chapter) || chapter < 1) return
  try { localStorage.setItem(key(bookId), JSON.stringify({ chapter, at: Date.now() })) } catch { /* 不影响读原文。 */ }
}

export function readingChapterNumber(node: Pick<VNode, 'ref' | 'range' | 'title'>): number {
  return Number(node.ref?.type === 'chapter' ? node.ref.id : node.range?.[0] ?? /第\s*(\d+)\s*章/.exec(node.title)?.[1] ?? 0)
}

/** 读过就展开那一卷；记录已失效或没读过就展开第一卷。 */
export function teardownDefaultVolume(book: { id: string; outline: VNode }): string | undefined {
  const saved = readTeardownReading(book.id)
  let first: string | undefined, found: string | undefined
  const visit = (node: VNode, volume?: string) => {
    if (node.kind === '卷') { volume = node.id; first ??= volume }
    if (node.kind === '章' && saved?.chapter === readingChapterNumber(node)) found = volume
    node.children?.forEach(child => visit(child, volume))
  }
  visit(book.outline)
  return found ?? first
}

type KeyEvent = Pick<KeyboardEvent, 'key' | 'defaultPrevented' | 'altKey' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'isComposing' | 'target'>
/** 正文只读区才接管方向键，输入、编辑、快捷键和输入法都不抢。 */
export function readingArrow(event: KeyEvent): -1 | 0 | 1 {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.isComposing) return 0
  const target = event.target as HTMLElement | null
  if (target?.isContentEditable || target?.closest?.('input, textarea, select, [role="textbox"], [contenteditable]:not([contenteditable="false"])')) return 0
  return event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
}

/** 普通子串匹配，不把用户输入当正则或 HTML。 */
export function textMatches(text: string, word: string): { text: string; match: boolean }[] {
  if (!word) return [{ text, match: false }]
  const parts: { text: string; match: boolean }[] = []
  let start = 0, at = text.indexOf(word)
  while (at !== -1) {
    if (at > start) parts.push({ text: text.slice(start, at), match: false })
    parts.push({ text: word, match: true })
    start = at + word.length
    at = text.indexOf(word, start)
  }
  if (start < text.length) parts.push({ text: text.slice(start), match: false })
  return parts
}
