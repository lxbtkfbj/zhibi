/** 左边那一栏的宽度和整页放大倍数：几页共用。 */

import { createContext, useState } from 'react'

/** 这一块放大了几倍（大屏上整页等比放大、外观里调了界面大小）：屏幕上的坐标除以它，才是页面里的位置 */
export function zoomOf(el: Element | null): number {
  return (el as (Element & { currentCSSZoom?: number }) | null)?.currentCSSZoom ?? 1
}

export const COLUMN_KEY = 'zhibi:directory-width'
export const COLUMN_MIN = 220
export const COLUMN_MAX = 480

/** 左边那一栏多宽：作者拖右边缘调，记住上次的宽度；顶栏的四个入口跟着它对准中间那一栏。 */
export const ColumnWidthContext = createContext<{ width: number; setWidth: (width: number) => void }>({ width: 288, setWidth: () => {} })

export function useColumnWidth(): [number, (width: number) => void] {
  const [width, setWidth] = useState(() => {
    const fallback = window.matchMedia('(min-width: 1536px)').matches ? 320 : 288
    try {
      const saved = Number(localStorage.getItem(COLUMN_KEY))
      return saved >= COLUMN_MIN && saved <= COLUMN_MAX ? saved : fallback
    } catch {
      return fallback
    }
  })
  return [width, setWidth]
}
