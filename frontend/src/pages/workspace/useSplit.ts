/** 编辑部帮拆的状态：说想要什么 → 主编在出 → 一版草稿 → 收下或不要。界面在 Split.tsx。 */

import { useState } from 'react'
import { type SplitDraft, type SplitResult, useWorkspace } from './actions'
import type { VNode } from './model'

export interface Draft extends SplitDraft { dropped?: boolean }
interface SplitState {
  step: 'idle' | 'ask' | 'working' | 'review'
  request: string
  round: number
  result?: SplitResult
  drafts: Draft[]
  error: string
}

const IDLE: SplitState = { step: 'idle', request: '', round: 0, drafts: [], error: '' }
/** 出好的草稿先记在这里：去别的页再回来还在 */
const memory = new Map<string, SplitState>()

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

/** 这一页能不能让编辑部帮拆：单元出章纲（写好的章不动，只换没写的）；卷还没有单元时拆成单元（已经有单元的卷不整个重拆）。 */
export function splitLabel(node: VNode): string | undefined {
  if (node.kind === '单元') return '编辑部出章纲'
  return node.kind === '卷' && !node.children?.length ? '编辑部拆成单元' : undefined
}

export function useSplit(node: VNode) {
  const { actions, notify } = useWorkspace()
  const [state, setState] = useState<SplitState>(() => memory.get(node.id) ?? IDLE)
  const update = (change: Partial<SplitState> | ((s: SplitState) => SplitState)) => setState((s) => {
    const next = typeof change === 'function' ? change(s) : { ...s, ...change }
    memory.set(node.id, next)
    return next
  })
  const label = splitLabel(node)
  const available = !!label && !!actions.splitNode && !!actions.acceptSplit
  const run = (request: string, round: number) => {
    update({ step: 'working', error: '', request })
    actions.splitNode!(node, request, round)
      .then((result) => update({ step: 'review', result, round, drafts: result.drafts.map((d) => ({ ...d })), request: '' }))
      .catch((error: unknown) => update((s) => ({ ...s, step: s.result ? 'review' : 'ask', error: errorText(error) })))
  }
  const accept = () => {
    const kept = state.drafts.filter((d) => !d.dropped).map((d): SplitDraft => ({ name: d.name, text: d.text, sections: d.sections, chapters: d.chapters }))
    if (!kept.length) return
    actions.acceptSplit!(node, kept)
      .then((undo) => {
        memory.delete(node.id)
        setState(IDLE)
        notify?.(`收下了 ${kept.length} ${node.kind === '单元' ? '章' : '个单元'}，放进了大纲`, undo)
      })
      .catch((error: unknown) => update({ error: errorText(error) }))
  }
  return {
    state, label, available,
    open: () => update({ step: 'ask', error: '' }),
    close: () => { memory.delete(node.id); setState(IDLE) },
    setRequest: (request: string) => update({ request }),
    start: () => run(state.request, 1),
    again: (request: string) => run(request, state.round + 1),
    edit: (index: number, change: Partial<Draft>) => update((s) => ({ ...s, drafts: s.drafts.map((d, i) => (i === index ? { ...d, ...change } : d)) })),
    accept,
  }
}

export type Split = ReturnType<typeof useSplit>
