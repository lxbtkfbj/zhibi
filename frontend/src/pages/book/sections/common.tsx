import type { ReactNode } from 'react'

/** 页头只说「这是哪一页、有多少」：位置由书稿标签栏交代，eyebrow 只留给读屏。 */
export function PageHeader(props: {
  eyebrow: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
}) {
  const { title, subtitle, action } = props
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <p className="sr-only">{props.eyebrow}</p>
        <div className="font-serif text-[22px] leading-tight font-bold text-ink">{title}</div>
        {subtitle && <div className="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-ink-2">{subtitle}</div>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>
  )
}

export function FieldBlock({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <p className="mb-1.5 text-xs text-ink-3">{label}</p>
      <div className="text-[15px] leading-relaxed">{children}</div>
    </div>
  )
}

export function Locked({ locked }: { locked: boolean }) {
  if (!locked) return null
  return <p className="mb-5 flex items-center gap-2 rounded-lg border border-line bg-subtle px-3.5 py-2 text-[13px] text-ink-2"><span aria-hidden className="size-1.5 rounded-full bg-chief motion-safe:animate-pulse" />编辑部正在工作，这里暂时只能看、不能改。</p>
}
