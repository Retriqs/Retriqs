import { useState, useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import ThemeProvider from '@/components/ThemeProvider'
import TabVisibilityProvider from '@/contexts/TabVisibilityProvider'
import { TenantProvider, useTenant } from '@/contexts/TenantContext'
import SettingsStoreProvider from '@/contexts/SettingsStoreProvider'
import ApiKeyAlert from '@/components/ApiKeyAlert'
import { SiteInfo, webuiPrefix } from '@/lib/constants'
import { useBackendState, useAuthStore } from '@/stores/state'
import { useSettingsStore } from '@/stores/settings'
import { getAuthStatus } from '@/api/retriqs'
import SiteHeader from '@/features/SiteHeader'
import { InvalidApiKeyError, RequireApiKeError } from '@/api/retriqs'

import GraphViewer from '@/features/GraphViewer'
import DocumentManager from '@/features/DocumentManager'
import SettingsPage from './features/SettingsPage'
import RetrievalTesting from '@/features/RetrievalTesting'
import ApiSite from '@/features/ApiSite'
import FeedbackPage from '@/features/FeedbackPage'
import MarketplacePage from './features/MarketplacePage'
import { WelcomeOverlay } from '@/components/WelcomeOverlay'
import { FloatingFeedback } from '@/components/FloatingFeedback'

import { Tabs, TabsContent } from '@/components/ui/Tabs'

// Inner component that consumes TenantContext
function AppContent() {
  const message = useBackendState.use.message()
  const backendStatus = useBackendState.use.status()
  const enableHealthCheck = useSettingsStore.use.enableHealthCheck()
  const currentTab = useSettingsStore.use.currentTab()
  const { tenants, isLoading: isTenantsLoading, selectedTenantId } = useTenant()
  const [apiKeyAlertOpen, setApiKeyAlertOpen] = useState(false)
  const [initializing, setInitializing] = useState(true) // Add initializing state
  const versionCheckRef = useRef(false) // Prevent duplicate calls in Vite dev mode
  const healthCheckInitializedRef = useRef(false) // Prevent duplicate health checks in Vite dev mode

  const handleApiKeyAlertOpenChange = useCallback((open: boolean) => {
    setApiKeyAlertOpen(open)
    if (!open) {
      useBackendState.getState().clear()
    }
  }, [])

  // Track component mount status with useRef
  const isMountedRef = useRef(true)

  // Set up mount/unmount status tracking
  useEffect(() => {
    isMountedRef.current = true

    // Handle page reload/unload
    const handleBeforeUnload = () => {
      isMountedRef.current = false
    }

    window.addEventListener('beforeunload', handleBeforeUnload)

    return () => {
      isMountedRef.current = false
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [])

  // Health check - can be disabled
  useEffect(() => {
    // Health check function
    const performHealthCheck = async () => {
      try {
        // Only perform health check if component is still mounted
        if (isMountedRef.current) {
          await useBackendState.getState().check()
        }
      } catch (error) {
        console.error('Health check error:', error)
      }
    }

    // Set health check function in the store
    useBackendState.getState().setHealthCheckFunction(performHealthCheck)

    if (!enableHealthCheck || apiKeyAlertOpen) {
      useBackendState.getState().clearHealthCheckTimer()
      return
    }

    // On first mount or when enableHealthCheck becomes true and apiKeyAlertOpen is false,
    // perform an immediate health check and start the timer
    if (!healthCheckInitializedRef.current) {
      healthCheckInitializedRef.current = true
    }

    // Start/reset the health check timer using the store
    useBackendState.getState().resetHealthCheckTimer()

    // Component unmount cleanup
    return () => {
      useBackendState.getState().clearHealthCheckTimer()
    }
  }, [enableHealthCheck, apiKeyAlertOpen])

  // Version check - independent and executed only once
  useEffect(() => {
    const checkVersion = async () => {
      // Prevent duplicate calls in Vite dev mode
      if (versionCheckRef.current) return
      versionCheckRef.current = true

      // Check if version info was already obtained in login page
      const versionCheckedFromLogin =
        sessionStorage.getItem('VERSION_CHECKED_FROM_LOGIN') === 'true'
      if (versionCheckedFromLogin) {
        setInitializing(false) // Skip initialization if already checked
        return
      }

      try {
        setInitializing(true) // Start initialization

        // Get version info
        const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
        const status = await getAuthStatus()

        // If auth is not configured and a new token is returned, use the new token
        if (!status.auth_configured && status.access_token) {
          useAuthStore.getState().login(
            status.access_token, // Use the new token
            true, // Guest mode
            status.core_version,
            status.api_version,
            status.webui_title || null,
            status.webui_description || null
          )
        } else if (
          token &&
          (status.core_version ||
            status.api_version ||
            status.webui_title ||
            status.webui_description)
        ) {
          // Otherwise use the old token (if it exists)
          const isGuestMode = status.auth_mode === 'disabled' || useAuthStore.getState().isGuestMode
          useAuthStore
            .getState()
            .login(
              token,
              isGuestMode,
              status.core_version,
              status.api_version,
              status.webui_title || null,
              status.webui_description || null
            )
        }

        // Set flag to indicate version info has been checked
        sessionStorage.setItem('VERSION_CHECKED_FROM_LOGIN', 'true')
      } catch (error) {
        console.error('Failed to get version info:', error)
      } finally {
        // Ensure initializing is set to false even if there's an error
        setInitializing(false)
      }
    }

    // Execute version check
    checkVersion()
  }, []) // Empty dependency array ensures it only runs once on mount

  const { pathname } = useLocation()
  const navigate = useNavigate()
  const isMarketplaceRoute = pathname === '/marketplace'

  // Sync tab with URL
  useEffect(() => {
    const tabName = pathname.slice(1) // Get tab name from path
    if (tabName && tabName !== currentTab) {
      // Validate tab name
      const validTabs = ['documents', 'knowledge-graph', 'retrieval', 'api', 'settings', 'marketplace', 'feedback']
      if (validTabs.includes(tabName)) {
        useSettingsStore.getState().setCurrentTab(tabName as any)
      }
    }
  }, [pathname, currentTab])


  const handleTabChange = useCallback(
    (tab: string) => navigate(`/${tab}`),
    [navigate]
  )

  useEffect(() => {
    if (message) {
      if (message.includes(InvalidApiKeyError) || message.includes(RequireApiKeError)) {
        setApiKeyAlertOpen(true)
      }
    }
  }, [message])

  const backendReady = backendStatus?.status === 'healthy'
  const backendStarting =
    enableHealthCheck &&
    (!backendStatus ||
      backendStatus.status === 'starting' ||
      backendStatus.status === 'stopping')


  return (
    <>
      {initializing || backendStarting ? (
        // Loading state while initializing with simplified header
        <div className="flex h-screen w-screen flex-col">
          {/* Simplified header during initialization - matches SiteHeader structure */}
          <header className="border-border/40 bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-50 flex h-10 w-full border-b px-4 backdrop-blur">
            <div className="flex w-auto min-w-[200px] items-center">
              <a href={webuiPrefix} className="flex items-center gap-2">
                <img src={`${webuiPrefix}Logo.png`} alt="Logo" className="size-6" />
                <span className="font-bold md:inline-block">{SiteInfo.name}</span>
              </a>
            </div>

            {/* Empty middle section to maintain layout */}
            <div className="flex h-10 flex-1 items-center justify-center"></div>

            {/* Empty right section to maintain layout */}
            <nav className="flex w-[200px] items-center justify-end"></nav>
          </header>

          {/* Loading indicator in content area */}
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <div className="border-primary mx-auto mb-2 h-8 w-8 animate-spin rounded-full border-4 border-t-transparent"></div>
              <p>{backendStatus?.message || 'Initializing...'}</p>
            </div>
          </div>
        </div>
      ) : (
        // Main content after initialization
        <>
          {/* Show welcome overlay when no tenants exist */}
          {!isTenantsLoading && backendReady && tenants.length === 0 && !isMarketplaceRoute && <WelcomeOverlay />}

          <main className="premium-bg flex h-screen w-screen overflow-hidden">
            <Tabs
              key={selectedTenantId ?? 'default'}
              value={currentTab}
              className="!m-0 flex grow flex-col overflow-hidden !p-0"
              onValueChange={handleTabChange}
            >
              <SiteHeader />
              <div className="relative grow">
                <TabsContent
                  value="documents"
                  className="absolute top-0 right-0 bottom-0 left-0 overflow-auto"
                >
                  <DocumentManager />
                </TabsContent>
                <TabsContent
                  value="knowledge-graph"
                  className="absolute top-0 right-0 bottom-0 left-0 overflow-hidden"
                >
                  <GraphViewer />
                </TabsContent>
                <TabsContent
                  value="retrieval"
                  className="absolute top-0 right-0 bottom-0 left-0 overflow-hidden"
                >
                  <RetrievalTesting />
                </TabsContent>
                <TabsContent
                  value="api"
                  className="absolute top-0 right-0 bottom-0 left-0 overflow-hidden"
                >
                  <ApiSite />
                </TabsContent>
                <TabsContent
                  value="settings"
                  className="absolute top-0 right-0 bottom-0 left-0 overflow-hidden"
                >
                  <SettingsPage />
                </TabsContent>
                <TabsContent
                  value="marketplace"
                  className="absolute top-0 right-0 bottom-0 left-0 overflow-hidden"
                >
                  <MarketplacePage />
                </TabsContent>
                <TabsContent
                  value="feedback"
                  className="absolute top-0 right-0 bottom-0 left-0 overflow-hidden"
                >
                  <FeedbackPage />
                </TabsContent>
              </div>
            </Tabs>
            {/* {enableHealthCheck && <StatusIndicator />} */}
            <ApiKeyAlert open={apiKeyAlertOpen} onOpenChange={handleApiKeyAlertOpenChange} />
            <FloatingFeedback />
          </main>
        </>
      )}
    </>
  )
}

// Wrapper component that provides TenantContext
function App() {
  return (
    <TenantProvider>
      <SettingsStoreProvider>
        <ThemeProvider>
          <TabVisibilityProvider>
            <AppContent />
          </TabVisibilityProvider>
        </ThemeProvider>
      </SettingsStoreProvider>
    </TenantProvider>
  )
}

export default App

