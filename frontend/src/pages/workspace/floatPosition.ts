/** 编辑部浮窗拖到哪：记在本机，换页面、换书再回来还在那儿。
 *  位置和拖的时候一样，用放大前的 CSS px；放回去时按当时的窗口夹在屏幕里。 */

export const FLOAT_KEY = 'zhibi:editorial-float'

export interface FloatPosition { x: number; y: number }

export function parseFloatPosition(raw: string | null): FloatPosition | null {
  try {
    const value: unknown = JSON.parse(raw ?? 'null')
    if (!value || typeof value !== 'object' || !('x' in value) || !('y' in value)) return null
    const { x, y } = value
    return typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null
  } catch { return null }
}

/** 夹在屏幕里：左右留 8px，上面让开顶栏，下面留 8px。box 是浮窗在屏幕上的宽高，zoom 是整页放大了几倍。 */
export function fitFloatPosition(pos: FloatPosition, box: { width: number; height: number }, view: { width: number; height: number }, zoom: number): FloatPosition {
  return {
    x: Math.min(Math.max(8, pos.x * zoom), view.width - box.width - 8) / zoom,
    y: Math.min(Math.max(64 * zoom, pos.y * zoom), view.height - box.height - 8) / zoom,
  }
}
