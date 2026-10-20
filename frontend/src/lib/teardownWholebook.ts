import type { TeardownSummary } from '../api/types'

export interface TeardownWaitItem {
  code: string
  kind: '期待' | '伏笔'
  what: string
  planted: number
  hints: number[]
  resolved: number | null
  how: string
}

export interface TeardownWaits {
  upto: number | null
  last: number
  items: TeardownWaitItem[]
}

export function endingState(info: TeardownSummary | null | undefined, last: number, total: number): string {
  if (!last) return '还没开拆。拆到最后一章以后，这里写全书结局。'
  if (info?.ending?.upto === total && !info.ending.ended) return `主编看了最后几章：原书到第 ${total} 章还没收住全书，所以没写结局。补上后面的章节、拆到最后一章以后再看。`
  if (info?.stage === 'done') return '全书都拆过了，结局还没写：点右上角「补上整理」。'
  return `拆到最后一章以后，这里写全书结局：主线怎么了结、主角最后到了哪、各人的去向、停在什么画面。现在拆到第 ${last} 章，一共 ${total} 章。`
}

export function waitsState(last: number, stage: string, active: boolean): string {
  if (!last) return '还没开拆。拆过的章会把读者在等的事连起来：哪章立下、哪章兑现、吊了读者多久。'
  if (active) return '拆书收尾时整理，到时这里就有了。'
  if (stage === 'done') return '还没整理：点右上角「补上整理」，不重读原文。'
  return `还没整理：点右上角「接着拆」，选「只整理前 ${last} 章」，不重读原文。`
}

export const waitDuration = (item: TeardownWaitItem, last: number) => (item.resolved ?? last) - item.planted
export const longestWaits = (items: TeardownWaitItem[], last: number) => [...items].sort((a, b) => waitDuration(b, last) - waitDuration(a, last))
export function waitDurationText(item: TeardownWaitItem, last: number): string {
  return `（吊了 ${waitDuration(item, last)} 章${item.hints.length ? `，中间提起 ${item.hints.length} 次` : ''}）`
}

export function rhythmCaption(kind: string): string {
  return kind === '篇' ? '一格一篇，宽窄是章数' : kind === '卷' ? '一格一卷，宽窄是章数' : '一格一个单元，宽窄是章数'
}
