import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { get, patch, post } from '../../api/client'
import { useLibrary, useRevertVersion } from '../../api/library'
import { settingsKeys, useAuthorRequirements } from '../../api/settings'
import type { ChangeDiff, MeetingMessage } from '../../api/types'
import { RequirementDialog } from '../../components/RequirementDialog'
import { ErrorText, TypingDots } from '../../components/ui'
import { outcomeCopy, pendingOutcome, type RequirementScope } from '../../lib/chat'
import { useBookContext } from './context'

/** 聊天里每一处改动现在还能不能换回、再改（后来又被动过就不能了）：跟着整本书一起刷新 */
function useNoteChanges(bookId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['workspace', bookId, 'note-changes'],
    queryFn: () => get<Record<string, boolean>>(`/books/${bookId}/note-changes`),
    enabled,
    staleTime: 0,
  })
}

/** 一栏的「原来」「改成」：原来浅色，改成正常色；太长折起来，点开看全文 */
export function DiffBlock({ diff }: { diff: ChangeDiff }) {
  const [open, setOpen] = useState(false)
  const long = diff.before.length + diff.after.length > 220 || (diff.before + diff.after).split('\n').length > 6
  const clamp = !open && long ? 'line-clamp-3' : ''
  return (
    <div className="rounded-lg border border-line bg-card px-3 py-2 text-left">
      <p className="text-[11px] text-ink-3">{diff.label}</p>
      {diff.before
        ? <p className={`mt-1 text-[13px] leading-relaxed whitespace-pre-line text-ink-3 ${clamp}`}><span className="mr-1 rounded bg-line/70 px-1 text-[11px]">原来</span>{diff.before}</p>
        : <p className="mt-1 text-[13px] text-ink-3"><span className="mr-1 rounded bg-line/70 px-1 text-[11px]">原来</span>（空着）</p>}
      {diff.after
        ? <p className={`mt-1 text-[13px] leading-relaxed whitespace-pre-line text-ink ${clamp}`}><span className="mr-1 rounded bg-lore/15 px-1 text-[11px] text-lore">改成</span>{diff.after}</p>
        : <p className="mt-1 text-[13px] text-ink-3"><span className="mr-1 rounded bg-lore/15 px-1 text-[11px] text-lore">改成</span>（删掉了）</p>}
      {long && <button type="button" onClick={() => setOpen(!open)} className="mt-1 text-xs text-ink-3 underline underline-offset-4 hover:text-ink">{open ? '收起' : '展开看全文'}</button>}
      {open && diff.truncated && <p className="mt-1 text-[11px] text-ink-3">太长了，这里只放了前 2000 字；全文去存档里看。</p>}
    </div>
  )
}

