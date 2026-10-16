import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { Job, Pending } from '../../api/types'
import { TechniqueChip } from '../../components/TechniqueChip'
import { Badge, Button, ErrorText } from '../../components/ui'

export function DirectionSelection({ job, pending }: { job: Job; pending: Extract<Pending, { kind: 'setup_directions' }> }) {
  const actions = useJobActions(job.book_id)
  const [length, setLength] = useState(pending.length.options[pending.length.recommended] ?? pending.length.options[0] ?? '')
  const [mix, setMix] = useState('')
  const [redoOpen, setRedoOpen] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [validation, setValidation] = useState('')
  const busy = actions.directions.isPending || actions.directions.isSuccess
  const choose = async (choice: number) => {
    if (busy) return
    try { await actions.directions.mutateAsync({ jobId: job.id, action: 'choose', choice, length, mix: mix.trim() }) } catch { /* 保留选择与混搭 */ }
  }
  const redo = async () => {
    if (busy) return
    if (!feedback.trim()) { setValidation('写一下哪里不满意'); return }
    setValidation('')
    try { await actions.directions.mutateAsync({ jobId: job.id, action: 'redo', feedback: feedback.trim() }) } catch { /* 保留意见 */ }
  }
  return <section className="space-y-5 border-b border-line pb-8" aria-label="选择开书方向">
    <div><p className="mb-2 text-xs tracking-[0.25em] text-chief">下一步 · 定调</p><h3 className="font-serif text-xl font-bold">先选一个想写的方向</h3><p className="mt-2 text-sm leading-relaxed text-ink-2">选好篇幅和方向，也可以混搭。接下来的每一块，都由你确认。</p></div>
    <fieldset disabled={busy} className="space-y-2"><legend className="mb-2 text-sm font-medium">{pending.length.question}</legend><div className="flex flex-wrap gap-2">
      {pending.length.options.map((option, index) => <label key={option} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${length === option ? 'border-chief bg-chief-soft text-chief' : 'border-line text-ink-2'}`}><input type="radio" name="direction-length" checked={length === option} onChange={() => setLength(option)} className="accent-chief" />{option}{index === pending.length.recommended && <span className="text-xs">推荐</span>}</label>)}
    </div></fieldset>
    <div className="space-y-4">{pending.directions.map((direction, index) => <article key={`${index}-${direction.name}`} className="rounded-xl border border-line bg-card p-5 shadow-sm" aria-label={`方向 ${index + 1}：${direction.name}`}>
      <div className="flex flex-wrap items-center gap-2"><span className="font-serif text-xl text-ink-3">0{index + 1}</span><h4 className="font-serif text-xl font-bold">{direction.name}</h4>{index === pending.recommended && <Badge tone="busy">主编推荐</Badge>}</div>
      <p className="my-3 font-serif text-base leading-relaxed">{direction.logline}</p>
      <dl className="space-y-2 text-sm leading-relaxed">{([
        ['主角', direction.protagonist], ['金手指', direction.golden_finger], ['开局', direction.opening], ['卖点', direction.selling_points?.join('；')], ['舞台阶梯', direction.stage_ladder], ['基调', direction.tone], ['目标读者', direction.reader], ['不同之处', direction.difference],
      ] as const).map(([label, value]) => value && <div key={label} className="flex gap-3"><dt className="w-16 shrink-0 text-ink-2">{label}</dt><dd className="min-w-0 break-words">{value}</dd></div>)}</dl>
      {(direction.editor_note || direction.techniques?.length > 0) && <footer className="mt-4 space-y-2 border-t border-line pt-3"><p className="text-xs leading-relaxed text-ink-2"><span className="mr-2 text-chief">批注</span>{direction.editor_note}</p><div className="flex flex-wrap gap-2">{direction.techniques?.map(name => <TechniqueChip key={name} name={name} />)}</div></footer>}
      <Button variant="soft" className="mt-4" onClick={() => void choose(index)} disabled={busy} loading={actions.directions.isPending && actions.directions.variables?.choice === index}>选这个</Button>
    </article>)}</div>
    <label className="block text-sm text-ink-2">想混搭就写在这里（比如：用方向一，但金手指换成方向二的）<textarea aria-label="混搭要求" value={mix} onChange={event => setMix(event.target.value)} disabled={busy} rows={3} className="mt-2 w-full rounded-lg border border-line bg-paper-2 p-3 text-sm text-ink focus:border-chief focus:outline-none" /></label>
    <button type="button" onClick={() => setRedoOpen(!redoOpen)} aria-expanded={redoOpen} className="text-sm text-ink-2 underline underline-offset-4">都不满意，重新出</button>
    {redoOpen && <div className="space-y-2"><textarea aria-label="不满意的地方" placeholder="说说哪里不满意，主编再换三个方向" value={feedback} onChange={event => setFeedback(event.target.value)} rows={3} className="w-full rounded-lg border border-line bg-paper-2 p-3 text-sm" /><p role="alert" className="text-sm text-seal">{validation}</p><Button onClick={() => void redo()} disabled={busy} loading={actions.directions.isPending && actions.directions.variables?.action === 'redo'}>重新出方向</Button></div>}
    {busy && <p role="status" className="text-sm text-chief">{actions.directions.variables?.action === 'redo' ? '主编正在重新拟定方向…' : '主编正在按你的选择定调…'}</p>}
    <ErrorText error={actions.directions.error} />
  </section>
}
