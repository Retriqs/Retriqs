import React from 'react'
import Button from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/Dialog'
import { UPGRADE_URL, redirectToUpgrade } from '@/lib/editionPolicy'

interface UpgradePromptDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  reason?: string
}

export const UpgradePromptDialog: React.FC<UpgradePromptDialogProps> = ({
  open,
  onOpenChange,
  reason
}) => {
  const handleBuyNow = () => {
    onOpenChange(false)
    redirectToUpgrade()
  }

  const handleGoToWebsite = () => {
    window.open(UPGRADE_URL, '_blank', 'noopener,noreferrer')
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Free Edition Limit</DialogTitle>
          <DialogDescription>
            You are using the free edition. Upgrade to Pro to unlock full access.
          </DialogDescription>
        </DialogHeader>
        {reason && <p className="text-sm text-muted-foreground">{reason}</p>}
        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="secondary" onClick={handleGoToWebsite}>
            Go to Website
          </Button>
          <Button onClick={handleBuyNow}>Buy Now</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
