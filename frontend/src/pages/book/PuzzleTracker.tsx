import clsx from 'clsx'
import { Check, ChevronDown, Circle } from 'lucide-react'
import { useState } from 'react'
import { useNodes } from '../../api/hooks'
import type { PieceStatus } from '../../api/types'
import { nodeCounts, PIECES, PIECE_STATUS_LABELS } from '../../lib/storyMap'
import { useBookContext } from './context'
import { usePuzzleProgress } from './usePuzzleProgress'

export function PieceStatusIcon({ status }: { status: PieceStatus }) {
  if (status === 'confirmed' || status === 'done') return <Check aria-hidden="true" className={clsx('size-3.5 shrink-0', status === 'confirmed' ? 'text-lore' : 'text-ink-3')} />
  if (status === 'drafting') return <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-chief motion-safe:animate-pulse" />
  return <Circle aria-hidden="true" className={clsx('size-3.5 shrink-0', status === 'waiting' ? 'text-chief' : 'text-ink-3/65')} />
}

export function PuzzleTracker() {
  const { bookId, manualNavigate } = useBookContext()
  const { data: nodes = [] } = useNodes(bookId)
  const progress = usePuzzleProgress()
  const [expanded, setExpanded] = useState(false)
  const counts = nodeCounts(nodes)
  if (!progress.show) return null
  const current = progress.pieces.find(piece => piece.key === progress.current) ?? progress.pieces[0]
  const name = (key: string, label: string) => key === 'segment' ? `第一段 ${counts.pinned}/${counts.total}` : label
  return <section aria-label="开书拼图进度" data-testid="puzzle-tracker" className="shrink-0 border-b border-divider bg-paper-2 px-4 py-3">
    <button type="button" aria-expanded={expanded} aria-controls="puzzle-pieces" onClick={() => setExpanded(value => !value)} className="flex w-full items-center gap-2 text-left text-sm text-chief md:hidden">
      <span>{current.number} {name(current.key, current.name)} · {progress.choosing ? '等你选方向' : PIECE_STATUS_LABELS[current.status]}</span><ChevronDown className={clsx('ml-auto size-4', expanded && 'rotate-180')} />
    </button>
    <ol id="puzzle-pieces" className={clsx('mt-3 grid grid-cols-1 gap-1 md:mt-0 md:grid md:grid-cols-5', !expanded && 'hidden')}>
      {progress.pieces.map(piece => <li key={piece.key}><button type="button" title={`${piece.name} · ${PIECE_STATUS_LABELS[piece.status]}`} onClick={() => { manualNavigate(`/books/${bookId}${piece.path}`); setExpanded(false) }} aria-current={piece.current ? 'step' : undefined} className={clsx('flex min-h-10 w-full items-center justify-center gap-1.5 rounded-lg border px-1.5 py-2 text-xs', piece.status === 'waiting' ? 'border-chief/50 bg-chief-soft text-chief' : piece.status === 'confirmed' ? 'border-transparent text-lore' : piece.status === 'todo' ? 'border-transparent text-ink-3' : 'border-transparent text-ink-2')}>
        <PieceStatusIcon status={piece.status} /><span>{name(piece.key, PIECES.find(item => item.key === piece.key)!.name)}</span>
      </button></li>)}
    </ol>
  </section>
}
