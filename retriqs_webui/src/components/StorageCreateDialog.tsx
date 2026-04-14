import React, { useEffect, useState } from 'react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/Tabs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Loader2, Plus, ChevronDown, ChevronUp } from 'lucide-react'
import { InstanceSettingsFields } from '@/components/InstanceSettingsFields'
import {
  createNewStorage,
  SettingsUpdateRequest
} from '@/api/retriqs'
import { getTenantCreateActionLabel } from '@/components/tenantCreateDialogUtils'
import { toast } from 'sonner'
import { errorMessage } from '@/lib/utils'
import { useTenant } from '@/contexts/TenantContext'
import { StorageArchiveImportFlow } from '@/components/StorageArchiveImportFlow'
import { trackEvent, trackFunnelStep } from '@/lib/analytics'

interface StorageCreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onStorageCreated?: () => void
  initialName?: string
}

const defaultInstanceSettings: SettingsUpdateRequest = {
  llm_binding: 'ollama',
  llm_model: 'qwen3:0.6B',
  llm_binding_host: 'http://localhost:11434',
  llm_binding_api_key: '',
  ollama_num_ctx: 32768,
  embedding_binding: 'ollama',
  embedding_model: 'bge-m3:latest',
  embedding_binding_host: 'http://localhost:11434',
  embedding_binding_api_key: '',
  embedding_dim: 1024,
  embedding_token_limit: 8192,
  max_async: 1,
  rerank_binding: 'null',
  id: 0,
  lightrag_graph_storage: 'GrafeoGraphStorage',
  lightrag_kv_storage: 'JsonKVStorage',
  lightrag_doc_status_storage: 'JsonDocStatusStorage',
  lightrag_vector_storage: 'GrafeoVectorStorage',
  neo4j_uri: 'bolt://localhost:7687',
  neo4j_username: 'neo4j',
  neo4j_password: 'neo4j',
  milvus_uri: 'http://localhost:19530',
  milvus_db_name: 'lightrag',
  milvus_user: '',
  milvus_password: '',
  redis_uri: 'redis://localhost:6379',
}

