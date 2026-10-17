import clsx from 'clsx'
import { Check, MessageSquareText } from 'lucide-react'
import { useState } from 'react'
import { useJobActions } from '../../api/hooks'
import type { Job, Pending } from '../../api/types'
import { Button } from '../../components/ui'
import { useBookContext } from './context'
import { PageHeader } from './sections/common'

/** 选故事方向：页面里只管点选，提交在书稿底部的操作条里。 */
export function PitchSelection({ job, pending }: { job: Job; pending: Extract<Pending, { kind: 'setup_pitches' }> }) {
  const { pitchChoice, setPitchChoice, requestFeedback } = useBookContext()
  const { setupPending } = useJobActions(job.book_id)
  const key = `${job.id}-${pending.round}`
  const current = pitchChoice?.key === key ? pitchChoice : null
  const [length, setLength] = useState(current?.length ?? pending.length.options[pending.length.recommended] ?? pending.length.options[0] ?? '')
  const [titles, setTitles] = useState<Record<number, string>>(() => current ? { [current.index]: current.title } : {})
  const busy = setupPending
  const choose = (index: number, title = titles[index] ?? '') => { if (!busy) setPitchChoice({ key, index, name: pending.pitches[index].name, title, length }) }
  const setTitle = (index: number, title: string) => {
    setTitles(previous => ({ ...previous, [index]: title }))
    choose(index, title)
  }
  return <section aria-label="选择故事方向" className="mx-auto max-w-[1500px]">
    <PageHeader eyebrow="书稿 · 定调" title="挑一个故事方向" subtitle="点一下卡片就选中，书名可以在卡片里挑，也可以自己写；选好后点底部的「用这个方向」，主编会把它展开成定调。" />
    {pending.benchmark && <section aria-label="主编对对标作品的理解" className="mb-6 rounded-xl border border-line bg-subtle px-4 py-3">
      <p className="text-xs text-ink-3">主编理解的对标作品</p>
      <p className="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-ink">{pending.benchmark}</p>
      <p className="mt-1.5 text-xs text-ink-3">理解得不对？在群聊里告诉主编。</p>
    </section>}
    <fieldset disabled={busy} className="mb-6">
      <legend className="mb-2 text-[13px] font-medium text-ink">{pending.length.question}</legend>
      <div className="flex flex-wrap gap-2">{pending.length.options.map((option, index) => <label key={option} className={clsx('flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-seal', length === option ? 'border-ink bg-ink text-paper-2' : 'border-line-2 bg-card text-ink-2 hover:text-ink')}>
        <input type="radio" name="pitch-length" className="sr-only" checked={length === option} onChange={() => { setLength(option); if (current) setPitchChoice({ ...current, length: option }) }} />{option}{index === pending.length.recommended && <span className={clsx('text-[11px]', length === option ? 'text-paper-2/70' : 'text-seal')}>推荐</span>}
      </label>)}</div>
    </fieldset>
    <div role="radiogroup" aria-label="三个故事方向" className="grid gap-4 @3xl/manuscript:grid-cols-3">{pending.pitches.map((pitch, index) => {
      const selected = current?.index === index
      return <article key={`${index}-${pitch.name}`} aria-label={`故事方向 ${index + 1}：${pitch.name}`} onClick={() => choose(index)}
        className={clsx('relative flex cursor-pointer flex-col rounded-xl border bg-card p-5 transition-[border-color,box-shadow]', selected ? 'border-ink shadow-[0_0_0_1px_var(--color-ink)]' : 'border-line hover:border-line-2 hover:shadow-[var(--shadow-paper)]', busy && 'pointer-events-none opacity-70')}>
        <div className="mb-3 flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-ink-3">方向 {index + 1}{pending.recommended === index + 1 && <span className="ml-2 rounded bg-seal-soft px-1.5 py-px text-[11px] text-seal-dark">主编推荐</span>}</p>
            <h3 className="mt-1 font-serif text-lg font-bold text-ink">{pitch.name}</h3>
          </div>
          <button type="button" role="radio" aria-checked={selected} aria-label={`选方向 ${index + 1}`} onClick={event => { event.stopPropagation(); choose(index) }}
            className={clsx('mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors', selected ? 'border-ink bg-ink text-paper-2' : 'border-line-2 bg-card')}>{selected && <Check className="size-3" />}</button>
        </div>
        <p className="flex-1 text-[14px] leading-[1.9] whitespace-pre-wrap text-ink-2">{pitch.text}</p>
        <fieldset disabled={busy} className="mt-4 border-t border-line pt-3" onClick={event => event.stopPropagation()}>
          <legend className="sr-only">书名</legend>
          <p className="mb-2 text-xs text-ink-3">书名（不选也行，主编会再起）</p>
          <div className="flex flex-wrap gap-1.5">{pitch.titles.map(title => <button key={title} type="button" aria-pressed={titles[index] === title} onClick={() => setTitle(index, titles[index] === title ? '' : title)}
            className={clsx('rounded-md border px-2.5 py-1 text-[13px] transition-colors', titles[index] === title ? 'border-chief/50 bg-chief-soft text-chief' : 'border-line-2 text-ink-2 hover:text-ink')}>《{title}》</button>)}</div>
          <input aria-label={`故事方向 ${index + 1} 的书名`} value={titles[index] ?? ''} onChange={event => setTitle(index, event.target.value)} onFocus={() => choose(index)} placeholder="自己写一个书名" maxLength={200}
            className="mt-2 h-8 w-full rounded-lg border border-line bg-card px-2.5 text-[13px] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
        </fieldset>
      </article>
    })}</div>
    <div className="mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-line-2 px-4 py-3 text-[13px] text-ink-2">
      <MessageSquareText aria-hidden className="size-4 shrink-0 text-ink-3" />
      <span className="min-w-0 flex-1">都不满意，或者想混搭？直接在群聊里说，比如「第一个的主角，配第二个的金手指」，主编会重出三个。</span>
      <Button size="sm" variant="outline" onClick={requestFeedback}>在群聊里说</Button>
    </div>
    {busy && <p role="status" className="mt-4 text-[13px] text-chief">主编正在处理你的选择…</p>}
  </section>
}
