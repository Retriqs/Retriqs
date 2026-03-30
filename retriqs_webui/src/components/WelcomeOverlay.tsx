import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTenant } from '@/contexts/TenantContext'
import Button from '@/components/ui/Button'
import { Card, CardContent } from '@/components/ui/Card'
import { Database, Store } from 'lucide-react'
import { canCreateAnotherStorage } from '@/lib/editionPolicy'
import { UpgradePromptDialog } from '@/components/UpgradePromptDialog'
import { StorageCreateDialog } from '@/components/StorageCreateDialog'

interface WelcomeOverlayProps {
  onStorageCreated?: () => void
}

export const WelcomeOverlay: React.FC<WelcomeOverlayProps> = ({ onStorageCreated }) => {
  const { tenants } = useTenant()
  const navigate = useNavigate()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showUpgradeDialog, setShowUpgradeDialog] = useState(false)
  const [upgradeReason, setUpgradeReason] = useState('')

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

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center glass backdrop-blur-md">
      <Card className="w-full max-w-2xl mx-4 border-none shadow-2xl glass-card">
        <CardContent className="pt-8 pb-6 px-8">
          <div className="flex flex-col items-center text-center space-y-6">
            <div className="rounded-full bg-primary/10 p-6">
              <Database className="h-16 w-16 text-primary" />
            </div>

            <div className="space-y-2">
              <h1 className="text-4xl font-black tracking-tight text-foreground drop-shadow-sm">Welcome to Retriqs</h1>
              <p className="text-muted-foreground text-lg">
                Create your first knowledge storage to get started
              </p>
            </div>

            <div className="bg-muted/50 rounded-lg p-4 space-y-2 w-full">
              <p className="text-sm text-muted-foreground">
                A <span className="font-semibold text-foreground">storage instance</span> is an isolated workspace where your documents,
                knowledge graph, and embeddings are stored. You can create multiple storages for different projects or use cases.
              </p>
            </div>

            <div className="w-full max-w-sm space-y-3">
              <Button
                size="lg"
                className="w-full shadow-2xl shadow-primary/30 transition-all hover:scale-105 font-bold"
                onClick={openCreateDialog}
              >
                <Database className="mr-2 h-5 w-5" />
                Create Your First Storage
              </Button>

              <Button
                size="lg"
                variant="outline"
                className="w-full font-bold"
                onClick={goToMarketplace}
              >
                <Store className="mr-2 h-5 w-5" />
                Browse Marketplace Packs
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <StorageCreateDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        onStorageCreated={onStorageCreated}
      />

      <UpgradePromptDialog
        open={showUpgradeDialog}
        onOpenChange={setShowUpgradeDialog}
        reason={upgradeReason}
      />
    </div>
  )
}
