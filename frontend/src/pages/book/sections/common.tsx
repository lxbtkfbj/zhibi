import type { ReactNode } from 'react'
import { Diamond, FretDivider } from '../../../components/decor'

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  action,
}: {
  eyebrow: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="mb-8">
      <p className="mb-2 flex items-center gap-2 text-xs tracking-[0.25em] text-ink-2">
        <Diamond />
        {eyebrow}
      </p>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 font-serif text-[26px] leading-tight font-bold">{title}</div>
        {action}
      </div>
      {subtitle && <div className="mt-2.5 max-w-2xl text-[15px] leading-relaxed text-ink-2">{subtitle}</div>}
      <FretDivider className="mt-6" />
    </div>
  )
}

export function FieldBlock({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <p className="mb-1.5 text-xs tracking-[0.15em] text-ink-2">{label}</p>
      <div className="text-[15px] leading-relaxed">{children}</div>
    </div>
  )
}

export function Locked({ locked }: { locked: boolean }) {
  if (!locked) return null
  return <p className="mb-5 rounded-xl bg-chief-soft/70 px-4 py-2.5 text-sm text-chief">编辑部正在工作，这里暂时只能看、不能改。</p>
}
