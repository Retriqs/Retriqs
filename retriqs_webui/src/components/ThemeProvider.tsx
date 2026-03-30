import { createContext, useEffect, useMemo, useState } from 'react'
import { Theme, useSettingsStore } from '@/stores/settings'

type ThemeProviderProps = {
  children: React.ReactNode
}

type ThemeProviderState = {
  theme: Theme
  setTheme: (theme: Theme) => void
}

const initialState: ThemeProviderState = {
  theme: 'system',
  setTheme: () => null
}

const ThemeProviderContext = createContext<ThemeProviderState>(initialState)
const THEME_STORAGE_KEY = 'settings-global'
const THEME_EVENT = 'retriqs-theme-change'

const readStoredTheme = (): Theme => {
  if (typeof localStorage === 'undefined') return 'system'

  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY)
    if (!raw) return 'system'

    const parsed = JSON.parse(raw) as { state?: { theme?: Theme } }
    return parsed.state?.theme ?? 'system'
  } catch {
    return 'system'
  }
}

const writeStoredTheme = (theme: Theme) => {
  if (typeof localStorage === 'undefined') return

  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) as { state?: Record<string, unknown> } : {}

    localStorage.setItem(
      THEME_STORAGE_KEY,
      JSON.stringify({
        ...parsed,
        state: {
          ...parsed.state,
          theme
        }
      })
    )
  } catch {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ state: { theme } }))
  }
}

/**
 * Component that provides the theme state and setter function to its children.
 */
export default function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme())

  const setTheme = (nextTheme: Theme) => {
    writeStoredTheme(nextTheme)
    setThemeState(nextTheme)
    useSettingsStore.getState().setTheme(nextTheme)
    window.dispatchEvent(new CustomEvent<Theme>(THEME_EVENT, { detail: nextTheme }))
  }

  useEffect(() => {
    const handleThemeChange = (event: Event) => {
      const customEvent = event as CustomEvent<Theme>
      setThemeState(customEvent.detail ?? readStoredTheme())
    }

    window.addEventListener(THEME_EVENT, handleThemeChange)
    return () => window.removeEventListener(THEME_EVENT, handleThemeChange)
  }, [])

  useEffect(() => {
    const root = window.document.documentElement
    root.classList.remove('light', 'dark')

    if (theme === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
      const handleChange = (e: MediaQueryListEvent) => {
        root.classList.remove('light', 'dark')
        root.classList.add(e.matches ? 'dark' : 'light')
      }

      root.classList.add(mediaQuery.matches ? 'dark' : 'light')
      mediaQuery.addEventListener('change', handleChange)

      return () => mediaQuery.removeEventListener('change', handleChange)
    } else {
      root.classList.add(theme)
    }
  }, [theme])

  const value = useMemo(() => ({
    theme,
    setTheme
  }), [theme])

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

export { ThemeProviderContext }
