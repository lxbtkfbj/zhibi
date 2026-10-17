import clsx from 'clsx'
import { ChevronDown, X } from 'lucide-react'
import { useState } from 'react'
import { post } from '../../api/client'
import { useInvalidateLibrary } from '../../api/library'
import type { MeetingMessage, PlanItem, ChatOutcome as Outcome } from '../../api/types'
import { Button, ErrorText, inputClass } from '../../components/ui'
import { ChatOutcome } from './ChatActions'
import { useBookContext } from './context'

/** 每条前面的类别小标签：落在哪里、改谁。 */
function planItemTag(item: PlanItem) {
  if (item.where === '写作要求') return `写作要求 · ${item.scope}`
  if (item.category) return `新建 · ${item.category}`
  return item.where
}
function planItemTarget(item: PlanItem) {
  if (item.where === '写作要求') return ''
  return [item.target, item.part].filter(Boolean).join(' · ')
}

const FOLDED = 3

function CreatedResult({ message, result, index }: { message: MeetingMessage; result: Outcome; index: number }) {
  const { bookId, manualNavigate } = useBookContext()
  const invalidate = useInvalidateLibrary(bookId)
  const [busy, setBusy] = useState(false)
  const [undone, setUndone] = useState(false)
  const [error, setError] = useState<unknown>(null)
  return <div className="space-y-1 text-xs text-ink-2"><div className="flex flex-wrap gap-x-3 gap-y-1"><span>{result.undone || undone ? '已撤销' : `已新建：${result.target_label}`}</span>{!result.undone && !undone && <><button className="text-chief hover:underline" onClick={() => manualNavigate(`/books/${bookId}/library?cat=${encodeURIComponent(result.target_type === 'character' ? '角色卡片' : String(result.snapshot?.category ?? ''))}&id=${result.target_id}`)}>去看看</button><button className="text-ink-2 hover:text-ink hover:underline disabled:opacity-40" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { await post(`/plans/${message.id}/results/${index}/undo`); await invalidate(); setUndone(true) } catch (cause) { setError(cause) } finally { setBusy(false) } }}>撤销</button></>}</div><ErrorText error={error} /></div>
}

/** 「总结一下」出的方案：单独一张卡，点文字就能改，「按这个来」才生效。 */
export function PlanCard({ message }: { message: MeetingMessage }) {
  const { bookId, working, focusChat } = useBookContext()
  const invalidate = useInvalidateLibrary(bookId)
  const plan = message.payload?.plan
  const status = message.payload?.status
  const [items, setItems] = useState(() => plan?.items ?? [])
  const [editing, setEditing] = useState<number | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  if (!plan) return <p className="whitespace-pre-wrap">{message.content}</p>
  const open = status === 'open'
  const shown = open ? items : plan.items
  const visible = expanded || shown.length <= FOLDED + 1 ? shown : shown.slice(0, FOLDED)
  const results = message.payload?.results ?? []
  return <section data-testid={`plan-${message.id}`} aria-label={`方案：${plan.title}`} className={clsx('overflow-hidden rounded-xl border bg-card', open ? 'border-line-2' : 'border-line', status === 'superseded' && 'opacity-60')}>
    <header className="px-4 pt-3.5 pb-3">
      <div className="flex items-center gap-2">
        <span className="shrink-0 rounded bg-chief-soft px-1.5 text-[11px] leading-5 text-chief">方案</span>
        <h3 className="min-w-0 flex-1 truncate font-serif text-[15px] font-bold text-ink" title={plan.title}>{plan.title}</h3>
        <span className="shrink-0 text-xs text-ink-3 tabular-nums">{shown.length} 条</span>
      </div>
      {plan.summary && <p className="mt-2 text-[13px] leading-relaxed whitespace-pre-wrap text-ink-2">{plan.summary}</p>}
      {open && working && <p className="mt-2 text-xs text-seal-dark">编辑部正在写，要改设定和大纲的几条会先放进待处理的建议</p>}
    </header>
    <ul className="border-t border-line">{visible.map((item, index) => <li key={index} className="group relative flex items-start gap-3 border-b border-line/70 px-4 py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <p className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs"><span className="rounded bg-subtle px-1.5 leading-5 text-ink-2 ring-1 ring-line">{planItemTag(item)}</span>{planItemTarget(item) && <span className="text-ink-3">{planItemTarget(item)}</span>}</p>
        {open && editing === index
          ? <textarea autoFocus aria-label={`修改方案第 ${index + 1} 条`} rows={4} className={clsx(inputClass, 'text-[13px] leading-relaxed')} value={item.change} onChange={event => setItems(previous => previous.map((value, i) => i === index ? { ...value, change: event.target.value } : value))} onBlur={() => setEditing(null)} />
          : open ? <button className="w-full rounded text-left text-[13px] leading-relaxed break-words whitespace-pre-wrap text-ink hover:text-chief" title="点一下就能改" aria-label={`编辑方案第 ${index + 1} 条`} onClick={() => setEditing(index)}>{item.change}</button>
            : <p className="text-[13px] leading-relaxed break-words whitespace-pre-wrap text-ink">{item.change}</p>}
      </div>
      {open && <button aria-label={`删除方案第 ${index + 1} 条`} title="这一条不要" disabled={busy} onClick={() => setItems(previous => previous.filter((_, i) => i !== index))} className="mt-0.5 shrink-0 rounded p-0.5 text-ink-3 opacity-60 transition-opacity group-hover:opacity-100 hover:bg-seal-soft hover:text-seal focus-visible:opacity-100"><X className="size-3.5" /></button>}
    </li>)}</ul>
    {visible.length < shown.length && <button type="button" onClick={() => setExpanded(true)} className="flex w-full items-center gap-1 border-t border-line px-4 py-2 text-xs text-chief hover:bg-subtle">展开其余 {shown.length - visible.length} 条<ChevronDown className="size-3.5" /></button>}
    {!!plan.open_questions.length && <details className="border-t border-line px-4 py-2 text-xs text-ink-2">
      <summary className="cursor-pointer text-ink-3 hover:text-ink">还有 {plan.open_questions.length} 处没定</summary>
      <ul className="mt-2 list-disc space-y-1 pl-4 leading-relaxed">{plan.open_questions.map((question, index) => <li key={index}>{question}</li>)}</ul>
    </details>}
    <footer className="flex flex-wrap items-center gap-2 border-t border-line bg-paper-2/70 px-4 py-2.5">
      {open ? <>
        <Button size="sm" variant="primary" loading={busy} disabled={!items.length || items.some(item => !item.change.trim())} onClick={async () => { setBusy(true); setError(null); try { await post(`/plans/${message.id}/apply`, { items }); await invalidate() } catch (cause) { setError(cause) } finally { setBusy(false) } }}>按这个来</Button>
        <Button size="sm" variant="ghost" onClick={focusChat}>接着聊</Button>
        <span className="ml-auto text-xs text-ink-3">点文字就能改，不要的删掉</span>
      </> : <p role="status" className="text-xs text-ink-2">{status === 'superseded' ? '已有新的方案' : status === 'applying' ? '正在照方案办…' : '已照办'}</p>}
    </footer>
    {(!!results.length || !!error) && <div className="space-y-2 border-t border-line px-4 py-2.5">
      {results.map((result, index) => result.kind === 'created' ? <CreatedResult key={index} message={message} result={result} index={index} /> : <ChatOutcome key={index} message={message} result={result} />)}
      <ErrorText error={error} />
    </div>}
  </section>
}
