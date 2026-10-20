import type { Job } from '../api/types'
import type { VBook, VNode } from '../pages/workspace/model'

/** 时间向上取整，不把还有几秒钟说成已经结束。 */
export function teardownEta(seconds: number): string {
  if (seconds < 60) return '不到 1 分钟'
  const minutes = Math.ceil(seconds / 60)
  if (seconds < 3600) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return `${hours} 小时${rest ? ` ${rest} 分钟` : ''}`
}

export function teardownProgressView(book: VBook, job: Job | null) {
  const info = book.teardown
  const active = job?.kind === 'teardown' && (job.status === 'queued' || job.status === 'running')
  const pending = active && job.pending && 'teardown' in job.pending ? job.pending.teardown : undefined
  const stage = active ? job.status : info?.stage ?? 'imported'
  const all: VNode[] = []
  const walk = (node: VNode) => { all.push(node); node.children?.forEach(walk) }
  walk(book.outline)
  const chapters = all.filter(node => node.kind === '章')
  const total = pending?.total ?? info?.chapters ?? chapters.length
  const target = pending?.target ?? Math.min(info?.upto ?? total, total)
  const indexOf = (node: VNode) => Number(node.ref?.id ?? node.range?.[0] ?? /^c(\d+)$/.exec(node.id)?.[1] ?? 0)
  const inTarget = chapters.filter(node => indexOf(node) <= target)
  const read = pending?.read ?? inTarget.filter(node => node.teardown?.read).length
  const failed = [...new Set(pending?.failed ?? inTarget.filter(node => node.teardown?.failed).map(indexOf))].sort((a, b) => a - b)
  const counts = `已拆 ${read}／${target} 章${target < total ? `（拆到第 ${target} 章）` : ''}`
  const eta = pending?.eta_seconds !== undefined && pending.eta_seconds !== null ? ` · 还要大约 ${teardownEta(pending.eta_seconds)}` : ''
  let text = ''
  if (stage === 'queued' || pending?.doing === 'queued') text = '排队中：前面还有书在拆'
  else if (stage === 'running') {
    if (pending?.doing === 'units') text = `主编在归单元：第 ${pending.range?.[0]}–${pending.range?.[1]} 章 · ${counts}${eta}`
    else if (pending?.doing === 'volumes') text = `主编在归卷 · ${counts}`
    else if (pending?.doing === 'closing') text = '在收尾：把最后几章归进单元和卷'
    else {
      // 两批之间 reading 可为空；不伪造尚未开始读的章号。
      const reading = pending?.reading?.length === 2 ? `第 ${pending.reading[0]}–${pending.reading[1]} 章` : '原文'
      text = `设定师在读${reading} · ${counts}${eta}`
    }
  } else if (stage === 'stopped') text = info?.stop_note ?? ''
  else if (stage === 'done') {
    const units = all.filter(node => node.kind === '单元' && !node.virtual).length
    const volumes = all.filter(node => node.kind === '卷' && !node.open && !node.virtual).length
    text = `拆完了 · ${total} 章，${units} 个单元，${volumes} 卷`
  }
  return { visible: book.source === 'teardown' && stage !== 'confirming', stage, active: !!active || stage === 'queued' || stage === 'running', text, read, target, failed, percent: target > 0 ? Math.max(0, Math.min(100, read / target * 100)) : 0 }
}

/** 正文搜索没完成时不提前宣告没找到，出错也不冒充零条结果。 */
export function chapterSearchDisplay(titleHits: number, bodyHits: number | undefined, live: boolean) {
  return { empty: titleHits === 0 && (!live || bodyHits === 0), body: live && bodyHits !== 0 }
}
