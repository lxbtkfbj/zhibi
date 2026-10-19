import type { LibraryConfig, LibraryItem } from '../api/library'
import type { AuthorRequirement } from '../api/settings'
import type { ChatOutcome } from '../api/types'

export const REQUIREMENT_SCOPES = [['always', '一直有效'], ['next_chapter', '只管下一章'], ['this_volume', '只管这一卷'], ['next_volume', '只管下一卷']] as const
export type RequirementScope = typeof REQUIREMENT_SCOPES[number][0]
export interface ChatQuote { text: string; where: string }
export interface ChatTyping { thread: string; speaker: string; on: boolean; at: number; mode?: 'plan' }

export function isFeedbackConflict(error: unknown, direct: boolean) {
  return !direct && typeof error === 'object' && error !== null && 'status' in error && error.status === 409 && 'code' in error && error.code === 'use_feedback'
}

export async function sendChatFirst<T>(sendNote: () => Promise<T>, sendFeedback: () => Promise<void>, direct: boolean) {
  try { return await sendNote() } catch (error) {
    if (!isFeedbackConflict(error, direct)) throw error
    await sendFeedback()
  }
}

export function typingVisible(value: ChatTyping, thread: string, now: number) { return value.thread === thread && value.on && now - value.at < 120000 }

export function outcomeCopy(outcome: ChatOutcome, requirement?: AuthorRequirement) {
  if (outcome.kind === 'requirement' || outcome.kind === 'to_job') {
    if (!requirement) return { text: '这条要求已经删了', actions: [] }
    return { text: outcome.kind === 'to_job' ? '已交给编辑部：做完手头这一步就照办' : `已记成要求：「${requirement.text}」（${requirement.label}）`, actions: outcome.kind === 'to_job' ? [] : ['改一下'] }
  }
  if (outcome.kind === 'pending') return { text: '主编在看…', actions: [] }
  if (outcome.kind === 'working') return { text: `${outcome.text ?? '编辑部在做'}…`, actions: [] }
  if (outcome.kind === 'fill') return outcome.filled?.length
    ? { text: `补好了「${outcome.target_label}」空着的 ${outcome.filled.length} 栏：${outcome.filled.join('、')}`, actions: ['去看看'] }
    : { text: `「${outcome.target_label}」每一栏都写了，没补`, actions: ['去看看'] }
  if (outcome.kind === 'created') return { text: `写好了，放进了${outcome.target_label ?? '设定库'}`, actions: ['去看看'] }
  if (outcome.kind === 'outline') return { text: `写好了${outcome.target_label ?? '这一段'}，已经换上去`, actions: ['去看看'] }
  if (outcome.kind === 'plan_pending') return { text: '正在整理方案…', actions: [] }
  if (outcome.kind === 'too_late') return { text: '编辑部这时在等你拍板，这句话没有记，也没有改。要改的话，在拍板的地方提意见，或者让我总结成方案。', actions: [] }
  if (outcome.kind === 'failed' && outcome.redo_failed) return { text: `再改一版没做成（${outcome.reason}），这一处现在是改之前的样子。`, actions: [] }
  if (outcome.kind === 'failed') return { text: `没判断出来（${outcome.reason}），这句话没有记，也没有改。`, actions: ['其实要记下'] }
  if (outcome.kind === 'plan_apply') return { text: `照方案办：${outcome.label ?? '方案'}`, actions: [] }
  if (outcome.kind === 'plan_made') return { text: '刚才聊了不少，我先整理成方案，你看看再照办', actions: [] }
  if (outcome.kind === 'suggestion') return { text: '放进了待处理的建议', actions: ['去看看'] }
  if (outcome.kind === 'feedback') return { text: outcome.label ?? '', actions: [] }
  if (outcome.kind === 'chat') return { text: '只是聊天，没有记', actions: ['其实要记下'] }
  if (outcome.kind === 'later') return { text: '编辑部写完再改：在待处理的建议里', actions: ['去看看'] }
  if (outcome.kind === 'edit') return { text: `${outcome.mode === 'options' ? '三种写法，挑一个换上' : '改了'}：${outcome.target_label}`, actions: outcome.mode === 'options' ? [] : ['去看看'] }
  if (outcome.kind === 'saved') return { text: `存好了一档「${outcome.title ?? ''}」`, actions: ['去看存档'] }
  return { text: '', actions: [] }
}

/** 与设定库的中文部分名一致，角色字段名来自后端配置，不把数据库路径展示给作者。 */
export function libraryQuoteWhere(item: LibraryItem, path: string, config: LibraryConfig) {
  const selected = path.includes('@')
  path = path.split('@')[0]
  let part = path
  const level = /^levels\.(\d+)\.(name|text)$/.exec(path)
  if (level) part = `第 ${Number(level[1]) + 1} 级「${item.levels?.[Number(level[1])]?.name ?? ''}」的${level[2] === 'name' ? '名称' : '介绍'}`
  else if (path.startsWith('fields.')) part = path.slice(7)
  else if (path === 'name') part = '名称'
  else if (path === 'one_line') part = '一句话'
  else if (path === 'content') part = item.style === 'ladder' ? '总说明' : '一段话'
  else part = config.character_category.fields.find(field => field.column === path)?.name ?? (path === 'aliases' ? '别名' : path)
  return `设定库 · ${item.name} · ${part}${selected ? '里选中的一句' : ''}`
}


/** 判断两分钟没结果算超时；判断完在做的，后台最多做两分半，过了三分半还没回音也算没等到。 */
export function pendingOutcome(outcome: ChatOutcome, createdAt: string | null, now: number): ChatOutcome {
  const start = outcome.since ?? createdAt
  const waited = start ? now - Date.parse(start) : 0
  if (outcome.kind === 'pending' && waited >= 120000) return { kind: 'failed', reason: '判断超时' }
  if (outcome.kind === 'working' && waited >= 210000) return { kind: 'failed', reason: '没等到结果' }
  return outcome
}
