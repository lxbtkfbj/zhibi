/* oxlint-disable react/only-export-components -- Provider and its public hooks form one appearance API. */
import { MotionConfig, useReducedMotion as useSystemReducedMotion } from 'motion/react'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export interface Appearance {
  theme: 'paper' | 'ink' | 'system'
  font: 'song' | 'kai' | 'hei'
  readingSize: number
  readingLeading: 'compact' | 'standard' | 'relaxed'
  uiScale: 'standard' | 'large'
  reducedMotion: boolean
}
const defaults: Appearance = { theme: 'paper', font: 'song', readingSize: 17, readingLeading: 'standard', uiScale: 'standard', reducedMotion: false }
const KEY = 'zhibi:appearance'
function saved(): Appearance {
  try {
    const a = JSON.parse(localStorage.getItem(KEY) ?? '{}')
    return {
      theme: ['paper', 'ink', 'system'].includes(a.theme) ? a.theme : defaults.theme,
      font: ['song', 'kai', 'hei'].includes(a.font) ? a.font : defaults.font,
      readingSize: Number.isInteger(a.readingSize) && a.readingSize >= 15 && a.readingSize <= 20 ? a.readingSize : 17,
      readingLeading: ['compact', 'standard', 'relaxed'].includes(a.readingLeading) ? a.readingLeading : defaults.readingLeading,
      uiScale: a.uiScale === 'large' ? 'large' : 'standard', reducedMotion: a.reducedMotion === true,
    }
  } catch { return defaults }
}
const AppearanceContext = createContext({ appearance: defaults, setAppearance: (_patch: Partial<Appearance>) => {} })

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setValue] = useState(saved)
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const root = document.documentElement
      root.dataset.theme = appearance.theme === 'system' ? (media.matches ? 'ink' : 'paper') : appearance.theme
      root.dataset.font = appearance.font
      root.dataset.reducedMotion = String(appearance.reducedMotion)
      root.style.setProperty('--reading-size', `${appearance.readingSize}px`)
      root.style.setProperty('--reading-leading', String({ compact: 1.65, standard: 2, relaxed: 2.35 }[appearance.readingLeading]))
      root.style.setProperty('--ui-scale', appearance.uiScale === 'large' ? '1.12' : '1')
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [appearance])
  useEffect(() => {
    const sync = (event: StorageEvent) => { if (event.key === KEY) setValue(saved()) }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])
  const setAppearance = (patch: Partial<Appearance>) => setValue(old => {
    const next = { ...old, ...patch }
    try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* Private browsing: preferences still apply this session. */ }
    return next
  })
  return <AppearanceContext.Provider value={{ appearance, setAppearance }}>
    <MotionConfig reducedMotion={appearance.reducedMotion ? 'always' : 'user'}>{children}</MotionConfig>
  </AppearanceContext.Provider>
}
export const useAppearance = () => useContext(AppearanceContext)
/** Motion's hook only reads the OS preference; also honor the author's explicit setting. */
export function useReducedMotion() {
  const { appearance } = useAppearance()
  const system = useSystemReducedMotion()
  return appearance.reducedMotion || !!system
}
