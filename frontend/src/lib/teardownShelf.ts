import type { ChapterBrief, TeardownSummary } from '../api/types'

/** 只在旧后台缺少汇总计数时读已有目录；新接口不增加逐本请求。 */
export function needsTeardownShelfRead(info?: TeardownSummary | null): boolean {
  return !!info && ['running', 'stopped'].includes(info.stage) && typeof info.read !== 'number'
}

/** 目录不含原文；只数真正读过的章，不能用 upto（最后章号）替代。 */
export function teardownShelfRead(chapters: Pick<ChapterBrief, 'teardown'>[], total: number): number | undefined {
  if (chapters.length !== total || chapters.some(chapter => typeof chapter.teardown?.read !== 'boolean')) return undefined
  return chapters.filter(chapter => chapter.teardown?.read).length
}

/** 书架只显示拆书状态；出错原因保留在鼠标提示里，不把聊天句子当状态。 */
export function teardownShelfStatus(info?: TeardownSummary | null, fallbackRead?: number): { text: string; title?: string } {
  const chapters = info?.chapters ?? 0
  const count = `已拆 ${info?.read ?? fallbackRead ?? '—'} / ${chapters} 章`
  if (info?.stage === 'confirming') return { text: '还没确认分章' }
  if (info?.stage === 'queued') return { text: '排队中' }
  if (info?.stage === 'running') return { text: `正在拆 · ${count}` }
  if (info?.stage === 'stopped') {
    return ['model', 'error'].includes(info.stop_reason ?? '')
      ? { text: `${count} · 出错停了`, title: info.stop_note ?? undefined }
      : { text: count }
  }
  if (info?.stage === 'done') return { text: `拆完了 · ${chapters} 章` }
  return { text: `已导入 ${chapters} 章 · 还没开拆` }
}
