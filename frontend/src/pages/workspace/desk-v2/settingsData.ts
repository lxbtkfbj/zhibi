import type { VBook, VEntry, VNode } from '../model.ts'

export const clean = (value?: string): string => value && value !== '（记录里没有）' ? value : ''
export const wan = (number: number) => number >= 10000 ? `${Math.round(number / 10000)} 万字` : `${number} 字`

export function nodes(root: VNode): VNode[] {
  return [root, ...(root.children ?? []).flatMap(nodes)]
}

export function currentRead(book: VBook): number {
  return Math.max(0, ...nodes(book.outline).filter(node => node.kind === '章' && node.teardown?.read).map(node => node.range?.[0] ?? 0))
}

export function spans(numbers: number[]): string {
  const out: string[] = []
  let first: number | undefined, last: number | undefined
  for (const number of [...new Set(numbers)].sort((a, b) => a - b)) {
    if (first === undefined) first = last = number
    else if (number === last! + 1) last = number
    else { out.push(first === last ? `${first}` : `${first}–${last}`); first = last = number }
  }
  if (first !== undefined) out.push(first === last ? `${first}` : `${first}–${last}`)
  return out.join('、')
}

export function momentLines(entry: VEntry) {
  const text = clean(entry.sections.find(section => (section.key ?? section.label) === '名场面')?.text ?? entry.facts.find(([label, , , key]) => (key ?? label) === '名场面')?.[1])
  return text.split('\n').filter(Boolean).map(raw => {
    const match = /^第\s*(\d+)\s*章[：:]\s*(.*?)——(?:立住了|立住)[：:]?\s*(.*)$/.exec(raw)
    return match ? { chapter: Number(match[1]), what: match[2], shows: match[3], raw } : { raw }
  })
}
