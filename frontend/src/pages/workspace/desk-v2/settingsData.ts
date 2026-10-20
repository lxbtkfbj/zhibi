import type { Job } from '../../../api/types.ts'
import { teardownProgressView } from '../../../lib/teardownProgress.ts'
import type { VBook, VEntry, VNode } from '../model.ts'

export const clean = (value?: string): string => value && value !== '（记录里没有）' ? value : ''
export const wan = (number: number) => number >= 10000 ? `${Math.round(number / 10000)} 万字` : `${number} 字`

export function nodes(root: VNode): VNode[] {
  return [root, ...(root.children ?? []).flatMap(nodes)]
}

export function currentRead(book: VBook): number {
  return Math.max(0, ...nodes(book.outline).filter(node => node.kind === '章' && node.teardown?.read).map(node => node.range?.[0] ?? 0))
}

/** 未整理且没有任何条目时只写现状；读到哪章和读过几章是两个不同的数。 */
export function emptyTeardownSettingsMeta(book: VBook, job: Job | null): string | null {
  if (book.source !== 'teardown' || book.teardown?.settings?.upto != null || book.categories.some(category => category.entries.length > 0)) return null
  const view = teardownProgressView(book, job)
  const pending = job?.pending && 'teardown' in job.pending ? job.pending.teardown : undefined
  if (view.active && pending?.doing === 'settings') return '设定师在整理设定，整理完这里就有了'
  if (view.stage === 'running') return '拆书收尾时会整理设定，到时这里就有了'
  const last = currentRead(book)
  if (last > 0 && (view.stage === 'stopped' || view.stage === 'queued')) return `设定还没整理：点右上角「接着拆」，拆到第 ${last} 章不变，只整理设定，不重读原文`
  if (last === 0) return '还没开拆，拆过的章会整理成角色卡和设定'
  return '设定还没整理'
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
