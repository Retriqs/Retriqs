import '@/lib/extensions'; // Import all global extensions
import { BrowserRouter as Router, Routes, Route, useNavigate, Navigate } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/stores/state'
import { navigationService } from '@/services/navigation'
import { Toaster } from 'sonner'
import {
  METRICS_EMAIL_STORAGE_KEY,
  getOrCreateAnalyticsInstallId,
  identifyAnalyticsUser,
  resetAnalytics,
  trackEvent
} from '@/lib/analytics'
import App from './App'
import BackendConnectPage from '@/features/BackendConnectPage'

const AppContent = () => {
  const [initializing, setInitializing] = useState(true)
  const { isAuthenticated, username, isGuestMode } = useAuthStore()
  const navigate = useNavigate()
  const appOpenTrackedRef = useRef(false)

  // Set navigate function for navigation service
  useEffect(() => {
    navigationService.setNavigate(navigate)
  }, [navigate])

  useEffect(() => {
    if (appOpenTrackedRef.current) {
      return
    }

    appOpenTrackedRef.current = true
    trackEvent('app_open')
  }, [])

  // Token validity check
  useEffect(() => {

    const checkAuth = async () => {
      try {
      const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
        console.log('[router] Initial auth check:', {
          hasToken: Boolean(token),
          isAuthenticated
        })

        if (token && isAuthenticated) {
          console.log('[router] Existing token and authenticated state found, skipping login redirect')
          setInitializing(false);
          return;
        }

        if (!token) {
          console.log('[router] No token found, clearing auth state')
          useAuthStore.getState().logout()
        }
      } catch (error) {
        console.error('Auth initialization error:', error)
        if (!isAuthenticated) {
          useAuthStore.getState().logout()
        }
      } finally {
        setInitializing(false)
      }
    }

    checkAuth()

    return () => {
    }
  }, [isAuthenticated])

  // Redirect effect for protected routes
  useEffect(() => {
    if (!initializing && !isAuthenticated) {
      const currentPath = window.location.pathname
      if (currentPath !== '/connect') {
        console.log('[router] Not authenticated after init, redirecting to connect from:', currentPath)
        navigate('/connect')
      }
    }
  }, [initializing, isAuthenticated, navigate])

  useEffect(() => {
    if (!initializing && isAuthenticated) {
      const storedMetricsEmail = localStorage.getItem(METRICS_EMAIL_STORAGE_KEY)
      identifyAnalyticsUser(getOrCreateAnalyticsInstallId(), {
        is_guest_mode: isGuestMode,
        username: username || undefined,
        email: storedMetricsEmail || undefined,
        contact_provided: Boolean(storedMetricsEmail)
      })
    }

    if (!initializing && !isAuthenticated) {
      resetAnalytics()
    }
  }, [initializing, isAuthenticated, isGuestMode, username])

  // Show nothing while initializing
  if (initializing) {
    return null
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/connect" replace />} />
      <Route path="/connect" element={<BackendConnectPage />} />
      <Route
        path="/"
        element={
          isAuthenticated ? <Navigate to="/documents" replace /> : <Navigate to="/connect" replace />
        }
      />
      <Route
        path="/*"
        element={isAuthenticated ? <App /> : <Navigate to="/connect" replace />}
      />
    </Routes>
  )
}

const AppRouter = () => {
  return (
    <Router>
      <AppContent />
      <Toaster
        position="bottom-center"
        theme="system"
        closeButton
        richColors
      />
    </Router>
  )
}

export default AppRouter
