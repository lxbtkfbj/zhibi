import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { AuthorChoice, SetupPiece } from '../../api/types'
import { Button, ErrorText } from '../../components/ui'
import { useBookContext } from './context'

/** 开书和定下一段共用同一组选择；提交者负责流程门禁和防重复。 */
export function Decisions({ decisions, name, disabled, loading, error, onRevise }: {
  decisions: AuthorChoice[]
  name: string
  disabled: boolean
  loading: boolean
  error: unknown
  onRevise: (flips: { topic: string; choice: string }[]) => void
}) {
  const [selected, setSelected] = useState<Record<number, string>>({})
  const flips = decisions.flatMap((decision, index) => selected[index] && selected[index] !== decision.chosen ? [{ topic: decision.topic, choice: selected[index] }] : [])
  return <section aria-label="替你做的决定" className="mb-6 rounded-xl border border-chief/20 bg-chief-soft/50 p-4">
    <h2 className="mb-3 font-serif text-base font-bold text-chief">替你做的决定</h2>
    <div className="space-y-4">{decisions.map((decision, index) => <fieldset key={`${index}-${decision.topic}`} disabled={disabled}>
      <legend className="mb-2 text-sm font-medium">{decision.topic}</legend>
      <div className="flex flex-wrap gap-2">{[...new Set([decision.chosen, ...decision.alternatives])].map(choice => <label key={choice} className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-line bg-card px-3 py-2 text-sm">
        <input type="radio" name={`${name}-decision-${index}`} checked={(selected[index] ?? decision.chosen) === choice} onChange={() => setSelected(previous => ({ ...previous, [index]: choice }))} className="accent-[var(--color-chief)]" />{choice}
      </label>)}</div><p className="mt-2 text-xs leading-relaxed text-ink-2">为什么：{decision.why}</p>
    </fieldset>)}</div>
    {!!flips.length && <Button className="mt-4" size="sm" onClick={() => onRevise(flips)} disabled={disabled} loading={loading}>按我选的改</Button>}
    <ErrorText error={error} />
  </section>
}

/** 旧页面保留决定展示入口；退役流程不再提供重新打开或解锁。 */
export function PieceDecisions({ piece }: { piece: SetupPiece }) {
  const { bookId, job } = useBookContext()
  const { pieceAction, setupPending } = useJobActions(bookId)
  const pending = job?.setup_flow === 3 && job.status === 'waiting_author' && job.pending?.kind === 'setup_piece' ? job.pending : null
  if (pending?.piece !== piece || !pending.decisions?.length) return null
  return <Decisions key={`${job?.id}-${pending.round}-${JSON.stringify(pending.decisions)}`} decisions={pending.decisions} name={`piece-${piece}`} disabled={setupPending} loading={pieceAction.isPending} error={pieceAction.error} onRevise={flips => job && pieceAction.mutate({ jobId: job.id, action: 'revise', piece, flips })} />
}
