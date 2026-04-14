import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTenant } from '@/contexts/TenantContext'
import Button from '@/components/ui/Button'
import { Card, CardContent } from '@/components/ui/Card'
import Input from '@/components/ui/Input'
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  Database,
  Mail,
  Store,
} from 'lucide-react'
import { canCreateAnotherStorage } from '@/lib/editionPolicy'
import { UpgradePromptDialog } from '@/components/UpgradePromptDialog'
import { StorageCreateDialog } from '@/components/StorageCreateDialog'
import {
  METRICS_EMAIL_SKIP_STORAGE_KEY,
  METRICS_EMAIL_STORAGE_KEY,
  getOrCreateAnalyticsInstallId,
  identifyAnalyticsUser
} from '@/lib/analytics'

const ONBOARDING_STEP_STORAGE_KEY = 'RETRIQS-ONBOARDING-STEP'
const DEFAULT_STORAGE_NAME = 'My First Storage'

interface WelcomeOverlayProps {
  onStorageCreated?: () => void
}

export const WelcomeOverlay: React.FC<WelcomeOverlayProps> = ({ onStorageCreated }) => {
  const { tenants } = useTenant()
  const navigate = useNavigate()
  const [step, setStep] = useState<'welcome' | 'storage'>(
    () => (localStorage.getItem(ONBOARDING_STEP_STORAGE_KEY) === 'storage' ? 'storage' : 'welcome')
  )
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showUpgradeDialog, setShowUpgradeDialog] = useState(false)
  const [upgradeReason, setUpgradeReason] = useState('')
  const [contactEmail, setContactEmail] = useState(
    localStorage.getItem(METRICS_EMAIL_STORAGE_KEY) || ''
  )
  const [contactError, setContactError] = useState('')
  const [contactSubmitted, setContactSubmitted] = useState(
    Boolean(localStorage.getItem(METRICS_EMAIL_STORAGE_KEY))
  )
  const [contactSkipped, setContactSkipped] = useState(
    localStorage.getItem(METRICS_EMAIL_SKIP_STORAGE_KEY) === 'true'
  )

  useEffect(() => {
    localStorage.setItem(ONBOARDING_STEP_STORAGE_KEY, step)
  }, [step])

  const handleSaveEmail = () => {
    const normalizedEmail = contactEmail.trim().toLowerCase()
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

    if (!emailPattern.test(normalizedEmail)) {
      setContactError('Please enter a valid email address.')
      return
    }

    localStorage.setItem(METRICS_EMAIL_STORAGE_KEY, normalizedEmail)
    localStorage.removeItem(METRICS_EMAIL_SKIP_STORAGE_KEY)
    identifyAnalyticsUser(getOrCreateAnalyticsInstallId(), {
      email: normalizedEmail,
      contact_provided: true
    })
    setContactError('')
    setContactSubmitted(true)
    setContactSkipped(false)
  }

  const handleSkipEmail = () => {
    localStorage.setItem(METRICS_EMAIL_SKIP_STORAGE_KEY, 'true')
    setContactSkipped(true)
    setContactError('')
  }

  const handleSkipEmailAndContinue = () => {
    handleSkipEmail()
    setStep('storage')
  }

  const openCreateDialog = () => {
    if (!canCreateAnotherStorage(tenants.length)) {
      setUpgradeReason('Creating more than one storage is available in Pro.')
      setShowUpgradeDialog(true)
      return
    }
    setShowCreateDialog(true)
  }

  const goToMarketplace = () => {
    navigate('/marketplace')
  }

  const continueToStorageStep = () => {
    if (!contactSubmitted && !contactSkipped) {
      handleSkipEmail()
    }
    setStep('storage')
  }

  const handleStorageCreated = () => {
    localStorage.removeItem(ONBOARDING_STEP_STORAGE_KEY)
    onStorageCreated?.()
  }

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto p-3 sm:items-center sm:p-6 glass backdrop-blur-md">
      <Card className="w-full max-w-4xl border-none shadow-2xl glass-card max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-3rem)]">
        <CardContent className="overflow-y-auto px-4 py-5 sm:px-8 sm:pt-8 sm:pb-6">
          <div className="grid gap-5 lg:grid-cols-[1.05fr_1fr] lg:items-stretch">
            <div className="rounded-[28px] border border-border/50 bg-gradient-to-br from-background/90 via-muted/30 to-background/80 p-5 sm:p-7">
              <div className="flex h-full flex-col justify-between gap-6">
                <div className="space-y-5">
                  <div className="flex items-center gap-3">
                    <div className="rounded-2xl bg-primary/10 p-3 ring-1 ring-primary/15">
                      <Database className="h-8 w-8 text-primary sm:h-10 sm:w-10" />
                    </div>
                    <div className="flex flex-col items-start gap-1">
                      <div className="inline-flex items-center rounded-full border border-border/50 bg-background/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        Getting Started
                      </div>
                      <div className="inline-flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
                        <Clock3 className="h-3.5 w-3.5" />
                        About 1 minute
                      </div>
                    </div>
                  </div>

                  <div className="space-y-3 text-left">
                    <h1 className="text-3xl font-black tracking-tight text-foreground sm:text-4xl">
                      Welcome to Retriqs
                    </h1>
                    <p className="max-w-xl text-sm leading-6 text-muted-foreground sm:text-base">
                      We will get you from first launch to a working storage in two clean steps. Start with a quick welcome, then create the workspace where your documents and graph will live.
                    </p>
                  </div>
                </div>

                <div className="rounded-2xl border border-border/40 bg-background/70 p-4">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${step === 'welcome' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>
                        1
                      </span>
                      <span className="text-sm font-medium text-foreground">Welcome</span>
                    </div>
                    <div className="h-px flex-1 bg-border/60" />
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${step === 'storage' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>
                        2
                      </span>
                      <span className="text-sm font-medium text-foreground">Storage</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-border/50 bg-background/80 p-4 shadow-sm sm:p-5">
              <div className="space-y-4">
                <div className="rounded-2xl border border-border/60 bg-muted/25 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Current step
                      </p>
                      <p className="mt-1 text-lg font-semibold text-foreground">
                        {step === 'welcome' ? 'Welcome' : 'Create storage'}
                      </p>
                    </div>
                    <div className="text-sm font-semibold text-primary">
                      {step === 'welcome' ? 'Step 1/2' : 'Step 2/2'}
                    </div>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-muted">
                    <div
                      className="h-2 rounded-full bg-primary transition-all duration-300"
                      style={{ width: step === 'welcome' ? '50%' : '100%' }}
                    />
                  </div>
                </div>

                {step === 'welcome' ? (
                  <>
                    <div className="rounded-2xl border border-border/60 bg-background/90 p-4 text-left">
                      <div className="space-y-2">
                        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                          <Mail className="h-4 w-4" />
                          Optional analytics email
                        </h2>
                        <p className="text-sm leading-6 text-muted-foreground">
                          Share your email if you want to help us improve Retriqs. You can also skip this and continue right away.
                        </p>
                      </div>
                      {!contactSubmitted && (
                        <>
                          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                            <Input
                              type="email"
                              placeholder="name@company.com"
                              value={contactEmail}
                              onChange={(e) => setContactEmail(e.target.value)}
                              className="flex-1"
                            />
                            <Button type="button" onClick={handleSaveEmail}>
                              Save email
                            </Button>
                          </div>
                          <div className="mt-3">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-0 text-xs font-medium text-muted-foreground hover:bg-transparent hover:text-muted-foreground"
                              onClick={handleSkipEmailAndContinue}
                            >
                              Skip for now
                            </Button>
                          </div>
                        </>
                      )}
                      {contactError && (
                        <p className="mt-2 text-sm text-destructive">{contactError}</p>
                      )}
                      {contactSubmitted && !contactError && (
                        <div className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-2 text-sm text-primary">
                          <CheckCircle2 className="h-4 w-4" />
                          Thanks. We will use this email for product metrics.
                        </div>
                      )}
                    </div>

                    <Button
                      size="lg"
                      className="w-full font-bold"
                      onClick={continueToStorageStep}
                    >
                      Continue
                      <ArrowRight className="ml-2 h-5 w-5" />
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="rounded-2xl border border-border/60 bg-background/90 p-4 text-left">
                      <p className="text-sm font-semibold text-foreground">Create your first storage</p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Suggested name: {DEFAULT_STORAGE_NAME}
                      </p>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">
                        A <span className="font-semibold text-foreground">storage instance</span> is your main workspace for documents, graph data, and embeddings.
                      </p>
                    </div>

                    <div className="space-y-3">
                      <Button
                        size="lg"
                        className="w-full shadow-xl shadow-primary/25 transition-all hover:scale-[1.01] font-bold"
                        onClick={openCreateDialog}
                      >
                        <Database className="mr-2 h-5 w-5" />
                        Create Your First Storage
                      </Button>

                      <Button
                        size="lg"
                        variant="outline"
                        className="w-full font-bold hover:bg-background hover:text-foreground"
                        onClick={goToMarketplace}
                      >
                        <Store className="mr-2 h-5 w-5" />
                        Browse Marketplace Packs
                      </Button>

                      <Button
                        type="button"
                        variant="ghost"
                        className="w-full text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                        onClick={() => setStep('welcome')}
                      >
                        Back
                      </Button>
                    </div>
                  </>
                )}
            </div>
          </div>
          </div>
        </CardContent>
      </Card>

      <StorageCreateDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        onStorageCreated={handleStorageCreated}
        initialName={DEFAULT_STORAGE_NAME}
      />

      <UpgradePromptDialog
        open={showUpgradeDialog}
        onOpenChange={setShowUpgradeDialog}
        reason={upgradeReason}
      />
    </div>
  )
}
