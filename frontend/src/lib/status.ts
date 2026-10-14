import type { BookStatus, JobStatus } from '../api/types'

export type Tone = 'busy' | 'wait' | 'ok' | 'idle' | 'error'

export interface DisplayStatus {
  label: string
  tone: Tone
  action: string
}

/** 综合书的状态和最近任务的状态，得到界面上显示的状态与下一步动作。 */
export function displayStatus(book: BookStatus, job: JobStatus | null | undefined): DisplayStatus {
  if (job === 'failed') return { label: '出错了，可继续', tone: 'error', action: '去处理' }
  if (job === 'cancelled' && book !== 'ready') return { label: '已暂停', tone: 'idle', action: '去继续' }
  if (job === 'queued' || job === 'running') return { label: '编辑部开会中', tone: 'busy', action: '去看看' }
  if (job === 'waiting_author' || book === 'awaiting_approval') return { label: '等你拍板', tone: 'wait', action: '去拍板' }
  if (book === 'ready') return { label: '方案已定稿', tone: 'ok', action: '进入工作台' }
  if (book === 'writing') return { label: '写作中', tone: 'busy', action: '去看看' }
  return { label: '准备中', tone: 'idle', action: '打开' }
}

export function greeting(date = new Date()) {
  const h = date.getHours()
  if (h >= 5 && h < 11) return '早上好'
  if (h >= 11 && h < 13) return '中午好'
  if (h >= 13 && h < 18) return '下午好'
  if (h >= 18 && h < 23) return '晚上好'
  return '夜深了'
}

/** 去掉模型偶尔塞进书名的「（备选：…）」。 */
export function cleanTitle(title: string) {
  return title.replace(/\s*[（(]\s*备选[^）)]*[）)]\s*$/, '').trim() || title
}

/** 去掉卷名里重复的「第一卷：」前缀。 */
export function cleanVolumeTitle(title: string) {
  return title.replace(/^第[一二三四五六七八九十百\d]+卷\s*[：:、.．\s]\s*/, '').trim() || title
}
