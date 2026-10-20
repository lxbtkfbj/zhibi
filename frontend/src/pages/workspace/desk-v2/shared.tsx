/* oxlint-disable react/only-export-components -- Template primitives and their pure text helpers form one API. */
import { Fragment, type CSSProperties, type MouseEventHandler, type ReactNode, useLayoutEffect, useRef, useState } from 'react'

export function clean(value: unknown): string {
  return typeof value === 'string' && value !== '（记录里没有）' ? value : ''
}

export function Refs({ text }: { text: string }) {
  return <>{text.split(/(第\s?\d+(?:\s?[–-]\s?\d+)?\s?章)/g).map((part, i) => /^第\s?\d/.test(part) ? <span className="ref" key={i}>{part}</span> : part)}</>
}

export const TYPE_CLS: Record<string, string> = { 情感: 'ochre', 铺垫: 'plain', 平收: 'plain', 揭秘: 'jade', 拿到东西: 'jade', 突破: 'seal', 反转: 'seal', 打脸: 'seal', 智取: 'seal', 扮猪吃虎: 'seal', 心动: 'ochre', 悬念: 'indigo', 期待: 'indigo', 危机: 'indigo' }
export function Chip({ text }: { text: string }) { return text ? <span className={`chip ${TYPE_CLS[text] || 'plain'}`}>{text}</span> : null }

export function More<T>({ items, cap, children, unit = '条' }: { items: T[]; cap: number; unit?: string; children: (item: T, index: number) => ReactNode }) {
  const [expanded, setExpanded] = useState(false)
  return <>{items.slice(0, cap).map((item, i) => <Fragment key={i}>{children(item, i)}</Fragment>)}{items.length > cap && <>{!expanded && <div className="more" data-more onClick={e => { e.stopPropagation(); setExpanded(true) }}>还有 {items.length - cap} {unit}，展开</div>}<div className="rest" style={expanded ? { display: 'contents' } : undefined}>{items.slice(cap).map((item, i) => <Fragment key={i}>{children(item, i + cap)}</Fragment>)}</div></>}</>
}

export function Clamp({ children, lines = 4, as: Tag = 'p', className = '', style }: { children: ReactNode; lines?: number; as?: 'p' | 'div'; className?: string; style?: CSSProperties }) {
  const ref = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflow, setOverflow] = useState(false)
  useLayoutEffect(() => {
    // The sample adds an expand link on first overflow, before fonts settle;
    // it does not remove that link when a later font/layout pass fits exactly.
    const check = () => { if (ref.current && !expanded) setOverflow(previous => previous || !!ref.current && ref.current.scrollHeight > ref.current.clientHeight + 2) }
    check()
    void document.fonts.ready.then(check)
    const observer = new ResizeObserver(check)
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [children, expanded, lines])
  return <><Tag ref={ref} className={`${!expanded ? 'clampable' : ''}${className ? ` ${className}` : ''}`} style={{ '--lines': lines, ...style } as CSSProperties}>{children}</Tag>{!expanded && overflow && <span className="more" onClick={() => setExpanded(true)}>展开</span>}</>
}

export function Icon({ name, onClick }: { name: 'chev' | 'search' | 'save' | 'l' | 'r' | 'go' | 'settings'; onClick?: MouseEventHandler<SVGSVGElement> }) {
  return <svg onClick={onClick} className={`i${name === 'chev' ? ' chev' : ''}`} viewBox="0 0 24 24" style={name === 'go' ? { width: 13, height: 13 } : name === 'settings' ? { width: 19, height: 19 } : undefined}>
    {name === 'chev' && <path d="M6 9l6 6 6-6" />}
    {name === 'search' && <><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>}
    {name === 'save' && <><path d="M5 3h11l3 3v15H5z" /><path d="M8 3v5h7V3" /><path d="M8 21v-7h8v7" /></>}
    {name === 'l' && <path d="M15 18l-6-6 6-6" />}
    {name === 'r' && <path d="M9 18l6-6-6-6" />}
    {name === 'go' && <path d="M5 12h14M13 6l6 6-6 6" />}
    {name === 'settings' && <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></>}
  </svg>
}
