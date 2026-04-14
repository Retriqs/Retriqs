import posthog from 'posthog-js'
import { isDesktopRuntime } from './runtime'

type AnalyticsValue = string | number | boolean | null | undefined
type AnalyticsParams = Record<string, AnalyticsValue>
type FunnelStepParams = AnalyticsParams & {
  funnel_name: string
  funnel_step: string
  step_number: number
}

let initialized = false

export const METRICS_EMAIL_STORAGE_KEY = 'RETRIQS-METRICS-EMAIL'
export const METRICS_EMAIL_SKIP_STORAGE_KEY = 'RETRIQS-METRICS-EMAIL-SKIPPED'
export const METRICS_INSTALL_ID_STORAGE_KEY = 'RETRIQS-METRICS-INSTALL-ID'

const getPlatform = (): string => (isDesktopRuntime() ? 'desktop' : 'web')

const sanitizeParams = (params?: AnalyticsParams): Record<string, string | number | boolean> => {
  if (!params) {
    return {}
  }

  return Object.entries(params).reduce<Record<string, string | number | boolean>>((acc, [key, value]) => {
    if (value === undefined || value === null) {
      return acc
    }

    acc[key] = value
    return acc
  }, {})
}

const getDefaultParams = (): AnalyticsParams => ({
  platform: getPlatform(),
  app_version: localStorage.getItem('LIGHTRAG-API-VERSION') || undefined,
  core_version: localStorage.getItem('LIGHTRAG-CORE-VERSION') || undefined
})

const generateInstallId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `install-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export const getOrCreateAnalyticsInstallId = (): string => {
  const storedInstallId = localStorage.getItem(METRICS_INSTALL_ID_STORAGE_KEY)
  if (storedInstallId) {
    return storedInstallId
  }

  const installId = generateInstallId()
  localStorage.setItem(METRICS_INSTALL_ID_STORAGE_KEY, installId)
  return installId
}

export const isAnalyticsConfigured = (): boolean =>
  Boolean(import.meta.env.VITE_PUBLIC_POSTHOG_KEY && import.meta.env.VITE_PUBLIC_POSTHOG_HOST)

export const initAnalytics = (): void => {
  if (initialized || typeof window === 'undefined' || !isAnalyticsConfigured()) {
    return
  }

  posthog.init(import.meta.env.VITE_PUBLIC_POSTHOG_KEY as string, {
    api_host: import.meta.env.VITE_PUBLIC_POSTHOG_HOST,
    autocapture: false,
    capture_pageview: false,
    capture_pageleave: false,
    person_profiles: 'identified_only',
    loaded: (instance) => {
      if (import.meta.env.DEV) {
        instance.debug(true)
      }
    }
  })

  initialized = true
}

export const trackEvent = (eventName: string, params?: AnalyticsParams): void => {
  if (!initialized) {
    return
  }

  posthog.capture(eventName, {
    ...sanitizeParams(getDefaultParams()),
    ...sanitizeParams(params)
  })
}

export const trackFunnelStep = (
  funnelName: string,
  funnelStep: string,
  stepNumber: number,
  params?: AnalyticsParams
): void => {
  const funnelParams: FunnelStepParams = {
    funnel_name: funnelName,
    funnel_step: funnelStep,
    step_number: stepNumber,
    ...params
  }
  trackEvent('funnel_step', funnelParams)
}

export const identifyAnalyticsUser = (distinctId: string, properties?: AnalyticsParams): void => {
  if (!initialized) {
    return
  }

  posthog.identify(distinctId, sanitizeParams(properties))
}

export const aliasAnalyticsUser = (alias: string): void => {
  if (!initialized) {
    return
  }

  posthog.alias(alias)
}

export const getAnalyticsDistinctId = (): string | null => {
  if (!initialized) {
    return null
  }

  return posthog.get_distinct_id()
}

export const resetAnalytics = (): void => {
  if (!initialized) {
    return
  }

  posthog.reset()
}

export const captureException = (error: unknown, properties?: AnalyticsParams): void => {
  if (!initialized) {
    return
  }

  posthog.captureException(error, sanitizeParams(properties))
}
