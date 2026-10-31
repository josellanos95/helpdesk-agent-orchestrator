import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { readStored, writeStored } from './storage'

export type ThemeChoice = 'system' | 'light' | 'dark'
const KEY = 'triagent.theme'

function apply(choice: ThemeChoice) {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
}

type ThemeContext = { theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void }
const Context = createContext<ThemeContext | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(() => {
    const stored = readStored(KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  })

  useEffect(() => apply(theme), [theme])

  const setTheme = useCallback((next: ThemeChoice) => {
    setThemeState(next)
    writeStored(KEY, next === 'system' ? null : next)
  }, [])
  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme])
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useTheme(): ThemeContext {
  const value = useContext(Context)
  if (!value) throw new Error('useTheme needs a ThemeProvider')
  return value
}
