import { type ReactNode } from 'react'
import { useTenant } from '@/contexts/TenantContext'
import { setSettingsStoreTenant } from '@/stores/settings'

interface SettingsStoreProviderProps {
  children: ReactNode
}

const SettingsStoreProvider = ({ children }: SettingsStoreProviderProps) => {
  const { selectedTenantId } = useTenant()

  setSettingsStoreTenant(selectedTenantId)

  return <>{children}</>
}

export default SettingsStoreProvider