export const StorageCreateDialog: React.FC<StorageCreateDialogProps> = ({
  open,
  onOpenChange,
  onStorageCreated,
  initialName,
}) => {
  const { loadTenants, setSelectedTenant } = useTenant()
  const [creatingInstance, setCreatingInstance] = useState(false)
  const [newInstanceName, setNewInstanceName] = useState('')
  const [newInstanceFormData, setNewInstanceFormData] = useState<SettingsUpdateRequest>(defaultInstanceSettings)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [createMode, setCreateMode] = useState<'blank' | 'import'>('blank')

  useEffect(() => {
    if (!open) {
      return
    }

    setNewInstanceName(initialName || '')
  }, [initialName, open])

  const resetCreateDialog = () => {
    setCreatingInstance(false)
    setNewInstanceName('')
    setNewInstanceFormData(defaultInstanceSettings)
    setShowAdvanced(false)
    setCreateMode('blank')
  }

  const normalizeModelForProvider = (binding: string, model: string) => {
    if (binding === 'ollama' && model.startsWith('ollama/')) {
      return model.slice('ollama/'.length)
    }
    return model
  }

  const handleCreateInstance = async () => {
    if (!newInstanceName.trim()) {
      toast.error('Please enter a name for the new instance')
      trackEvent('storage_create_failed', {
        error_code: 'missing_name'
      })
      return
    }

    if (((newInstanceFormData.llm_binding === 'openai' || newInstanceFormData.llm_binding === 'openai_codex') || newInstanceFormData.embedding_binding === 'openai') && !(newInstanceFormData as any).openai_consent) {
      toast.error('Please agree to the External Data Processing terms to use OpenAI.')
      trackEvent('storage_create_failed', {
        error_code: 'missing_openai_consent'
      })
      return
    }

    setCreatingInstance(true)
    trackEvent('storage_create_started', {
      create_mode: createMode,
      has_advanced_settings: showAdvanced
    })
    trackFunnelStep('activation', 'storage_create_started', 3, {
      create_mode: createMode
    })
    try {
      const normalizedNewInstanceData: SettingsUpdateRequest = {
        ...newInstanceFormData,
        llm_model: normalizeModelForProvider(newInstanceFormData.llm_binding, newInstanceFormData.llm_model),
        embedding_model: normalizeModelForProvider(newInstanceFormData.embedding_binding, newInstanceFormData.embedding_model)
      }
      const result = await createNewStorage(newInstanceName.trim(), normalizedNewInstanceData)
      toast.success(`Instance "${result.storage.name}" created successfully!`)
      trackEvent('storage_created', {
        storage_id: result.storage.id,
        storage_name: result.storage.name,
        create_mode: createMode
      })
      trackFunnelStep('activation', 'storage_created', 4, {
        storage_id: result.storage.id
      })
      await loadTenants()
      setSelectedTenant(result.storage.id)
      onOpenChange(false)
      resetCreateDialog()
      onStorageCreated?.()
    } catch (err) {
      trackEvent('storage_create_failed', {
        create_mode: createMode,
        error_message: errorMessage(err)
      })
      toast.error(`Failed to create instance: ${errorMessage(err)}`)
    } finally {
      setCreatingInstance(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) {
          trackEvent('storage_create_dialog_opened')
        }
        onOpenChange(nextOpen)
        if (!nextOpen) {
          resetCreateDialog()
        }
      }}
    >
      <DialogContent className="w-[95vw] sm:w-[92vw] max-w-2xl max-h-[90vh] p-0 gap-0 flex flex-col overflow-hidden">
        <DialogHeader className="px-4 sm:px-6 pt-6 pb-3 border-b">
          <DialogTitle>Create New Instance</DialogTitle>
          <DialogDescription>
            Create a blank instance or import a prebuilt storage archive.
          </DialogDescription>
        </DialogHeader>
        <div className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-6 py-4">
          <Tabs
            value={createMode}
            onValueChange={(value) => {
              const nextMode = value as 'blank' | 'import'
              setCreateMode(nextMode)
              trackEvent('storage_create_mode_changed', {
                create_mode: nextMode
              })
            }}
            className="space-y-4"
          >
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="blank">Blank Instance</TabsTrigger>
              <TabsTrigger value="import">Import Archive</TabsTrigger>
            </TabsList>
            <TabsContent value="blank" className="mt-0 space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Instance Name</label>
                <Input
                  placeholder="e.g., Marketing-RAG-01"
                  value={newInstanceName}
                  onChange={(e) => setNewInstanceName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !creatingInstance) {
                      void handleCreateInstance()
                    }
                  }}
                />
              </div>

              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                {showAdvanced ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
                Advanced Settings (Optional)
              </button>

              {showAdvanced && (
                <div className="space-y-6 border-t pt-4">
                  <InstanceSettingsFields formData={newInstanceFormData} setFormData={setNewInstanceFormData} disabledSections={['storage']} />
                </div>
              )}
            </TabsContent>
            <TabsContent value="import" className="mt-0 space-y-4">
              <StorageArchiveImportFlow
                open={open && createMode === 'import'}
                source="custom"
                allowedModes={['new']}
                lockedMode="new"
                initialName={newInstanceName}
                onCompleted={() => {
                  onOpenChange(false)
                  resetCreateDialog()
                  void loadTenants()
                  onStorageCreated?.()
                }}
              />
            </TabsContent>
          </Tabs>
        </div>
        {createMode === 'blank' && (
          <DialogFooter className="sticky bottom-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 border-t px-4 sm:px-6 py-3">
            <Button
              variant="ghost"
              onClick={() => {
                onOpenChange(false)
                resetCreateDialog()
              }}
              disabled={creatingInstance}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleCreateInstance()}
              disabled={creatingInstance || !newInstanceName.trim()}
            >
              {creatingInstance ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
              {getTenantCreateActionLabel(createMode)}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}
