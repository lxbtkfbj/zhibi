import { Fragment, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'

function markup(text: string, refs: boolean): string {
  const safe = text.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)
  return refs ? safe.replace(/第\s?\d+(?:\s?[–-]\s?\d+)?\s?章/g, match => `<span class="ref">${match}</span>`) : safe
}

/** 原生标签上直接手改：不额外包 div，不把样张的 p、b、h1 改成旧编辑器布局。 */
export function DeskEdit({ as = 'div', value, onSave, className, style, placeholder, spot, lines, refs = false, fresh = false }: {
  as?: 'h1' | 'h2' | 'p' | 'div' | 'b' | 'span'
  value: string
  onSave?: (value: string) => void
  className?: string
  style?: CSSProperties
  placeholder?: string
  spot?: string
  lines?: number
  refs?: boolean
  fresh?: boolean
}) {
  const ref = useRef<HTMLElement>(null)
  const saved = useRef(value)
  const [expanded, setExpanded] = useState(false)
  const [overflow, setOverflow] = useState(false)
  useLayoutEffect(() => {
    const element = ref.current
    saved.current = value
    if (element && document.activeElement !== element) element.innerHTML = markup(value, refs)
  }, [value, refs])
  useLayoutEffect(() => {
    const element = ref.current
    if (!element || !lines) return
    let frame = 0
    const measure = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const line = parseFloat(getComputedStyle(element).lineHeight) || 24
        setOverflow(element.scrollHeight > line * lines + 1)
      })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    void document.fonts?.ready.then(measure)
    return () => { observer.disconnect(); cancelAnimationFrame(frame) }
  }, [value, lines])
  useLayoutEffect(() => { if (fresh) ref.current?.focus() }, [fresh])
  const Tag = as
  const properties = {
    className: [className, lines ? 'clampable' : ''].filter(Boolean).join(' ') || undefined,
    style: { ...style, outline: 'none', ...(lines ? { '--lines': lines, ...(expanded ? { WebkitLineClamp: 'unset' } : {}) } : {}) } as CSSProperties,
    contentEditable: onSave ? 'plaintext-only' as const : false,
    suppressContentEditableWarning: true,
    spellCheck: false,
    'data-spot': spot,
    'data-placeholder': placeholder,
    'data-desk-edit': onSave ? '' : undefined,
    role: onSave ? 'textbox' : undefined,
    'aria-label': onSave ? placeholder : undefined,
    onFocus: () => { if (lines && onSave) setExpanded(true) },
    onBlur: () => {
      const text = (ref.current?.innerText ?? '').replace(/\r/g, '').replace(/\u00a0/g, ' ').replace(/\n+$/, '')
      if (onSave && text !== saved.current) { saved.current = text; onSave(text) }
    },
    onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
      if (event.key === 'Escape') {
        event.currentTarget.innerHTML = markup(saved.current, refs)
        event.currentTarget.blur()
      } else if (event.key === 'Enter' && !['p', 'div'].includes(as) && !event.nativeEvent.isComposing) {
        event.preventDefault()
        event.currentTarget.blur()
      }
    },
  }
  const tag = <Tag {...properties} ref={(node: HTMLElement | null) => { ref.current = node }} />
  return <Fragment>{tag}{lines && overflow && !expanded && <div className="more" onClick={() => setExpanded(true)}>展开</div>}</Fragment>
}
