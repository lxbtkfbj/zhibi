import clsx from 'clsx'
import { BookOpen, Check, ChevronDown, Circle, Globe2, Lightbulb, Route, UserRound } from 'lucide-react'
import { useState } from 'react'
import type { SetupPiece, PieceStatus } from '../../api/types'
import { PIECE_STATUS_LABELS } from '../../lib/storyMap'
import { useBookContext } from './context'
import { usePuzzleProgress } from './usePuzzleProgress'

const PIECE_ICONS = { concept: Lightbulb, settings: Globe2, outline: Route, protagonist: UserRound, world: Globe2, segment: Route, first_volume: BookOpen }

export function PieceStatusIcon({ status, piece }: { status: PieceStatus; piece?: SetupPiece }) {
  if (status === 'confirmed' || status === 'done') return <Check aria-hidden="true" className={clsx('size-3.5 shrink-0', status === 'confirmed' ? 'text-lore' : 'text-ink-3')} />
  if (status === 'drafting') return <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-chief motion-safe:animate-pulse" />
  const Icon = piece ? PIECE_ICONS[piece] : Circle
  return <Icon aria-hidden="true" className={clsx('size-3.5 shrink-0', status === 'waiting' ? 'text-chief' : 'text-ink-3/65')} />
}

export function PuzzleTracker() {
  const { bookId, manualNavigate } = useBookContext()
  const progress = usePuzzleProgress()
  const [expanded, setExpanded] = useState(false)
  if (!progress.show) return null
  const current = progress.pieces.find(piece => piece.key === progress.current) ?? progress.pieces[0]
  return <section aria-label="开书拼图进度" data-testid="puzzle-tracker" className="shrink-0 border-b border-divider bg-paper-2 px-4 py-3">
    <button type="button" aria-expanded={expanded} aria-controls="puzzle-pieces" onClick={() => setExpanded(value => !value)} className="flex w-full items-center gap-2 text-left text-sm text-chief md:hidden">
      <span>{current.number} {current.name} · {progress.choosing ? '等你挑短版' : PIECE_STATUS_LABELS[current.status]}</span><ChevronDown className={clsx('ml-auto size-4', expanded && 'rotate-180')} />
    </button>
    <ol id="puzzle-pieces" className={clsx('mt-3 grid grid-cols-1 gap-1 md:mt-0 md:grid', progress.pieces.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-5', !expanded && 'hidden')}>
      {progress.pieces.map(piece => <li key={piece.key}><button type="button" title={`${piece.name} · ${PIECE_STATUS_LABELS[piece.status]}`} onClick={() => { manualNavigate(`/books/${bookId}${piece.path}`); setExpanded(false) }} aria-current={piece.current ? 'step' : undefined} className={clsx('flex min-h-10 w-full items-center justify-center gap-1.5 rounded-lg border px-1.5 py-2 text-xs', piece.status === 'waiting' ? 'border-chief/50 bg-chief-soft text-chief' : piece.status === 'confirmed' ? 'border-transparent text-lore' : piece.status === 'todo' ? 'border-transparent text-ink-3' : 'border-transparent text-ink-2')}>
        <PieceStatusIcon status={piece.status} piece={piece.key} /><span>{piece.name}</span>
      </button></li>)}
    </ol>
  </section>
}
