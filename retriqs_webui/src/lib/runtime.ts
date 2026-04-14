type DesktopRuntime = {
  backendBaseUrl: string
  desktop: boolean
}

const configuredBackendBaseUrl = (import.meta.env.VITE_BACKEND_URL || '').replace(/\/+$/, '')
const defaultDevBackendBaseUrl = import.meta.env.DEV ? 'http://127.0.0.1:9621' : ''

let runtime: DesktopRuntime = {
  backendBaseUrl: configuredBackendBaseUrl || defaultDevBackendBaseUrl,
  desktop: false
}

const isTauriEnvironment = () =>
  typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export const initializeRuntime = async (): Promise<void> => {
  if (!isTauriEnvironment()) {
    console.log('[runtime] Non-Tauri environment detected, using configured backend URL:', runtime.backendBaseUrl)
    return
  }

  try {
    const { invoke } = await import('@tauri-apps/api/core')
    const desktopRuntime = await invoke<DesktopRuntime>('get_backend_runtime')
    runtime = desktopRuntime
    console.log('[runtime] Initialized desktop runtime:', desktopRuntime)
  } catch (error) {
    console.error('Failed to initialize desktop runtime, falling back to env config.', error)
    console.log('[runtime] Fallback backend URL:', runtime.backendBaseUrl)
  }
}

export const getBackendBaseUrl = (): string => runtime.backendBaseUrl

export const isDesktopRuntime = (): boolean => runtime.desktop

export const openExternalUrl = async (url: string): Promise<void> => {
  if (isDesktopRuntime()) {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_external_url', { url })
    return
  }

  const openedWindow = window.open(url, '_blank', 'noopener,noreferrer')
  if (!openedWindow) {
    throw new Error('Browser popup was blocked')
  }
}
