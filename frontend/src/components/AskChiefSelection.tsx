import { useEffect, useRef, useState, type ReactNode } from 'react'
import { selectedTextRange } from '../lib/textSelection'
import { useBookContext } from '../pages/book/context'
import { Button } from './ui'

export function AskChiefSelection({ where, children }: { where: string; children: ReactNode }) {
  const { askChief } = useBookContext()
  const root = useRef<HTMLDivElement>(null)
  const [text, setText] = useState('')
  useEffect(() => { const select = () => { const selection = window.getSelection(); setText(root.current && selectedTextRange(root.current, selection) ? selection?.toString() ?? '' : '') }; document.addEventListener('selectionchange', select); return () => document.removeEventListener('selectionchange', select) }, [])
  return <div><div ref={root} className="select-text">{children}</div>{text && <div className="sticky bottom-2 w-fit rounded-lg border border-line bg-card shadow"><Button size="sm" variant="ghost" onPointerDown={event => event.preventDefault()} onClick={() => { askChief({ text, where }); window.getSelection()?.removeAllRanges(); setText('') }}>问问主编</Button></div>}</div>
}
