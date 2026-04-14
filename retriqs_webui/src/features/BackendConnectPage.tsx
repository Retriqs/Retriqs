import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ZapIcon, RefreshCwIcon, ServerCrashIcon } from 'lucide-react'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import { getAuthStatus, waitForBackendHealth } from '@/api/retriqs'
import { useAuthStore } from '@/stores/state'
import { trackEvent } from '@/lib/analytics'

const BackendConnectPage = () => {
  const navigate = useNavigate()
  const { login } = useAuthStore()
  const [connecting, setConnecting] = useState(false)
  const [statusMessage, setStatusMessage] = useState(
    'Waiting for the bundled backend to report healthy status.'
  )
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const attemptedInitialConnectRef = useRef(false)

  const handleReconnect = async () => {
    setConnecting(true)
    setErrorMessage(null)
    setStatusMessage('Checking backend health...')
    try {
      await waitForBackendHealth()

      setStatusMessage('Backend is healthy. Loading desktop session...')
      const status = await getAuthStatus()
      console.log('[connect] Auth status after backend health check:', status)

      if (!status.auth_configured && status.access_token) {
        trackEvent('backend_connect_succeeded', {
          auth_configured: status.auth_configured,
          has_access_token: Boolean(status.access_token)
        })
        login(
          status.access_token,
          true,
          status.core_version,
          status.api_version,
          status.webui_title || null,
          status.webui_description || null
        )
        navigate('/')
        return
      }

      const message =
        'Backend is reachable, but desktop startup did not receive a guest token from /auth-status.'
      trackEvent('backend_connect_failed', {
        error_code: 'missing_guest_token'
      })
      setErrorMessage(message)
      toast.error(message)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to connect to backend'
      console.error('[connect] Backend reconnect failed:', error)
      trackEvent('backend_connect_failed', {
        error_code: 'health_check_failed',
        error_message: message
      })
      setErrorMessage(message)
      toast.error(message)
    } finally {
      setConnecting(false)
      setStatusMessage('Use Reconnect to try the backend handshake again.')
    }
  }

  useEffect(() => {
    if (attemptedInitialConnectRef.current) {
      return
    }
    attemptedInitialConnectRef.current = true
    void handleReconnect()
  }, [])

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-gradient-to-br from-emerald-50 to-teal-100 dark:from-gray-900 dark:to-gray-800">
      <Card className="mx-4 w-full max-w-[560px] shadow-lg">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex items-center gap-3">
            <img src="Logo.png" alt="Retriqs Logo" className="h-12 w-12 object-contain" />
            <ZapIcon className="size-10 text-emerald-400" aria-hidden="true" />
          </div>
          <CardTitle className="text-3xl">Retriqs</CardTitle>
          <CardDescription className="max-w-md text-sm">
            The desktop shell is up, but the backend session is not ready yet. This screen waits
            for `/health` and then completes the guest bootstrap.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="rounded-lg border bg-background/70 p-4">
            <div className="flex items-start gap-3">
              <ServerCrashIcon className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
              <div className="space-y-2">
                <p className="text-sm font-medium">Backend status</p>
                <p className="text-muted-foreground text-sm">{statusMessage}</p>
                {errorMessage && <p className="text-sm text-destructive">{errorMessage}</p>}
              </div>
            </div>
          </div>

          <Button
            type="button"
            className="h-11 w-full text-base font-medium"
            disabled={connecting}
            onClick={handleReconnect}
          >
            <RefreshCwIcon className={connecting ? 'animate-spin' : ''} />
            {connecting ? 'Connecting...' : 'Reconnect'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

export default BackendConnectPage
