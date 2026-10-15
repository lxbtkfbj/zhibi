/* oxlint-disable react/only-export-components -- Provider and its public opener are one API. */
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { Outlet } from 'react-router-dom'
import { SettingsModal } from '../pages/SettingsPage'

const SettingsContext = createContext({ openSettings: () => {} })
export const useSettingsModal = () => useContext(SettingsContext)
export function SettingsHost({ children }: { children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const openSettings = useCallback(() => setOpen(true), [])
  const closeSettings = useCallback(() => setOpen(false), [])
  return <SettingsContext.Provider value={{ openSettings }}>
    {children ?? <Outlet />}
    <SettingsModal open={open} onClose={closeSettings} />
  </SettingsContext.Provider>
}
