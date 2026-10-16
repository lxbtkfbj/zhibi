import { RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { AuthorChoice, PieceKey } from '../../api/types'
import { Button, ErrorText, Modal } from '../../components/ui'
import { PIECES } from '../../lib/storyMap'
import { useBookContext } from './context'

function Choices({ decisions, piece }: { decisions: AuthorChoice[]; piece: PieceKey }) {
  const { bookId, job } = useBookContext()
  const { pieceAction } = useJobActions(bookId)
  const [selected, setSelected] = useState<Record<number, string>>({})
  const flips = decisions.flatMap((decision, index) => selected[index] && selected[index] !== decision.chosen ? [{ topic: decision.topic, choice: selected[index] }] : [])
  return <section aria-label="替你做的决定" className="mb-6 rounded-xl border border-chief/20 bg-chief-soft/50 p-4">
    <h2 className="mb-3 font-serif text-base font-bold text-chief">替你做的决定</h2>
    <div className="space-y-4">{decisions.map((decision, index) => <fieldset key={`${index}-${decision.topic}`} disabled={pieceAction.isPending}>
      <legend className="mb-2 text-sm font-medium">{decision.topic}</legend>
      <div className="flex flex-wrap gap-2">{[...new Set([decision.chosen, ...decision.alternatives])].map(choice => <label key={choice} className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-line bg-card px-3 py-2 text-sm">
        <input type="radio" name={`piece-${piece}-decision-${index}`} checked={(selected[index] ?? decision.chosen) === choice} onChange={() => setSelected(previous => ({ ...previous, [index]: choice }))} className="accent-[var(--color-chief)]" />{choice}
      </label>)}</div><p className="mt-2 text-xs leading-relaxed text-ink-2">为什么：{decision.why}</p>
    </fieldset>)}</div>
    {!!flips.length && <Button className="mt-4" size="sm" onClick={() => job && pieceAction.mutate({ jobId: job.id, action: 'revise', piece, flips })} loading={pieceAction.isPending}>按我选的改</Button>}
    <ErrorText error={pieceAction.error} />
  </section>
}

/** 同时负责该块的决定和重新打开；不在属于其他块的页面泄漏操作。 */
export function PieceDecisions({ piece }: { piece: PieceKey }) {
  const { bookId, book, job, working } = useBookContext()
  const { pieceAction } = useJobActions(bookId)
  const [open, setOpen] = useState(false)
  const pending = job?.status === 'waiting_author' && job.pending?.kind === 'setup_piece' ? job.pending : null
  const canReopen = !working && pending && book.setup_progress?.pieces?.[piece] === 'confirmed' && book.setup_progress?.mode === 'puzzle'
  const index = PIECES.findIndex(item => item.key === piece)
  const downstream = PIECES.slice(index + 1).filter(item => book.setup_progress?.pieces?.[item.key] === 'confirmed').map(item => item.name)
  return <>
    {pending?.piece === piece && !!pending.decisions?.length && <Choices key={`${job?.id}-${pending.round}-${JSON.stringify(pending.decisions)}`} decisions={pending.decisions} piece={piece} />}
    {canReopen && <div className="mb-5 flex flex-wrap items-center gap-2"><span className="text-xs text-lore">{PIECES[index].name} · 已确认</span><Button size="sm" variant="ghost" aria-label={`重新打开这一块：${PIECES[index].name}`} onClick={() => setOpen(true)}><RotateCcw className="size-4" />重新打开这一块</Button><ErrorText error={pieceAction.error} /></div>}
    <Modal open={!!canReopen && open} title={`重新打开「${PIECES[index].name}」`} onClose={() => { if (!pieceAction.isPending) setOpen(false) }} footer={<><Button variant="ghost" onClick={() => setOpen(false)} disabled={pieceAction.isPending}>取消</Button><Button onClick={async () => { if (!job) return; try { await pieceAction.mutateAsync({ jobId: job.id, action: 'reopen', piece }); setOpen(false) } catch { /* 原决定和错误保留。 */ } }} loading={pieceAction.isPending}>确认重新打开</Button></>}>
      <p className="text-sm leading-relaxed">{downstream.length ? `重新打开后，后面已经确认的「${downstream.join('」「')}」也会按新的内容重新检查一遍。` : '重新打开后，这一块会回到等你确认；后面的内容会按新的内容重新检查一遍。'}</p><ErrorText error={pieceAction.error} />
    </Modal>
  </>
}
