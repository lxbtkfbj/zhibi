import type { BookDetail, Job } from '../api/types'

/** 与现有开写按钮一致：新书先写三章，其余默认十章；试读开关由后端本书设置决定。 */
export function initialWriteRequest(book: Pick<BookDetail, 'chapters_final' | 'trial_read_done'>) {
  return { until: 'count' as const, count: book.chapters_final === 0 && !book.trial_read_done ? 3 : 10 }
}

/** 只有确认的这个开书任务成功结束后才能开写，失败、取消和超时都不启动写作。 */
export async function waitForSetupCompletion(read: () => Promise<Job>, wait: () => Promise<void>, limit = 120) {
  for (let attempt = 0; attempt < limit; attempt += 1) {
    const job = await read()
    if (job.status === 'succeeded') return
    if (job.status === 'failed' || job.status === 'cancelled') throw new Error(job.error || '开书没有完成，请先处理开书任务。')
    await wait()
  }
  throw new Error('开书还没有结束，暂未自动开写。请稍后查看任务，完成后可点「开写」。')
}
