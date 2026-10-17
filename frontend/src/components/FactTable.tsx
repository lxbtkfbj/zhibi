import clsx from 'clsx'
import type { ReactNode } from 'react'
import './setupQuestions.css'

export function FactTable({ rows, className }: { rows: { label: string; value: ReactNode }[]; className?: string }) {
  return <dl className={clsx('setup-facts', className)}>{rows.map((row, index) => <div key={`${row.label}-${index}`} className="setup-fact-row border-b border-line py-3 first:pt-0 last:border-b-0 last:pb-0">
    <dt className="flex flex-wrap items-start gap-1.5 text-xs leading-relaxed text-ink-2"><span>{row.label}</span></dt>
    <dd className="min-w-0 text-[15px] leading-relaxed">{row.value}</dd>
  </div>)}</dl>
}
