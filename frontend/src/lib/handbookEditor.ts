import type { HandbookItem } from '../api/handbooks.ts'

export function visibleHandbooks<T extends Pick<HandbookItem, 'name' | 'when'>>(items: T[], search: string): T[] {
  const needle = search.trim().toLocaleLowerCase()
  return items.filter(item => `${item.name} ${item.when}`.toLocaleLowerCase().includes(needle))
}

/** Failed switches always keep the committed state, including a server's exact 422 wording. */
export async function changeHandbookEnabled<T extends HandbookItem>(item: T, update: (enabled: boolean) => Promise<T>): Promise<{ item: T; error: string }> {
  try { return { item: await update(!item.enabled), error: '' } }
  catch (error) { return { item, error: error instanceof Error ? error.message : '暂时没能完成，请再试一次。' } }
}

export interface HandbookParagraph {
  kind: 'same' | 'change' | 'add' | 'delete'; left: string; right: string
}
const paragraphs = (body: string) => body.split(/\r?\n[\t ]*\r?\n/)
  .map(part => part.replace(/^(?:\r?\n)+|(?:\r?\n)+$/g, '')).filter(part => part.trim())

/** Exact paragraph LCS for ordinary handbooks; unique anchors bound work for very long inputs. */
function matchingParagraphs(left: string[], right: string[]): [number, number][] {
  if (left.length * right.length <= 1_000_000) {
    const width = right.length + 1
    const matrix = new Uint32Array((left.length + 1) * width)
    for (let i = left.length - 1; i >= 0; i--) for (let j = right.length - 1; j >= 0; j--) {
      matrix[i * width + j] = left[i] === right[j] ? matrix[(i + 1) * width + j + 1] + 1 : Math.max(matrix[(i + 1) * width + j], matrix[i * width + j + 1])
    }
    const matches: [number, number][] = []
    for (let i = 0, j = 0; i < left.length && j < right.length;) {
      if (left[i] === right[j]) { matches.push([i++, j++]); continue }
      if (matrix[(i + 1) * width + j] >= matrix[i * width + j + 1]) i++
      else j++
    }
    return matches
  }
  const positions = (items: string[]) => {
    const result = new Map<string, number>()
    items.forEach((part, index) => result.set(part, result.has(part) ? -1 : index))
    return result
  }
  const lp = positions(left), rp = positions(right)
  const pairs: [number, number][] = []
  left.forEach((part, i) => { const j = rp.get(part); if (lp.get(part) === i && j !== undefined && j >= 0) pairs.push([i, j]) })
  const tails: number[] = [], previous: number[] = []
  for (let i = 0; i < pairs.length; i++) {
    let low = 0, high = tails.length
    while (low < high) { const mid = (low + high) >>> 1; if (pairs[tails[mid]][1] < pairs[i][1]) low = mid + 1; else high = mid }
    previous[i] = low ? tails[low - 1] : -1
    tails[low] = i
  }
  const anchors: [number, number][] = []
  for (let i = tails.at(-1) ?? -1; i >= 0; i = previous[i]) anchors.push(pairs[i])
  anchors.reverse()
  // With no unique anchors, keep equal boundaries and pair the remaining paragraphs as changes.
  if (!anchors.length) {
    let first = 0, last = 0
    while (first < Math.min(left.length, right.length) && left[first] === right[first]) first++
    while (last < Math.min(left.length, right.length) - first && left[left.length - last - 1] === right[right.length - last - 1]) last++
    return [...Array.from({ length: first }, (_, i) => [i, i] as [number, number]), ...Array.from({ length: last }, (_, i) => [left.length - last + i, right.length - last + i] as [number, number])]
  }
  const matches: [number, number][] = []
  let li = 0, ri = 0
  for (const [i, j] of [...anchors, [left.length, right.length] as [number, number]]) {
    matches.push(...matchingParagraphs(left.slice(li, i), right.slice(ri, j)).map(([a, b]) => [a + li, b + ri] as [number, number]))
    if (i < left.length) matches.push([i, j])
    li = i + 1; ri = j + 1
  }
  return matches
}

export function compareHandbookParagraphs(system: string, mine: string): { rows: HandbookParagraph[]; changed: number; added: number; deleted: number } {
  const left = paragraphs(system), right = paragraphs(mine)
  const rows: HandbookParagraph[] = []
  let li = 0, ri = 0
  for (const [i, j] of [...matchingParagraphs(left, right), [left.length, right.length] as [number, number]]) {
    const count = Math.max(i - li, j - ri)
    for (let n = 0; n < count; n++) {
      const before = n < i - li ? left[li + n] : '', after = n < j - ri ? right[ri + n] : ''
      rows.push({ kind: before && after ? 'change' : before ? 'delete' : 'add', left: before, right: after })
    }
    if (i < left.length) rows.push({ kind: 'same', left: left[i], right: right[j] })
    li = i + 1; ri = j + 1
  }
  return { rows, changed: rows.filter(row => row.kind === 'change').length, added: rows.filter(row => row.kind === 'add').length, deleted: rows.filter(row => row.kind === 'delete').length }
}
