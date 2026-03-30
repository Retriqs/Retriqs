import '@/lib/extensions'; // Import all global extensions
import { BrowserRouter as Router, Routes, Route, useNavigate, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useAuthStore } from '@/stores/state'
import { navigationService } from '@/services/navigation'
import { Toaster } from 'sonner'
import App from './App'
import BackendConnectPage from '@/features/BackendConnectPage'
import ThemeProvider from '@/components/ThemeProvider'

const AppContent = () => {
  const [initializing, setInitializing] = useState(true)
  const { isAuthenticated } = useAuthStore()
  const navigate = useNavigate()

  // Set navigate function for navigation service
  useEffect(() => {
    navigationService.setNavigate(navigate)
  }, [navigate])

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
