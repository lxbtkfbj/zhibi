import clsx from 'clsx'
import type { ReactNode } from 'react'
import type { Pending, PieceKey } from '../api/types'
import { useReducedMotion } from '../lib/appearance'
import { SETUP_QUESTIONS, questionFlags, questionWhen, showLaterPlaceholder, type AnswerWhen } from '../lib/setupQuestions'
import { LATER_ANSWER } from '../lib/setupPresentation'
import './setupQuestions.css'

export function WhenBadge({ when, direction = false }: { when: AnswerWhen; direction?: boolean }) {
  return <span className={clsx('inline-flex shrink-0 rounded border px-1.5 py-0.5 font-sans text-xs font-normal leading-normal', when === 'before' ? 'border-chief/40 text-chief' : 'border-dashed border-ink-3/60 text-ink-2')}>
    {when === 'before' ? `开写前${direction ? ' · 只要方向' : ''}` : '写到再定'}
  </span>
}

export function QuestionSection({ piece, questionKey, pending, children, className }: { piece: PieceKey; questionKey: string; pending?: Pending | null; children: ReactNode; className?: string }) {
  const question = SETUP_QUESTIONS[piece].find(item => item.key === questionKey)
  if (!question) return null
  const when = questionWhen(question)
  const flags = questionFlags(piece, questionKey, pending)
  return <section id={`q-${questionKey}`} tabIndex={-1} aria-labelledby={`q-title-${questionKey}`} className={clsx('setup-question scroll-mt-6 border-b border-line py-6 outline-none first:pt-0 last:border-b-0 focus-visible:ring-2 focus-visible:ring-chief/30', className)}>
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
      {question.focus && <span className="inline-flex items-center gap-1.5 text-xs text-seal"><span className="size-1.5 rounded-full bg-seal" aria-hidden />重点看</span>}
      <h2 id={`q-title-${questionKey}`} className="font-serif text-[18px] leading-relaxed font-bold">{question.title}</h2>
      {when && <WhenBadge when={when} />}
    </div>
    {!!flags.length && <ul className="mb-4 space-y-1.5 text-xs leading-relaxed text-seal" aria-label="这道题的提醒">{flags.map((flag, index) => <li key={`${index}-${flag}`}>需要再看看：{flag}</li>)}</ul>}
    <div className="min-w-0 space-y-5 text-[15px] leading-relaxed">{children}</div>
  </section>
}

export function FocusQuestions({ piece }: { piece: PieceKey }) {
  const reduced = useReducedMotion()
  return <nav aria-label="作者重点看" className="mb-7 border-l-2 border-seal/35 pl-3 text-sm leading-relaxed">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5"><span className="font-medium text-ink-2">作者重点看：</span>{SETUP_QUESTIONS[piece].filter(question => question.focus).map(question => <a
      key={question.key} href={`#q-${question.key}`} className="text-chief underline decoration-chief/30 underline-offset-4 hover:decoration-chief focus-visible:outline-chief"
      onClick={event => { event.preventDefault(); const section = document.getElementById(`q-${question.key}`); section?.focus({ preventScroll: true }); section?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'start' }) }}
    >{question.title}</a>)}</div>
    <p className="mt-2 text-xs text-ink-2">其余的扫一眼就行，有问题编辑部会标出来。</p>
  </nav>
}

export function QuestionField({ label, when, direction, children }: { label: string; when?: AnswerWhen; direction?: boolean; children: ReactNode }) {
  return <div><div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-2"><span>{label}</span>{when && <WhenBadge when={when} direction={direction} />}</div>{children}</div>
}

export function LaterValue({ value, children }: { value: unknown; children?: ReactNode }) {
  if (showLaterPlaceholder('later', value)) return <p className="text-sm text-ink-3">{LATER_ANSWER}</p>
  return <>{children ?? (typeof value === 'string' ? <p className="whitespace-pre-wrap">{value}</p> : null)}</>
}
