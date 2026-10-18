import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { del, get, patch, post } from '../../api/client'
import { useLibrary, useRevertVersion } from '../../api/library'
import { settingsKeys, useAuthorRequirements } from '../../api/settings'
import type { MeetingMessage } from '../../api/types'
import { RequirementDialog } from '../../components/RequirementDialog'
import { ErrorText, TypingDots } from '../../components/ui'
import { outcomeCopy, pendingOutcome, type RequirementScope } from '../../lib/chat'
import { useBookContext } from './context'

export function ChatOutcome({ message, result }: { message: MeetingMessage; result?: NonNullable<MeetingMessage["payload"]>["outcome"] }) {
  const { bookId, manualNavigate, messages, openTarget } = useBookContext()
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
        else if (outcome.kind === 'outline' && outcome.before && outcome.target_type && outcome.target_id) {
          // 大纲帮写：把改之前的样子存回去
          await post(`/books/${bookId}/outline/restore`, { target_type: outcome.target_type, target_id: outcome.target_id, before: outcome.before })
          setUndone(true)
          void qc.invalidateQueries({ queryKey: ['workspace', bookId] })
        }
        else if (outcome.kind === 'created' && outcome.items?.length) {
          // 群聊里新建的：撤销就是删掉建的那几条
          for (const item of outcome.items) await del(`/${item.target_type === 'character' ? 'characters' : 'world-entries'}/${item.target_id}`)
          setUndone(true)
          void qc.invalidateQueries({ queryKey: ['workspace', bookId] })
        }
        else if (outcome.revert_version_id) {
          await revert.mutateAsync(outcome.revert_version_id)
          setUndone(true)
          void qc.invalidateQueries({ queryKey: ['workspace', bookId] })
        }
      } else if ((outcome.kind === 'later' || outcome.kind === 'suggestion')) manualNavigate(`/books/${bookId}/library?suggestions=1`)
      // 新书页上：直接打开那一条，不跳回旧版
      else if (openTarget && outcome.target_type && outcome.target_id) openTarget(outcome.target_type, outcome.target_id)
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
  return <div data-testid={`outcome-${message.id}`} className="mt-2 space-y-1 text-xs leading-relaxed text-ink-2"><div className="flex flex-wrap items-center gap-x-2"><span>{undone ? '已撤销' : copy.text}</span>{(outcome.kind === 'pending' || outcome.kind === 'working') && <TypingDots />}{outcome.kind === 'working' && <span className="text-ink-3 tabular-nums">{Math.max(0, Math.round((now - Date.parse(message.created_at ?? '')) / 1000))} 秒</span>}{!undone && copy.actions.map(action => <button key={action} disabled={busy} className="underline underline-offset-4 hover:text-chief disabled:opacity-40" onClick={() => void act(action)}>{action}</button>)}</div><ErrorText error={error} />{outcome.kind === 'edit' && outcome.mode === 'options' && outcome.candidate_id && outcome.target_type && outcome.target_id && <ChatOptions bookId={bookId} candidateId={outcome.candidate_id} targetType={outcome.target_type} targetId={outcome.target_id} />}{editing && <RequirementDialog initial={row?.text ?? message.content} scope={row?.scope === 'chapter' ? 'next_chapter' : row?.scope === 'volume' ? 'this_volume' : 'always'} onClose={() => setEditing(false)} onSave={save} />}</div>
}

type Candidate = { id: string; options: { label: string; text: string }[]; chosen: number | null }

/** 聊天里给的三种写法：就在消息下面挑一个换上，换上以后能撤销。 */
function ChatOptions({ bookId, candidateId, targetType, targetId }: { bookId: string; candidateId: string; targetType: string; targetId: string }) {
  const qc = useQueryClient()
  const revert = useRevertVersion(bookId)
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  const [undoId, setUndoId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    get<Candidate[]>(`/books/${bookId}/candidates?target_type=${targetType}&target_id=${targetId}`)
      .then((rows) => setCandidate(rows.find((row) => row.id === candidateId) ?? null))
      .catch(setError)
  }, [bookId, candidateId, targetType, targetId])
  if (!candidate) return <ErrorText error={error} />
  const refresh = () => {
    for (const key of [['workspace', bookId], ['library', bookId]]) void qc.invalidateQueries({ queryKey: key })
  }
  const choose = async (index: number) => {
    setBusy(true); setError(null)
    try {
      const reply = await post<{ revert_version_id?: string | null }>(`/candidates/${candidate.id}/choose`, { index })
      setCandidate({ ...candidate, chosen: index })
      setUndoId(reply.revert_version_id ?? null)
      refresh()
    } catch (cause) { setError(cause) } finally { setBusy(false) }
  }
  const undo = async () => {
    if (!undoId) return
    setBusy(true); setError(null)
    try {
      await revert.mutateAsync(undoId)
      setCandidate({ ...candidate, chosen: null })
      setUndoId(null)
      refresh()
    } catch (cause) { setError(cause) } finally { setBusy(false) }
  }
  return (
    <div className="mt-1.5 space-y-1.5">
      {candidate.options.map((option, i) => (
        <div key={option.label} className="rounded-lg border border-line bg-card px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-line/70 px-2 py-px text-[11px] text-ink-2">{option.label}</span>
            {candidate.chosen === i
              ? <span className="ml-auto text-lore">已换上{undoId && <button type="button" disabled={busy} onClick={() => void undo()} className="ml-2 underline underline-offset-4 hover:text-chief">撤销</button>}</span>
              : <button type="button" disabled={busy} onClick={() => void choose(i)} className="ml-auto underline underline-offset-4 hover:text-chief disabled:opacity-40">用这个</button>}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed whitespace-pre-line text-ink">{option.text}</p>
        </div>
      ))}
      <ErrorText error={error} />
    </div>
  )
}
