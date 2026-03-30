import React, { useState } from 'react'
import { useTenant } from '@/contexts/TenantContext'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/Select'
import Button from '@/components/ui/Button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/AlertDialog'
import { Database, Trash2, HardDrive, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { deleteGraphStorage } from '@/api/retriqs'
import { toast } from 'sonner'
import { canCreateAnotherStorage } from '@/lib/editionPolicy'
import { UpgradePromptDialog } from '@/components/UpgradePromptDialog'
import { StorageCreateDialog } from '@/components/StorageCreateDialog'

const CREATE_INSTANCE_VALUE = '__create_new_instance__'

export const TenantSelector: React.FC = () => {
  const { selectedTenantId, tenants, isLoading, setSelectedTenant, loadTenants } = useTenant()
  const [tenantToDelete, setTenantToDelete] = useState<number | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showUpgradeDialog, setShowUpgradeDialog] = useState(false)
  const [upgradeReason, setUpgradeReason] = useState('')

  const openCreateDialog = () => {
    //TODO remove or enforce
    // if (!canCreateAnotherStorage(tenants.length)) {
    //   setUpgradeReason('Creating more than one storage is available in Pro.')
    //   setShowUpgradeDialog(true)
    //   return
    // }
    setShowCreateDialog(true)
  }

  const confirmDelete = async () => {
    if (!tenantToDelete) return

    setIsDeleting(true)
    try {
      await deleteGraphStorage(tenantToDelete)
      toast.success('Tenant deleted successfully')
      await loadTenants()
      if (selectedTenantId === tenantToDelete) {
        setSelectedTenant(tenants.find((t) => t.id !== tenantToDelete)?.id || 0)
      }
    } catch (error) {
      console.error('Failed to delete tenant:', error)
      toast.error('Failed to delete tenant')
    } finally {
      setIsDeleting(false)
      setTenantToDelete(null)
    }
  }

  if (isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Database className="h-4 w-4" />
        <span>Loading...</span>
      </div>
    )
  }

  const selectedTenant = tenants.find((t) => t.id === selectedTenantId)

  if (tenants.length === 0) {
    return (
      <>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9"
          onClick={openCreateDialog}
        >
          <Plus className="mr-2 h-3.5 w-3.5" />
          Create Instance
        </Button>

        <StorageCreateDialog open={showCreateDialog} onOpenChange={setShowCreateDialog} />

        <UpgradePromptDialog
          open={showUpgradeDialog}
          onOpenChange={setShowUpgradeDialog}
          reason={upgradeReason}
        />
      </>
    )
  }

  return (
    <div className="flex items-center">
      <Select
        value={selectedTenantId?.toString() || ''}
        onValueChange={(value) => {
          if (value === CREATE_INSTANCE_VALUE) {
            openCreateDialog()
            return
          }
          setSelectedTenant(parseInt(value, 10))
        }}
      >
        <SelectTrigger className="bg-muted/40 hover:bg-muted/60 shadown-none focus:ring-primary/20 group h-9 w-[240px] border-none px-3 py-1 transition-colors focus:ring-1">
          <div className="flex w-full items-center gap-2.5 overflow-hidden">
            <div className="bg-primary/10 text-primary group-hover:bg-primary/20 flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors">
              <HardDrive className="h-3.5 w-3.5" />
            </div>
            <div className="flex flex-col items-start overflow-hidden leading-tight">
              <span className="text-foreground/90 w-full truncate text-left text-xs font-semibold">
                {selectedTenant?.name || 'Select Instance'}
              </span>
              <span className="text-muted-foreground w-full truncate text-left text-[9px] font-medium tracking-wider uppercase opacity-70">
                Storage ID: {selectedTenant?.id}
              </span>
            </div>
          </div>
        </SelectTrigger>
        <SelectContent className="border-muted/40 min-w-[240px] p-1 shadow-2xl">
          <div className="text-muted-foreground/60 px-2 py-1.5 text-[10px] font-bold tracking-widest uppercase">
            Switch Instance
          </div>
          {tenants.map((tenant) => (
            <SelectItem
              key={tenant.id}
              value={tenant.id.toString()}
              className="focus:bg-primary/5 cursor-pointer rounded-md"
            >
              <div className="group/item flex w-full items-center justify-between py-0.5 pl-0">
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      'h-2 w-2 rounded-full',
                      tenant.id === selectedTenantId
                        ? 'bg-primary animate-pulse'
                        : 'bg-muted-foreground/30'
                    )}
                  />
                  <div className="flex flex-col">
                    <span
                      className={cn(
                        'text-sm transition-colors',
                        tenant.id === selectedTenantId ? 'text-primary font-bold' : 'font-medium'
                      )}
                    >
                      {tenant.name}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  className="hover:bg-destructive/10 ml-auto cursor-pointer rounded-md p-1.5 opacity-0 transition-opacity group-hover/item:opacity-100"
                  onPointerDown={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    setTenantToDelete(tenant.id)
                  }}
                >
                  <Trash2 className="text-destructive/70 hover:text-destructive h-3.5 w-3.5" />
                </button>
              </div>
            </SelectItem>
          ))}
          <SelectItem
            value={CREATE_INSTANCE_VALUE}
            className="focus:bg-primary/5 border-border/60 mt-1 cursor-pointer rounded-md border-t pt-2"
          >
            <div className="flex items-center gap-3 py-0.5 pl-0">
              <div className="bg-primary/10 text-primary flex h-5 w-5 items-center justify-center rounded-md">
                <Plus className="h-3.5 w-3.5" />
              </div>
              <span className="text-primary text-sm font-semibold">Create New Instance</span>
            </div>
          </SelectItem>
        </SelectContent>
      </Select>

      <AlertDialog
        open={!!tenantToDelete}
        onOpenChange={(open) => !open && setTenantToDelete(null)}
      >
        <AlertDialogContent className="max-w-[400px]">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Instance?</AlertDialogTitle>
            <AlertDialogDescription className="text-sm">
              This will permanently remove{' '}
              <strong>{tenants.find((t) => t.id === tenantToDelete)?.name}</strong> and all indexed
              documents. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="mt-4 gap-2">
            <AlertDialogCancel disabled={isDeleting} className="h-8 text-xs">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                void confirmDelete()
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 h-8 text-xs"
              disabled={isDeleting}
            >
              {isDeleting ? 'Deleting...' : 'Delete Permanently'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <StorageCreateDialog open={showCreateDialog} onOpenChange={setShowCreateDialog} />

      <UpgradePromptDialog
        open={showUpgradeDialog}
        onOpenChange={setShowUpgradeDialog}
        reason={upgradeReason}
      />
    </div>
  )
}
