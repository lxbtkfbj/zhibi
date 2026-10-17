import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { del, patch, post } from '../../api/client'
import { useLibrary, useRevertVersion } from '../../api/library'
import { settingsKeys, useAuthorRequirements } from '../../api/settings'
import type { MeetingMessage } from '../../api/types'
import { RequirementDialog } from '../../components/RequirementDialog'
import { ErrorText, TypingDots } from '../../components/ui'
import { outcomeCopy, pendingOutcome, type RequirementScope } from '../../lib/chat'
import { useBookContext } from './context'

export function ChatOutcome({ message, result }: { message: MeetingMessage; result?: NonNullable<MeetingMessage["payload"]>["outcome"] }) {
  const { bookId, manualNavigate, messages } = useBookContext()
  const requirements = useAuthorRequirements(bookId)
  const library = useLibrary(bookId)
  const revert = useRevertVersion(bookId)
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [undone, setUndone] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const rawOutcome = result ?? message.payload?.outcome
  if (!rawOutcome || (message.payload?.thread && !result && !['plan_pending', 'plan_made', 'plan_apply', 'failed'].includes(rawOutcome.kind))) return null
  const outcome = { ...pendingOutcome(rawOutcome, message.created_at, now) }
  if (outcome.kind === 'plan_apply') outcome.label = messages.find(m => m.id === outcome.plan_id)?.payload?.plan?.title
  if (result?.kind === 'failed') return <p className="mt-2 text-xs text-seal">没做成：{result.reason}</p>
  const row = requirements.data?.find(item => item.id === outcome.requirement_id)
  if ((outcome.kind === 'requirement' || outcome.kind === 'to_job') && !requirements.data) return null
  const copy = outcomeCopy(outcome, row)
  const act = async (action: string) => {
    if (busy) return
    if (action === '改一下' || action === '其实要记下') { setEditing(true); return }
    setBusy(true); setError(null)
    try {
      if (action === '撤销') {
        if (outcome.requirement_id) { await del(`/requirements/${outcome.requirement_id}`); await qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) }) }
        else if (outcome.revert_version_id) { await revert.mutateAsync(outcome.revert_version_id); setUndone(true) }
      } else if ((outcome.kind === 'later' || outcome.kind === 'suggestion')) manualNavigate(`/books/${bookId}/library?suggestions=1`)
      else {
        const entry = library.data?.entries.find(item => item.id === outcome.target_id)
        const type = outcome.target_type
        manualNavigate(`/books/${bookId}/${type === 'concept' ? 'concept' : type === 'segment' || type === 'volume' || type === 'unit' ? `outline?node=${type}-${outcome.target_id}` : `library?cat=${encodeURIComponent(type === 'character' ? '角色卡片' : entry?.category ?? '')}&id=${outcome.target_id}`}`)
      }
    } catch (cause) { setError(cause) } finally { setBusy(false) }
  }
  const save = async (text: string, scope: RequirementScope) => {
    if (row) await patch(`/requirements/${row.id}`, { text, scope })
    else await post(`/books/${bookId}/requirements`, { text, scope, message_id: message.id })
    await qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) })
  }
  return <div data-testid={`outcome-${message.id}`} className="mt-2 space-y-1 text-xs leading-relaxed text-ink-2"><div className="flex flex-wrap items-center gap-x-2"><span>{undone ? '已撤销' : copy.text}</span>{outcome.kind === 'pending' && <TypingDots />}{!undone && copy.actions.map(action => <button key={action} disabled={busy} className="underline underline-offset-4 hover:text-chief disabled:opacity-40" onClick={() => void act(action)}>{action}</button>)}</div><ErrorText error={error} />{editing && <RequirementDialog initial={row?.text ?? message.content} scope={row?.scope === 'chapter' ? 'next_chapter' : row?.scope === 'volume' ? 'this_volume' : 'always'} onClose={() => setEditing(false)} onSave={save} />}</div>
}
