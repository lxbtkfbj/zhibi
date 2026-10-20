export const BALL_KEY = 'zhibi.ball'
export const BALL_GAP = 24
export const BALL_EDGE = 16
export const BALL_TOP = 54

export interface BallPosition { side: 'left' | 'right'; top: number }
export interface BallRect { left: number; top: number; width: number }

export function parseBallPosition(raw: string | null): BallPosition | null {
  try {
    const value: unknown = JSON.parse(raw ?? 'null')
    if (!value || typeof value !== 'object' || !('side' in value) || !('top' in value)) return null
    return (value.side === 'left' || value.side === 'right') && typeof value.top === 'number' && Number.isFinite(value.top)
      ? { side: value.side, top: value.top } : null
  } catch { return null }
}

/** 与样张 place() 一样，位置用放大前的 CSS px，top 存窗口高度比例。 */
export function ballPlacement(position: BallPosition, height: number, zoom: number, size: number) {
  const h = height / zoom
  return {
    top: `${Math.min(Math.max(BALL_TOP + BALL_EDGE, position.top * h), h - size - BALL_EDGE)}px`,
    bottom: 'auto',
    left: position.side === 'left' ? `${BALL_GAP}px` : 'auto',
    right: position.side === 'left' ? 'auto' : `${BALL_GAP}px`,
  }
}

export function ballDropPosition(rect: BallRect, width: number, height: number, zoom: number): BallPosition {
  return { side: rect.left + rect.width / 2 < width / 2 ? 'left' : 'right', top: (rect.top / zoom) / (height / zoom) }
}

export function ballDragPosition(rect: BallRect, dx: number, dy: number, zoom: number) {
  return { left: `${(rect.left + dx) / zoom}px`, top: `${(rect.top + dy) / zoom}px`, right: 'auto', bottom: 'auto' }
}

export const isBallDrag = (dx: number, dy: number) => Math.hypot(dx, dy) >= 4
