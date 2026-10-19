/** 待处理挂在哪一条设定、哪一段大纲上：那一页最上面提醒一行，点「看看」打开待处理、找到那一条。 */

import { createContext } from 'react'
import type { LibrarySuggestion } from '../../api/library'
import { suggestionTargetId } from '../../lib/libraryView'

export interface PendingNotes {
  /** 挂在这一条（设定、大纲上的一段，按 id 认）上、还没处理的有几条 */
  count: (id: string) => number
  /** 打开待处理；给了 id 就找到挂在它上面的第一条 */
  open: (id?: string) => void
}

export const PendingContext = createContext<PendingNotes | null>(null)

/** 这一条建议说的是哪一处：新书页上打开它用的类型 */
export function pendingTarget(suggestion: LibrarySuggestion): { type: string; id: string } | null {
  const id = suggestionTargetId(suggestion)
  const raw = suggestion.target_type ?? (typeof suggestion.payload.target_type === 'string' ? suggestion.payload.target_type : null)
  if (!id || !raw) return null
  // 大纲上的篇在后台叫 node
  return { type: raw === 'node' ? 'segment' : raw, id }
}

/** 有具体改法的点「同意」；只说了毛病的、群聊里说的点「让编辑部改」 */
export function handOver(suggestion: LibrarySuggestion): boolean {
  return suggestion.kind === 'chat' || suggestion.payload.op === 'note'
}

/** 这一条是从哪来的：一行小字 */
export function sourceOf(suggestion: LibrarySuggestion): string {
  if (suggestion.kind === 'chat') return '群聊里说的，编辑部当时在写，没改'
  if (suggestion.kind === 'cascade') return '改了一处，别处要不要跟着改'
  if (suggestion.kind === 'written') return '正文里写到过'
  if (suggestion.kind === 'concept') return '改了简介以后，编辑部查出来的'
  if (suggestion.kind === 'fill_gap' || suggestion.kind === 'gap' || suggestion.kind === 'fill_gaps') return '编辑部看还缺什么'
  if (suggestion.kind === 'new_entry') return '大纲里冒出来的'
  if (/^第 \d+ 章/.test(suggestion.title)) return '写章的时候发现的'
  return '编辑部查出来的'
}

/** 同意之前先看一眼要改成什么（标题里没说清的那几种） */
export function previewOf(suggestion: LibrarySuggestion): string {
  const p = suggestion.payload
  if (p.op === 'set_field' && typeof p.value === 'string') return `改成：${p.value}`
  if (p.op === 'splice' && typeof p.new === 'string') return `改成：${p.new}`
  if (p.op === 'create_character' || p.op === 'create_entry') {
    const data = (p.op === 'create_character' ? p.character : p.entry) as Record<string, string> | undefined
    if (!data) return ''
    const where = p.op === 'create_character' ? '角色' : data.category ?? ''
    return `新建：${data.name ?? ''}${where ? `（${where}）` : ''}${data.one_line ? `：${data.one_line}` : ''}`
  }
  return ''
}
