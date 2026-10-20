import { type ReactNode, useLayoutEffect, useRef } from 'react'
import { BALL_KEY, ballDragPosition, ballDropPosition, ballPlacement, isBallDrag, parseBallPosition } from './ballPosition'

export function DraggableBall({ onClick, children = '编', title = '编辑部' }: { onClick: () => void; children?: ReactNode; title?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const start = useRef<{ x: number; y: number; rect: DOMRect } | null>(null)
  const moved = useRef(false)

  useLayoutEffect(() => {
    const ball = ref.current!
    const zoom = () => Number(getComputedStyle(ball.closest('.desk-v2') ?? ball).zoom || 1)
    const restore = () => {
      let pos = null
      try { pos = parseBallPosition(localStorage.getItem(BALL_KEY)) } catch { /* Storage unavailable: retain the default right/bottom position. */ }
      if (pos) Object.assign(ball.style, ballPlacement(pos, innerHeight, zoom(), ball.offsetHeight))
      else for (const property of ['left', 'right', 'top', 'bottom']) ball.style.removeProperty(property)
    }
    restore()
    window.addEventListener('resize', restore)
    // fit and the existing appearance control set zoom through root variables.
    // Reposition after either changes, not just after a viewport resize.
    const observer = new MutationObserver(() => { if (!start.current) restore() })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['style'] })
    return () => { window.removeEventListener('resize', restore); observer.disconnect() }
  }, [])

  const zoom = () => Number(getComputedStyle(ref.current!.closest('.desk-v2') ?? ref.current!).zoom || 1)
  return <div ref={ref} role="button" tabIndex={0} title={title} className="ball"
    onPointerDown={event => {
      start.current = { x: event.clientX, y: event.clientY, rect: event.currentTarget.getBoundingClientRect() }
      moved.current = false
      event.currentTarget.setPointerCapture(event.pointerId)
    }}
    onPointerMove={event => {
      if (!start.current) return
      const dx = event.clientX - start.current.x, dy = event.clientY - start.current.y
      if (!moved.current && !isBallDrag(dx, dy)) return
      moved.current = true
      event.currentTarget.classList.add('dragging')
      Object.assign(event.currentTarget.style, ballDragPosition(start.current.rect, dx, dy, zoom()))
    }}
    onPointerUp={event => {
      if (!start.current) return
      const rect = event.currentTarget.getBoundingClientRect()
      start.current = null
      event.currentTarget.classList.remove('dragging')
      if (!moved.current) return
      const pos = ballDropPosition(rect, innerWidth, innerHeight, zoom())
      Object.assign(event.currentTarget.style, ballPlacement(pos, innerHeight, zoom(), event.currentTarget.offsetHeight))
      try { localStorage.setItem(BALL_KEY, JSON.stringify(pos)) } catch { /* Store failure does not prevent this drag. */ }
    }}
    onPointerCancel={event => {
      start.current = null
      moved.current = true
      event.currentTarget.classList.remove('dragging')
    }}
    onClick={event => { if (moved.current) { event.preventDefault(); event.stopPropagation(); return } onClick() }}
    onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick() } }}
  >{children}</div>
}
