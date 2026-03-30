import React, { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react'
import { GraphStorage, getGraphStorages, waitForBackendHealth } from '@/api/retriqs'
import { toast } from 'sonner'

interface TenantContextType {
    selectedTenantId: number | null
    tenants: GraphStorage[]
    isLoading: boolean
    setSelectedTenant: (id: number) => void
    loadTenants: () => Promise<void>
}

const TenantContext = createContext<TenantContextType | undefined>(undefined)

export const useTenant = () => {
    const context = useContext(TenantContext)
    if (!context) {
        throw new Error('useTenant must be used within a TenantProvider')
    }
    return context
}

interface TenantProviderProps {
    children: ReactNode
}

export const TenantProvider: React.FC<TenantProviderProps> = ({ children }) => {
    const [selectedTenantId, setSelectedTenantId] = useState<number | null>(null)
    const [tenants, setTenants] = useState<GraphStorage[]>([])
    const [isLoading, setIsLoading] = useState(true)

    const loadTenants = useCallback(async () => {
        setIsLoading(true)
        try {
            await waitForBackendHealth()
            const fetchedTenants = await getGraphStorages()
            setTenants(fetchedTenants)

            // Auto-select first tenant if available and none selected
            if (fetchedTenants.length > 0 && selectedTenantId === null) {
                setSelectedTenantId(fetchedTenants[0].id)
            }
        } catch (error) {
            console.error('Failed to load tenants:', error)
            toast.error('Failed to load tenants')
        } finally {
            setIsLoading(false)
        }
    }, [selectedTenantId])

    const setSelectedTenant = useCallback((id: number) => {
        setSelectedTenantId(id)
    }, [])

    useEffect(() => {
        loadTenants()
    }, [])

    return (
        <TenantContext.Provider
            value={{
                selectedTenantId,
                tenants,
                isLoading,
                setSelectedTenant,
                loadTenants
            }}
        >
            {children}
        </TenantContext.Provider>
    )
}
