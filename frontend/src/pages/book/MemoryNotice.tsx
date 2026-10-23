import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { get, post } from '../../api/client'
import { memoryKeys, useMemories, type Memory, type MemoryReceipt } from '../../api/memories'
import { receiptCopy } from '../../lib/memory'
import { ErrorText } from '../../components/ui'
import { useBookContext } from './context'

/** All three existing paths share the same receipt and optimistic-version undo. */
export function MemoryNotice({ receipt, undone = false }: { receipt: MemoryReceipt; undone?: boolean }) {
  const { bookId, openMemory } = useBookContext()
  const query = useMemories(bookId)
  const deletedQuery = useQuery({ queryKey: [...memoryKeys.book(bookId), receipt.id], queryFn: () => get<Memory>(`/books/${bookId}/memories/${receipt.id}`), enabled: receipt.action === 'forget', refetchInterval: 5000, retry: false })
  const qc = useQueryClient()
  const [cancelled, setCancelled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const gone = undone || cancelled
  const copy = receiptCopy(receipt, receipt.action === 'forget' ? deletedQuery.data : query.data?.find(row => row.id === receipt.id), gone)
  const pending = receipt.action === 'forget' ? deletedQuery.isPending : query.isPending
  const undo = async () => {
    setBusy(true); setError(null)
    try {
      await post(`/books/${bookId}/memories/${receipt.id}/undo`, { version: receipt.version })
      setCancelled(true)
    } catch (cause) { setError(cause) }
    finally { await qc.invalidateQueries({ queryKey: memoryKeys.all }); setBusy(false) }
  }
  return <div data-testid={`memory-notice-${receipt.id}`} className="mt-2 space-y-1 text-xs leading-relaxed text-ink-2">
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      {receipt.action === 'forget' ? <span>{copy.text}</span> : <button type="button" onClick={() => openMemory?.(receipt.id)} className="text-left hover:text-chief hover:underline">{copy.text}</button>}
      <span className="text-ink-3">{copy.meta}</span>
      {!gone && <span title={pending ? undefined : copy.title}><button type="button" disabled={busy || pending || copy.disabled} onClick={() => void undo()} className="underline underline-offset-4 hover:text-chief disabled:cursor-not-allowed disabled:no-underline disabled:opacity-40">撤销</button></span>}
    </div><ErrorText error={error} />
  </div>
}
