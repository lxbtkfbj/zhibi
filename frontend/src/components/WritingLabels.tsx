import clsx from 'clsx'
import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { TechniqueChip } from './TechniqueChip'

/** 同时支持鼠标悬停、键盘聚焦与触屏点击；浮层不受稿件卡片边界裁切。 */
export function WritingHint({ hint, label, children, className, style }: { hint: string; label?: string; children: ReactNode; className?: string; style?: CSSProperties }) {
  const id = useId()
  const ref = useRef<HTMLButtonElement>(null)
  const [position, setPosition] = useState<{ left: number; top?: number; bottom?: number } | null>(null)
  const show = () => {
    const rect = ref.current?.getBoundingClientRect()
    if (rect) setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - 300)), ...(rect.bottom > window.innerHeight - 160 ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }) })
  }
  useEffect(() => {
    if (!position) return
    const close = () => setPosition(null)
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
    const outside = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node)) close() }
    window.addEventListener('resize', close)
    window.addEventListener('scroll', close, true)
    document.addEventListener('keydown', escape)
    document.addEventListener('pointerdown', outside)
    return () => { window.removeEventListener('resize', close); window.removeEventListener('scroll', close, true); document.removeEventListener('keydown', escape); document.removeEventListener('pointerdown', outside) }
  }, [position])
  return <>
    <button ref={ref} type="button" style={style} className={clsx('focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-chief', className)} aria-label={label || hint} aria-describedby={position ? id : undefined} onMouseEnter={show} onMouseLeave={() => setPosition(null)} onFocus={show} onBlur={() => setPosition(null)} onClick={show}>{children}</button>
    {position && createPortal(<div id={id} role="tooltip" style={{ ...position, maxHeight: `calc(100vh - ${(position.top ?? position.bottom ?? 0) + 12}px)` }} className="pointer-events-none fixed z-[90] w-max max-w-[min(288px,calc(100vw-24px))] overflow-auto rounded-lg border border-line-2 bg-paper-2 px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap text-ink shadow-[var(--shadow-lift)]">{hint}</div>, document.body)}
  </>
}

export function RevealChips({ reveals }: { reveals?: { ref: string; to: string; how: string }[] }) {
  if (!reveals?.length) return null
  return <ul aria-label="揭晓安排" className="flex flex-wrap gap-1.5">{reveals.map((reveal, index) => <li key={`${reveal.ref}-${index}`}><WritingHint label={`揭晓 ${reveal.ref} → ${reveal.to}`} hint={`揭晓 ${reveal.ref} → ${reveal.to}：${reveal.how || '尚未说明揭晓方式'}`} className="rounded-full border border-lore/25 bg-lore-soft px-2.5 py-0.5 text-left text-xs text-lore">揭晓 {reveal.ref} → {reveal.to}</WritingHint></li>)}</ul>
}

export function EditorAnnotations({ note, techniques }: { note?: string; techniques?: string[] }) {
  if (!note && !techniques?.length) return null
  return <footer className="mt-4 space-y-2 border-t border-line pt-3">
    {note && <p className="text-xs leading-relaxed whitespace-pre-wrap text-ink-2"><span className="mr-2 text-chief">编辑批注</span>{note}</p>}
    {!!techniques?.length && <div aria-label="写作技巧" className="flex flex-wrap gap-1.5">{techniques.map(name => <TechniqueChip key={name} name={name} />)}</div>}
  </footer>
}
