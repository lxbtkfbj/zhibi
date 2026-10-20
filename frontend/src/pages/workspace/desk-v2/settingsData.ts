import type { Job } from '../../../api/types.ts'
import { teardownProgressView } from '../../../lib/teardownProgress.ts'
import { pinnedFirst, type VBook, type VEntry, type VNode } from '../model.ts'

export const clean = (value?: string): string => value && value !== '（记录里没有）' ? value : ''
export const wan = (number: number) => number >= 10000 ? `${Math.round(number / 10000)} 万字` : `${number} 字`

/** 拆书沿用后台出场顺序；作者书保留置顶顺序，再把主角提到其余角色之前。 */
export function orderedCharacters(entries: VEntry[], teardown: boolean): VEntry[] {
  if (teardown) return [...entries].sort((a, b) => (a.position ?? Number.MAX_SAFE_INTEGER) - (b.position ?? Number.MAX_SAFE_INTEGER))
  const rest = entries.filter(entry => !entry.pinnedAt)
  return [...pinnedFirst(entries), ...rest.filter(entry => entry.role === '主角'), ...rest.filter(entry => entry.role !== '主角')]
}

/** 别名、定位不算全卡栏；作者补过任一正文或现状，就不再当成一句话卡。 */
export function isOneLineCharacter(entry: VEntry): boolean {
  return !!clean(entry.oneLine)
    && entry.facts.every(([label, text, , key]) => ['别名', '定位'].includes(key ?? label) || !clean(text))
    && entry.sections.every(section => ['别名', '定位'].includes(section.key ?? section.label) || !clean(section.text))
    && !(entry.now ?? []).some(([, text]) => clean(text))
    && !entry.dead
}

export function characterFieldLabel(label: string, teardown: boolean): string {
  return teardown && label === '成长与结局' ? '变化' : label
}

export function nodes(root: VNode): VNode[] {
  return [root, ...(root.children ?? []).flatMap(nodes)]
}

export function currentRead(book: VBook): number {
  if (book.teardown?.last_read !== undefined) return book.teardown.last_read
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
  if (last > 0 && (view.stage === 'stopped' || view.stage === 'queued')) return `设定还没整理：点右上角「接着拆」，选「只整理前 ${last} 章」，不重读原文`
  if (view.stage === 'done') return '设定还没整理：点右上角「补上整理」，不重读原文'
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
