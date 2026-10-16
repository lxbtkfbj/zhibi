import type { Pending } from '../api/types'
import type { SetupQuestion } from './setupQuestions'

/** 第二包任务 4 第 3.5 节是题目与顺序的唯一规范。 */
export const NEXT_SEGMENT_QUESTIONS: SetupQuestion[] = [
  ['carried', '上一段留下的线头怎么收？', false],
  ['pursuit', '主角的追求要不要升级？', true],
  ['finger_next', '金手指下一步解锁什么？', false],
  ['answers', '快揭晓的谜，谜底是什么？', false],
  ['map', '这一段在哪张地图？', false],
  ['opponents', '主角和谁打？', false],
  ['people', '这一段谁登场？', false],
  ['goal', '这一段主角想做成什么？', true],
  ['wait', '这一段让读者等什么？', false],
  ['reveal', '这一段揭开什么？', false],
  ['end', '这一段走到哪里结束？', true],
  ['cast', '人物什么时候登场？', false],
  ['volumes', '这一段分几卷？', false],
  ['direction', '结局方向要调吗？', false],
].map(([key, title, focus]) => ({ key: String(key), title: String(title), focus: Boolean(focus), rows: [{ name: String(title), when: 'before' }] }))

export function nextSegmentQuestionFlags(key: string, pending?: Pending | null): string[] {
  if (pending?.kind !== 'segment_review' || !NEXT_SEGMENT_QUESTIONS.some(question => question.key === key)) return []
  return (pending.flags?.[key] ?? []).filter(flag => typeof flag === 'string' && !!flag.trim())
}

/** 钉死选择只属于这一轮待确认稿；换书、换任务、重出与新段都不会继承。 */
export function segmentReviewKey(jobId: string | undefined, pending: Pending | null | undefined): string {
  return jobId && pending?.kind === 'segment_review' ? `${jobId}:${pending.number}:${pending.round}` : ''
}
