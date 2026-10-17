import { pieceStatuses } from '../../lib/storyMap'
import { useBookContext } from './context'

export function usePuzzleProgress() {
  const { book, job } = useBookContext()
  const show = book.status === 'setting_up' || (job?.kind === 'book_setup' && job.status !== 'succeeded' && job.status !== 'cancelled')
  const pending = job?.status === 'waiting_author' ? job.pending : null
  const progress = pieceStatuses(book.setup_progress, job?.setup_flow ?? (book.concept.story ? 3 : undefined))
  if (pending?.kind === 'setup_piece') {
    progress.current = pending.piece
    progress.pieces = progress.pieces.map(piece => (piece.key === pending.piece || (pending.flow === 3 && pending.piece === 'settings' && piece.key === 'concept')) ? { ...piece, status: 'waiting', current: true } : { ...piece, current: false })
  } else if ((pending?.kind === 'setup_directions' || pending?.kind === 'setup_pitches')) {
    progress.current = 'concept'
    progress.pieces = progress.pieces.map(piece => piece.key === 'concept' ? { ...piece, status: 'waiting', current: true } : piece)
  }
  return { ...progress, show, prefill: pending?.kind === 'setup_prefill', choosing: (pending?.kind === 'setup_directions' || pending?.kind === 'setup_pitches') }
}
