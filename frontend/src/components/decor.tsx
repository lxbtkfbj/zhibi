import clsx from 'clsx'
import { useId } from 'react'

/** 朱砂印章。 */
export function Seal({ text = '笔', size = 36, className }: { text?: string; size?: number; className?: string }) {
  return (
    <span
      className={clsx('relative inline-flex shrink-0 items-center justify-center rounded-[6px] bg-seal font-serif font-bold text-paper-2', className)}
      style={{ width: size, height: size, fontSize: size * (text.length > 1 ? 0.36 : 0.55), lineHeight: 1 }}
    >
      <span className="absolute inset-[3px] rounded-[3px] border border-paper-2/40" />
      <span className={text.length > 1 ? 'grid grid-cols-2 gap-0' : ''}>{text}</span>
    </span>
  )
}

/** 层叠的水墨远山（静态），可带一轮朱砂日。 */
export function InkMountains({ className, sun = true }: { className?: string; sun?: boolean }) {
  return (
    <svg viewBox="0 0 1200 240" preserveAspectRatio="xMidYMax slice" className={className} aria-hidden>
      {sun && <circle cx="930" cy="70" r="34" fill="var(--color-seal)" opacity="0.78" />}
      <path
        d="M0 170 C90 140 160 108 250 122 C330 134 380 86 470 92 C560 98 610 150 720 132 C820 116 880 70 980 86 C1070 100 1130 132 1200 122 L1200 240 L0 240Z"
        fill="var(--color-ink)"
        opacity="0.05"
      />
      <path
        d="M0 196 C110 168 170 128 260 150 C340 170 400 116 500 124 C590 132 640 180 760 166 C860 154 930 112 1040 132 C1110 145 1160 166 1200 160 L1200 240 L0 240Z"
        fill="var(--color-ink)"
        opacity="0.08"
      />
      <path
        d="M0 222 C80 206 150 176 230 190 C300 202 350 168 430 174 C520 181 560 214 660 206 C760 198 820 160 920 178 C1010 194 1080 210 1200 200 L1200 240 L0 240Z"
        fill="var(--color-ink)"
        opacity="0.12"
      />
    </svg>
  )
}

/** 祥云纹（装饰用，低透明度）。 */
export function Cloud({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 120 60" className={className} aria-hidden fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <path d="M14 46 H94 a12 12 0 0 0 0-24 a16 16 0 0 0-30-6 a14 14 0 0 0-26 4 a10 10 0 0 0-10 10" />
      <path d="M38 30 a7 7 0 1 1 10 6" />
      <path d="M66 22 a8 8 0 1 1 11 7" />
      <path d="M22 46 a8 8 0 0 1 8-8 a5 5 0 1 1 4 5" />
      <path d="M100 46 h12" />
    </svg>
  )
}

/** 回纹分隔线。 */
export function FretDivider({ className }: { className?: string }) {
  const id = useId()
  return (
    <svg className={clsx('h-2 w-full text-line-2', className)} aria-hidden>
      <defs>
        <pattern id={id} width="16" height="8" patternUnits="userSpaceOnUse">
          <path d="M0 7.5 H4 V0.5 H12 V5 H8 V3 H6 V7.5 H16" fill="none" stroke="currentColor" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="100%" height="8" fill={`url(#${id})`} />
    </svg>
  )
}

/** 小标题前的菱形点缀。 */
export function Diamond({ className }: { className?: string }) {
  return <span aria-hidden className={clsx('inline-block size-1.5 rotate-45 bg-seal', className)} />
}
