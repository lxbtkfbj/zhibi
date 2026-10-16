import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useGlossary } from '../api/hooks'

/** 术语只解释，不把未知的模型词语伪装成已登记技巧。 */
export function TechniqueChip({ name }: { name: string }) {
  const { data } = useGlossary()
  const term = data?.terms.find(item => item.term === name)
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  const id = useId()
  useEffect(() => {
    if (!position) return
    const close = () => { setPosition(null); trigger.current?.focus() }
    const keydown = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); close() } }
    const pointerdown = (event: PointerEvent) => { if (!popup.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setPosition(null) }
    document.addEventListener('keydown', keydown)
    document.addEventListener('pointerdown', pointerdown)
    window.addEventListener('resize', close)
    return () => { document.removeEventListener('keydown', keydown); document.removeEventListener('pointerdown', pointerdown); window.removeEventListener('resize', close) }
  }, [position])
  if (!term) return <span className="text-xs text-ink-2">{name}</span>
  return <>
    <button ref={trigger} type="button" aria-haspopup="dialog" aria-expanded={!!position} aria-controls={position ? id : undefined} onClick={() => {
      if (position) { setPosition(null); return }
      const rect = trigger.current!.getBoundingClientRect()
      setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - 300)), top: Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - 210)) })
    }} className="rounded-full border border-chief/30 px-2 py-0.5 text-xs text-chief transition-colors hover:bg-chief-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-chief">{name}</button>
    {position && createPortal(<div ref={popup} id={id} role="dialog" aria-label={`${name}：技巧说明`} style={position} className="fixed z-[80] max-h-[190px] w-72 overflow-auto rounded-xl border border-line-2 bg-paper-2 p-4 shadow-[var(--shadow-lift)]">
      <p className="mb-2 font-serif text-base font-bold text-ink">{term.term}</p>
      <p className="text-sm leading-relaxed text-ink-2">{term.explanation}</p>
      <button type="button" onClick={() => { setPosition(null); trigger.current?.focus() }} className="mt-3 text-xs text-chief underline underline-offset-4">关闭说明</button>
    </div>, document.body)}
  </>
}
