import clsx from 'clsx'
import type { ForeshadowStep, Foreshadowing } from '../api/types'
import { foreshadowAction } from '../lib/writingUi'
import { WritingHint } from './WritingLabels'

const ACTION_TONE: Record<string, string> = { 埋下: 'bg-lore-soft text-lore', 立下: 'bg-chief-soft text-chief', 提醒: 'bg-line/70 text-ink-2', 回收: 'bg-seal-soft text-seal-dark', 兑现: 'bg-seal-soft text-seal-dark' }

export function ForeshadowChips({ actions, ledger = [] }: { actions: ForeshadowStep[]; ledger?: Foreshadowing[] }) {
  if (!actions.length) return null
  return (
    <ul aria-label="期待与伏笔动作" className="flex flex-wrap gap-1.5">
      {actions.map((action, i) => {
        const { label, code, hint } = foreshadowAction(action, ledger)
        return <li key={i}><WritingHint label={`${label} ${code}`} hint={hint} className={clsx('rounded-full px-2.5 py-0.5 text-xs', ACTION_TONE[label] ?? 'bg-line/70 text-ink-2')}>{label} {code}</WritingHint></li>
      })}
    </ul>
  )
}
