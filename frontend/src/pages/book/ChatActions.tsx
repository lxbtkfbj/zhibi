import { useGroupFeedback } from './useGroupFeedback'
import { sendChatFirst } from '../../lib/chat'
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { del, patch, post } from '../../api/client'
import { useLibrary, useRevertVersion } from '../../api/library'
import { settingsKeys, useAuthorRequirements } from '../../api/settings'
import type { MeetingMessage } from '../../api/types'
import { RequirementDialog } from '../../components/RequirementDialog'
import { Button, ErrorText, inputClass, Modal } from '../../components/ui'
import { outcomeCopy, type RequirementScope } from '../../lib/chat'
import { useBookContext } from './context'

export function ChatOutcome({ message }: { message: MeetingMessage }) {
  const { bookId, manualNavigate } = useBookContext()
  const requirements = useAuthorRequirements(bookId)
  const library = useLibrary(bookId)
  const revert = useRevertVersion(bookId)
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [undone, setUndone] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const outcome = message.payload?.outcome
  if (!outcome || message.payload?.thread) return null
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
      } else if (outcome.kind === 'later') manualNavigate(`/books/${bookId}/library?suggestions=1`)
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
  return <div data-testid={`outcome-${message.id}`} className="mt-2 space-y-1 text-xs leading-relaxed text-ink-2"><div className="flex flex-wrap items-center gap-x-2"><span>{undone ? '已撤销' : copy.text}</span>{!undone && copy.actions.map(action => <button key={action} disabled={busy} className="underline underline-offset-4 hover:text-chief disabled:opacity-40" onClick={() => void act(action)}>{action}</button>)}</div><ErrorText error={error} />{editing && <RequirementDialog initial={row?.text ?? message.content} scope={row?.scope === 'chapter' ? 'next_chapter' : row?.scope === 'volume' ? 'this_volume' : 'always'} onClose={() => setEditing(false)} onSave={save} />}</div>
}

interface Conclusion { found: boolean; text: string; scope: '一直有效' | '只管下一章' | '只管这一卷' | '只管下一卷' }
export function ConclusionActions({ thread }: { thread: string }) {
  const { bookId } = useBookContext()
  const feedback = useGroupFeedback()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<(Conclusion & { mode: 'requirement' | 'instruction' }) | null>(null)
  const [instruction, setInstruction] = useState('')
  const conclude = async (mode: 'requirement' | 'instruction') => { setBusy(true); setError(null); try { const response = await post<Conclusion>(`/books/${bookId}/chat/${thread}/conclude`, { mode }); if (!response.found) throw new Error('这段对话里还没聊出要落实的结论。'); setResult({ ...response, mode }); setInstruction(response.text) } catch (cause) { setError(cause) } finally { setBusy(false) } }
  return <div className="mt-2 text-xs text-ink-2"><div className="flex gap-3"><button disabled={busy} className="hover:text-chief disabled:opacity-40" onClick={() => void conclude('requirement')}>记成要求</button><button disabled={busy} className="hover:text-chief disabled:opacity-40" onClick={() => void conclude('instruction')}>照这个改</button></div><ErrorText error={error} />
    {result?.mode === 'requirement' && <RequirementDialog initial={result.text} scope={{ '一直有效': 'always', '只管下一章': 'next_chapter', '只管这一卷': 'this_volume', '只管下一卷': 'next_volume' }[result.scope] as RequirementScope} onClose={() => setResult(null)} onSave={async (text, scope) => { await post(`/books/${bookId}/requirements`, { text, scope, source: `chat:${thread}` }); await qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) }) }} />}
    {result?.mode === 'instruction' && <Modal open title="交给编辑部的话" onClose={() => !busy && setResult(null)} footer={<><Button variant="ghost" disabled={busy} onClick={() => setResult(null)}>取消</Button><Button loading={busy} disabled={!instruction.trim()} onClick={async () => { setBusy(true); setError(null); try { const m = await sendChatFirst(() => post<MeetingMessage>(`/books/${bookId}/notes`, { content: instruction.trim() }), () => feedback(instruction.trim()), false); await post(`/books/${bookId}/chat/${thread}/receipt`, m ? { message_id: m.id } : { content: instruction.trim() }); setResult(null) } catch (cause) { setError(cause) } finally { setBusy(false) } }}>发到群聊</Button></>}><textarea aria-label="交给编辑部的话" className={`${inputClass} min-h-28 w-full`} value={instruction} onChange={event => setInstruction(event.target.value)} /><ErrorText error={error} /></Modal>}
  </div>
}
