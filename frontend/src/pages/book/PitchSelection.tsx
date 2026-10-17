import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { Job, Pending } from '../../api/types'
import { Badge, Button, ErrorText, inputClass } from '../../components/ui'

export function PitchSelection({ job, pending }: { job: Job; pending: Extract<Pending, { kind: 'setup_pitches' }> }) {
  const { pitches, setupPending } = useJobActions(job.book_id)
  const [length, setLength] = useState(pending.length.options[pending.length.recommended] ?? pending.length.options[0] ?? '')
  const [titles, setTitles] = useState<Record<number, string>>({})
  const [feedback, setFeedback] = useState('')
  const busy = setupPending || pitches.isSuccess
  const choose = (index: number) => pitches.mutate({ jobId: job.id, action: 'pick', index: index + 1, length: Number(length.match(/\d+/)?.[0]), ...(titles[index]?.trim() ? { title: titles[index].trim() } : {}) })
  return <section aria-label="选择短版定调" className="space-y-6">
    <div><h2 className="font-serif text-xl font-bold">先挑一个短版定调</h2><p className="mt-2 text-sm leading-relaxed text-ink-2">挑好篇幅和短版，主编会把它展开成定调。也可以在下面说说想怎么混搭。</p></div>
    {pending.benchmark && <section aria-label="主编对对标作品的理解" className="rounded-xl border border-chief/20 bg-chief-soft/40 p-4"><h3 className="mb-2 text-sm font-medium">主编对对标作品的理解</h3><p className="whitespace-pre-wrap text-sm leading-relaxed">{pending.benchmark}</p></section>}
    <fieldset disabled={busy}><legend className="mb-3 text-sm font-medium">{pending.length.question}</legend><div className="flex flex-wrap gap-2">{pending.length.options.map((option, index) => <label key={option} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${length === option ? 'border-chief bg-chief-soft text-chief' : 'border-line text-ink-2'}`}><input type="radio" name="pitch-length" checked={length === option} onChange={() => setLength(option)} />{option}{index === pending.length.recommended && <span className="text-xs">推荐</span>}</label>)}</div></fieldset>
    <div className="space-y-4">{pending.pitches.map((pitch, index) => <article key={`${index}-${pitch.name}`} aria-label={`短版 ${index + 1}：${pitch.name}`} className="rounded-xl border border-line bg-card p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2"><h3 className="font-serif text-lg font-bold">{index + 1}. {pitch.name}</h3>{pending.recommended === index + 1 && <Badge tone="busy">主编推荐</Badge>}</div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{pitch.text}</p>
      <fieldset disabled={busy} className="mt-4"><legend className="mb-2 text-xs text-ink-2">书名候选</legend><div className="flex flex-wrap gap-2">{pitch.titles.map(title => <button key={title} type="button" aria-pressed={titles[index] === title} onClick={() => setTitles(previous => ({ ...previous, [index]: previous[index] === title ? '' : title }))} className={`rounded-lg border px-3 py-2 text-sm ${titles[index] === title ? 'border-chief bg-chief-soft text-chief' : 'border-line'}`}>《{title}》</button>)}</div><input aria-label={`短版 ${index + 1} 的书名`} value={titles[index] ?? ''} onChange={event => setTitles(previous => ({ ...previous, [index]: event.target.value }))} placeholder="也可以自己写书名；不填就由主编起名" maxLength={200} className={`${inputClass} mt-3`} /></fieldset>
      <Button className="mt-4" variant="soft" disabled={busy} loading={pitches.isPending && pitches.variables?.index === index + 1} onClick={() => choose(index)}>用这个</Button>
    </article>)}</div>
    <label className="block text-sm text-ink-2">想换三个短版，或混搭不同版本？<textarea aria-label="重出短版的意见" value={feedback} onChange={event => setFeedback(event.target.value)} placeholder="例如：A 的主角配 B 的金手指" disabled={busy} rows={3} maxLength={5000} className={`${inputClass} mt-2`} /></label>
    <Button disabled={busy || !feedback.trim()} loading={pitches.isPending && pitches.variables?.action === 'redo'} onClick={() => pitches.mutate({ jobId: job.id, action: 'redo', feedback: feedback.trim() })}>都不要，再来</Button>
    {busy && <p role="status" className="text-sm text-chief">{pitches.variables?.action === 'redo' ? '主编正在重新出三个短版…' : '主编正在展开定调…'}</p>}
    <ErrorText error={pitches.error} />
  </section>
}
