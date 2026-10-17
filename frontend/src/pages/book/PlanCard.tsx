import { useState } from 'react'
import { post } from '../../api/client'
import { useInvalidateLibrary } from '../../api/library'
import type { MeetingMessage, PlanItem, ChatOutcome as Outcome } from '../../api/types'
import { Button, ErrorText, inputClass } from '../../components/ui'
import { ChatOutcome } from './ChatActions'
import { useBookContext } from './context'

function planItemLabel(item: PlanItem) {
  if (item.where === '写作要求') return `写作要求（${item.scope}）`
  return [item.where, item.target, item.category ? `新建 · ${item.category}` : '', item.part].filter(Boolean).join(' · ')
}

function CreatedResult({ message, result, index }: { message: MeetingMessage; result: Outcome; index: number }) {
  const { bookId, manualNavigate } = useBookContext()
  const invalidate = useInvalidateLibrary(bookId)
  const [busy, setBusy] = useState(false)
  const [undone, setUndone] = useState(false)
  const [error, setError] = useState<unknown>(null)
  return <div className="mt-2 space-y-1 text-xs text-ink-2"><div className="flex flex-wrap gap-2"><span>{result.undone || undone ? '已撤销' : `已新建：${result.target_label}`}</span>{!result.undone && !undone && <><button className="underline" onClick={() => manualNavigate(`/books/${bookId}/library?cat=${encodeURIComponent(result.target_type === 'character' ? '角色卡片' : String(result.snapshot?.category ?? ''))}&id=${result.target_id}`)}>去看看</button><button className="underline disabled:opacity-40" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { await post(`/plans/${message.id}/results/${index}/undo`); await invalidate(); setUndone(true) } catch (cause) { setError(cause) } finally { setBusy(false) } }}>撤销</button></>}</div><ErrorText error={error} /></div>
}

export function PlanCard({ message }: { message: MeetingMessage }) {
  const { bookId, working, focusChat } = useBookContext()
  const invalidate = useInvalidateLibrary(bookId)
  const plan = message.payload?.plan
  const status = message.payload?.status
  const [items, setItems] = useState(() => plan?.items ?? [])
  const [editing, setEditing] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  if (!plan) return <p className="whitespace-pre-wrap">{message.content}</p>
  const open = status === 'open'
  const shown = open ? items : plan.items
  return <section data-testid={`plan-${message.id}`} className={status === 'superseded' ? 'space-y-3 opacity-50' : 'space-y-3'} aria-label={`方案：${plan.title}`}>
    <h3 className="font-serif font-bold text-chief">方案：{plan.title}</h3><p className="whitespace-pre-wrap text-sm leading-relaxed">{plan.summary}</p>
    {open && working && <p className="text-xs text-seal">编辑部正在写，要改设定和大纲的几条会先放进待处理的建议</p>}
    <ul className="space-y-2">{shown.map((item, index) => <li key={index} className="flex items-start gap-2 rounded-lg border border-divider bg-paper/60 p-2 text-sm"><div className="min-w-0 flex-1"><p className="mb-1 text-xs text-ink-2">{planItemLabel(item)}</p>{open && editing === index ? <textarea autoFocus aria-label={`修改方案第 ${index + 1} 条`} rows={3} className={inputClass} value={item.change} onChange={event => setItems(previous => previous.map((value, i) => i === index ? { ...value, change: event.target.value } : value))} onBlur={() => setEditing(null)} /> : open ? <button className="w-full whitespace-pre-wrap break-words text-left hover:text-chief" aria-label={`编辑方案第 ${index + 1} 条`} onClick={() => setEditing(index)}>{item.change}</button> : <p className="whitespace-pre-wrap break-words">{item.change}</p>}</div>{open && <button aria-label={`删除方案第 ${index + 1} 条`} disabled={busy} onClick={() => setItems(previous => previous.filter((_, i) => i !== index))} className="text-ink-3 hover:text-seal">×</button>}</li>)}</ul>
    {!!plan.open_questions.length && <p className="text-xs text-ink-2">还没定的：{plan.open_questions.join('；')}</p>}
    {open ? <div className="flex flex-wrap gap-2"><Button size="sm" loading={busy} disabled={items.some(item => !item.change.trim())} onClick={async () => { setBusy(true); setError(null); try { await post(`/plans/${message.id}/apply`, { items }); await invalidate() } catch (cause) { setError(cause) } finally { setBusy(false) } }}>按这个来</Button><Button size="sm" variant="ghost" onClick={focusChat}>接着聊</Button></div> : <p role="status" className="text-xs text-ink-2">{status === 'superseded' ? '已有新的方案' : status === 'applying' ? '正在照方案办…' : '已照办'}</p>}
    {(message.payload?.results ?? []).map((result, index) => result.kind === 'created' ? <CreatedResult key={index} message={message} result={result} index={index} /> : <ChatOutcome key={index} message={message} result={result} />)}
    <ErrorText error={error} />
  </section>
}