/** step：一句话拆成好几件事时，这是第几件（换回原来的、再改一版都只管那一件） */
export function ChatOutcome({ message, result, step }: { message: MeetingMessage; result?: NonNullable<MeetingMessage["payload"]>["outcome"]; step?: number }) {
  const { bookId, manualNavigate, messages, openTarget, openSaves } = useBookContext()
  const requirements = useAuthorRequirements(bookId)
  const library = useLibrary(bookId)
  const qc = useQueryClient()
  const rawOutcome = result ?? message.payload?.outcome
  const shown = !!rawOutcome?.diff?.length && !!rawOutcome?.change?.length
  const changes = useNoteChanges(bookId, shown)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  if (!rawOutcome || (message.payload?.thread && !result && !['plan_pending', 'plan_made', 'plan_apply', 'failed'].includes(rawOutcome.kind))) return null
  // 再改一版时从点的那一刻算，不从这句话发出来算
  const started = message.payload?.redo_since ?? message.created_at
  const outcome = { ...pendingOutcome(rawOutcome, started, now) }
  if (outcome.kind === 'plan_apply') outcome.label = messages.find(m => m.id === outcome.plan_id)?.payload?.plan?.title
  if (result?.kind === 'failed') return <p className="mt-2 text-xs text-seal">没做成：{result.reason}</p>
  const row = requirements.data?.find(item => item.id === outcome.requirement_id)
  if ((outcome.kind === 'requirement' || outcome.kind === 'to_job') && !requirements.data && !shown) return null
  const copy = outcomeCopy(outcome, row)
  const gone = !!rawOutcome.undone
  const key = step === undefined ? String(message.id) : `${message.id}:${step}`
  // 还没问到的先当能用：真点了后台会再查一遍，后来改过就说
  const fresh = changes.data ? changes.data[key] !== false : true
  const isRequirement = outcome.kind === 'requirement' || outcome.kind === 'to_job'
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['workspace', bookId] })
    void qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) })
    void qc.invalidateQueries({ queryKey: ['saves', bookId] })
  }
  const act = async (action: string) => {
    if (busy) return
    if (action === '改一下' || action === '其实要记下') { setEditing(true); return }
    if (action === '去看存档') { openSaves?.(outcome.save_id); return }
    setBusy(true); setError(null)
    try {
      if (action === '换回原来的' || action === '再改一版') {
        await post(`/books/${bookId}/notes/${message.id}/${action === '换回原来的' ? 'revert' : 'redo'}`, step === undefined ? {} : { step })
        refresh()
      } else if ((outcome.kind === 'later' || outcome.kind === 'suggestion')) manualNavigate(`/books/${bookId}/library?suggestions=1`)
      // 新书页上：直接打开那一条，不跳回旧版
      else if (openTarget && outcome.target_type && outcome.target_id) openTarget(outcome.target_type, outcome.target_id)
      else {
        const entry = library.data?.entries.find(item => item.id === outcome.target_id)
        const type = outcome.target_type
        manualNavigate(`/books/${bookId}/${type === 'concept' ? 'concept' : type === 'segment' || type === 'volume' || type === 'unit' ? `outline?node=${type}-${outcome.target_id}` : `library?cat=${encodeURIComponent(type === 'character' ? '角色卡片' : entry?.category ?? '')}&id=${outcome.target_id}`}`)
      }
    } catch (cause) {
      setError(cause)
      // 后来又改过：按钮变灰
      void qc.invalidateQueries({ queryKey: ['workspace', bookId, 'note-changes'] })
    } finally { setBusy(false) }
  }
  const save = async (text: string, scope: RequirementScope) => {
    if (row) await patch(`/requirements/${row.id}`, { text, scope })
    else await post(`/books/${bookId}/requirements`, { text, scope, message_id: message.id })
    await qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) })
  }
  const link = 'underline underline-offset-4 hover:text-chief disabled:cursor-not-allowed disabled:no-underline disabled:opacity-40'
  const dialog = editing && <RequirementDialog initial={row?.text ?? message.content} scope={row?.scope === 'chapter' ? 'next_chapter' : row?.scope === 'volume' ? 'this_volume' : 'always'} onClose={() => setEditing(false)} onSave={save} />
  if (shown) {
    const what = isRequirement ? (outcome.kind === 'to_job' ? '交给了编辑部：记成写作要求' : '记成了写作要求') : copy.text
    const canGo = !isRequirement && outcome.kind !== 'deleted' && !!outcome.target_type && !!outcome.target_id
    return (
      <div data-testid={`outcome-${message.id}`} className="mt-2 space-y-1.5 text-xs leading-relaxed text-ink-2">
        <p>{gone ? `已换回原来的：${outcome.target_label ?? (isRequirement ? '这条写作要求删掉了' : '这一处')}` : what}</p>
        {!gone && <div className="space-y-1.5">{(outcome.diff ?? []).map((diff, i) => <DiffBlock key={i} diff={diff} />)}</div>}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {!gone && !isRequirement && !!rawOutcome.redo && <button type="button" disabled={busy || !fresh} onClick={() => void act('再改一版')} className={link} title="照你这句话把这一处重新改一遍">再改一版</button>}
          {!gone && <button type="button" disabled={busy || !fresh} onClick={() => void act('换回原来的')} className={link} title={isRequirement ? '删掉这条要求' : '这一处换回改之前的样子'}>换回原来的</button>}
          {!gone && isRequirement && row && <button type="button" disabled={busy} onClick={() => void act('改一下')} className={link}>改一下</button>}
          {canGo && <button type="button" disabled={busy} onClick={() => void act('去看看')} className={link}>去看看</button>}
          {busy && <TypingDots />}
        </div>
        {!gone && !fresh && (
          <p className="text-ink-3">这一处后来又改过；要退就去{openSaves ? <button type="button" onClick={() => openSaves()} className="mx-0.5 underline underline-offset-4 hover:text-chief">存档</button> : '存档'}</p>
        )}
        <ErrorText error={error} />
        {dialog}
      </div>
    )
  }
  return <div data-testid={`outcome-${message.id}`} className="mt-2 space-y-1 text-xs leading-relaxed text-ink-2"><div className="flex flex-wrap items-center gap-x-2"><span>{gone ? '已换回原来的' : copy.text}</span>{(outcome.kind === 'pending' || outcome.kind === 'working') && <TypingDots />}{outcome.kind === 'working' && <span className="text-ink-3 tabular-nums">{Math.max(0, Math.round((now - Date.parse(outcome.since ?? started ?? '')) / 1000))} 秒</span>}{!gone && copy.actions.filter(action => action !== '去看存档' || openSaves).map(action => <button key={action} disabled={busy} className="underline underline-offset-4 hover:text-chief disabled:opacity-40" onClick={() => void act(action)}>{action}</button>)}</div><ErrorText error={error} />{outcome.kind === 'edit' && outcome.mode === 'options' && outcome.candidate_id && outcome.target_type && outcome.target_id && <ChatOptions bookId={bookId} candidateId={outcome.candidate_id} targetType={outcome.target_type} targetId={outcome.target_id} />}{dialog}</div>
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
