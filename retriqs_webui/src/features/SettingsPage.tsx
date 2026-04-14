import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useTenant } from '@/contexts/TenantContext'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { toast } from 'sonner'
import { SaveIcon, Loader2, Cpu, MessageSquarePlus, ArchiveRestore, FileDown, Mail, Trash2 } from 'lucide-react'
import { InstanceSettingsFields } from '@/components/InstanceSettingsFields'
import {
  getSystemSettings,
  updateSystemSettings,
  SettingsUpdateRequest,
  deleteGraphStorage,
  exportStorageArchive,
} from '@/api/retriqs'
import { errorMessage } from '@/lib/utils'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/AlertDialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'

import { useNavigate } from 'react-router-dom'
import { isStorageNeedsReembedding } from '@/lib/storageSettings'
import { StorageArchiveImportFlow } from '@/components/StorageArchiveImportFlow'
import {
  METRICS_EMAIL_SKIP_STORAGE_KEY,
  METRICS_EMAIL_STORAGE_KEY,
  getOrCreateAnalyticsInstallId,
  identifyAnalyticsUser
} from '@/lib/analytics'

type EmbeddingComparableSettings = Pick<
  SettingsUpdateRequest,
  | 'embedding_binding'
  | 'embedding_model'
  | 'embedding_dim'
  | 'embedding_token_limit'
>

const getEmbeddingComparableSettings = (
  data: SettingsUpdateRequest
): EmbeddingComparableSettings => ({
  embedding_binding: data.embedding_binding,
  embedding_model: data.embedding_model,
  embedding_dim: data.embedding_dim,
  embedding_token_limit: data.embedding_token_limit,
})

const hasEmbeddingSettingsChanged = (
  a: EmbeddingComparableSettings,
  b: EmbeddingComparableSettings
) =>
  a.embedding_binding !== b.embedding_binding ||
  a.embedding_model !== b.embedding_model ||
  a.embedding_dim !== b.embedding_dim ||
  a.embedding_token_limit !== b.embedding_token_limit

export default function SettingsPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { selectedTenantId, tenants, loadTenants, setSelectedTenant, isLoading: isContextLoading } = useTenant()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showEmbeddingChangeConfirm, setShowEmbeddingChangeConfirm] = useState(false)
  const [pendingSaveData, setPendingSaveData] = useState<SettingsUpdateRequest | null>(null)
  const [savedEmbeddingSettings, setSavedEmbeddingSettings] = useState<EmbeddingComparableSettings | null>(null)

  const getDefaultMaxAsync = (binding: string) => (binding === 'ollama' ? 1 : 4)
  const getDefaultBindingHost = (binding: string) => {
    if (binding === 'openai') return 'https://api.openai.com/v1'
    if (binding === 'openai_codex') return 'https://chatgpt.com/backend-api/codex'
    if (binding === 'ollama') return 'http://localhost:11434'
    if (binding === 'codex_cli') return 'codex'
    return ''
  }
  const normalizeModelForProvider = (binding: string, model: string) => {
    if (binding === 'ollama' && model.startsWith('ollama/')) {
      return model.slice('ollama/'.length)
    }
    return model
  }

  const [formData, setFormData] = useState<SettingsUpdateRequest>({
    llm_binding: 'openai',
    llm_model: '',
    llm_binding_host: 'https://api.openai.com/v1',
    llm_binding_api_key: '',
    ollama_num_ctx: 32768,
    embedding_binding: 'openai',
    embedding_model: '',
    embedding_binding_host: 'https://api.openai.com/v1',
    embedding_binding_api_key: '',
    embedding_dim: 1536,
    embedding_token_limit: 8192,
    max_async: 4,
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
  })

  useEffect(() => {
    loadTenants()
  }, [selectedTenantId, loadTenants])

  useEffect(() => {
    const syncForm = async () => {
      try {
        setLoading(true)
        if (selectedTenantId) {
          const tenant = tenants.find((t) => t.id === selectedTenantId)
          if (tenant && tenant.storage_settings) {
            const settingsMap = tenant.storage_settings.reduce((acc, curr) => {
              acc[curr.key] = curr.value
              return acc
            }, {} as Record<string, string>)

            const llmBinding = settingsMap.LLM_BINDING || 'openai'
            const embeddingBinding = settingsMap.EMBEDDING_BINDING || 'openai'
            const llmModel = settingsMap.LLM_MODEL || (llmBinding === 'ollama' ? 'qwen3:0.6B' : '')
            const embeddingModel = settingsMap.EMBEDDING_MODEL || (embeddingBinding === 'ollama' ? 'bge-m3:latest' : '')

            setFormData({
              llm_binding: llmBinding,
              llm_model: normalizeModelForProvider(llmBinding, llmModel),
              llm_binding_host: settingsMap.LLM_BINDING_HOST || getDefaultBindingHost(llmBinding),
              llm_binding_api_key: settingsMap.LLM_BINDING_API_KEY || '',
              ollama_num_ctx: settingsMap.OLLAMA_NUM_CTX ? Number(settingsMap.OLLAMA_NUM_CTX) : 32768,
              embedding_binding: embeddingBinding,
              embedding_model: normalizeModelForProvider(embeddingBinding, embeddingModel),
              embedding_binding_host: settingsMap.EMBEDDING_BINDING_HOST || getDefaultBindingHost(embeddingBinding),
              embedding_binding_api_key: settingsMap.EMBEDDING_BINDING_API_KEY || '',
              embedding_dim: settingsMap.EMBEDDING_DIM ? Number(settingsMap.EMBEDDING_DIM) : (embeddingBinding === 'ollama' ? 1024 : 1536),
              embedding_token_limit: settingsMap.EMBEDDING_TOKEN_LIMIT
                ? Number(settingsMap.EMBEDDING_TOKEN_LIMIT)
                : 8192,
              max_async: settingsMap.MAX_ASYNC
                ? Number(settingsMap.MAX_ASYNC)
                : getDefaultMaxAsync(llmBinding),
              rerank_binding: settingsMap.RERANK_BINDING || 'null',
              id: selectedTenantId,
              lightrag_graph_storage: settingsMap.LIGHTRAG_GRAPH_STORAGE || 'GrafeoGraphStorage',
              lightrag_kv_storage: settingsMap.LIGHTRAG_KV_STORAGE || 'JsonKVStorage',
              lightrag_doc_status_storage: settingsMap.LIGHTRAG_DOC_STATUS_STORAGE || 'JsonDocStatusStorage',
              lightrag_vector_storage: settingsMap.LIGHTRAG_VECTOR_STORAGE || 'GrafeoVectorStorage',
              neo4j_uri: settingsMap.NEO4J_URI || 'bolt://localhost:7687',
              neo4j_username: settingsMap.NEO4J_USERNAME || 'neo4j',
              neo4j_password: settingsMap.NEO4J_PASSWORD || 'neo4j',
              milvus_uri: settingsMap.MILVUS_URI || 'http://localhost:19530',
              milvus_db_name: settingsMap.MILVUS_DB_NAME || 'lightrag',
              milvus_user: settingsMap.MILVUS_USER || '',
              milvus_password: settingsMap.MILVUS_PASSWORD || '',
              redis_uri: settingsMap.REDIS_URI || 'redis://localhost:6379',
              openai_consent: !!settingsMap.OPENAI_CONSENT || false
            } as any)
            setSavedEmbeddingSettings({
              embedding_binding: embeddingBinding,
              embedding_model: normalizeModelForProvider(embeddingBinding, embeddingModel),
              embedding_dim: settingsMap.EMBEDDING_DIM ? Number(settingsMap.EMBEDDING_DIM) : (embeddingBinding === 'ollama' ? 1024 : 1536),
              embedding_token_limit: settingsMap.EMBEDDING_TOKEN_LIMIT
                ? Number(settingsMap.EMBEDDING_TOKEN_LIMIT)
                : 8192,
            })
          }
        } else {
          try {
            const data = (await getSystemSettings()) as Record<string, string>
            const llmBinding = data.LLM_BINDING || 'openai'
            setFormData(prev => ({
              ...prev,
              llm_binding: llmBinding,
              llm_binding_host: data.LLM_BINDING_HOST || getDefaultBindingHost(llmBinding),
              embedding_binding_host: data.EMBEDDING_BINDING_HOST || getDefaultBindingHost(prev.embedding_binding),
              max_async: data.MAX_ASYNC ? Number(data.MAX_ASYNC) : getDefaultMaxAsync(llmBinding),
              id: 0
            }))
            setSavedEmbeddingSettings(null)
          } catch (error) {
            console.error("Failed to fetch default settings", error)
          }
        }
      } catch (err) {
        toast.error(t('documentPanel.settingsPage.messages.loadError'))
      } finally {
        setLoading(false)
      }
    }
    syncForm()
  }, [t, selectedTenantId, tenants])

  const persistSettings = async (normalizedFormData: SettingsUpdateRequest) => {
    setSaving(true)
    try {
      await updateSystemSettings(normalizedFormData)
      setFormData(normalizedFormData)
      setSavedEmbeddingSettings(getEmbeddingComparableSettings(normalizedFormData))
      toast.success(t('documentPanel.settingsPage.messages.saveSuccess'))
      await loadTenants()
    } catch (err) {
      toast.error(t('documentPanel.settingsPage.messages.saveError', { error: errorMessage(err) }))
    } finally {
      setSaving(false)
    }
  }

  const handleSave = async () => {
    if (((formData.llm_binding === 'openai' || formData.llm_binding === 'openai_codex') || formData.embedding_binding === 'openai') && !(formData as any).openai_consent) {
        toast.error(t('Please agree to the External Data Processing terms to use OpenAI.'))
        return
    }

    const normalizedFormData: SettingsUpdateRequest = {
      ...formData,
      llm_model: normalizeModelForProvider(formData.llm_binding, formData.llm_model),
      embedding_model: normalizeModelForProvider(formData.embedding_binding, formData.embedding_model)
    }

    const storageEmbeddingsAreUpToDate =
      !!selectedTenant && !isStorageNeedsReembedding(selectedTenant)
    const embeddingChanged =
      savedEmbeddingSettings !== null &&
      hasEmbeddingSettingsChanged(
        savedEmbeddingSettings,
        getEmbeddingComparableSettings(normalizedFormData)
      )

    if (selectedTenantId && storageEmbeddingsAreUpToDate && embeddingChanged) {
      setPendingSaveData(normalizedFormData)
      setShowEmbeddingChangeConfirm(true)
      return
    }

    await persistSettings(normalizedFormData)
  }

  const [tenantToDelete, setTenantToDelete] = useState<number | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [exportingArchive, setExportingArchive] = useState(false)
  const [analyticsEmail, setAnalyticsEmail] = useState(
    localStorage.getItem(METRICS_EMAIL_STORAGE_KEY) || ''
  )
  const [analyticsError, setAnalyticsError] = useState('')

  const selectedTenant = tenants.find((t) => t.id === selectedTenantId)
  const pageTitle = 'Settings'

  const handleSaveAnalyticsEmail = () => {
    const normalizedEmail = analyticsEmail.trim().toLowerCase()
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

    if (!emailPattern.test(normalizedEmail)) {
      setAnalyticsError('Please enter a valid email address.')
      return
    }

    localStorage.setItem(METRICS_EMAIL_STORAGE_KEY, normalizedEmail)
    localStorage.removeItem(METRICS_EMAIL_SKIP_STORAGE_KEY)
    identifyAnalyticsUser(getOrCreateAnalyticsInstallId(), {
      email: normalizedEmail,
      contact_provided: true
    })
    setAnalyticsError('')
    setAnalyticsEmail(normalizedEmail)
    toast.success('Analytics email updated')
  }

  const handleRemoveAnalyticsEmail = () => {
    localStorage.removeItem(METRICS_EMAIL_STORAGE_KEY)
    localStorage.setItem(METRICS_EMAIL_SKIP_STORAGE_KEY, 'true')
    identifyAnalyticsUser(getOrCreateAnalyticsInstallId(), {
      contact_provided: false
    })
    setAnalyticsError('')
    setAnalyticsEmail('')
    toast.success('Analytics email removed')
  }

  const handleExportStorage = async () => {
    if (!selectedTenantId || !selectedTenant) {
      toast.error('Select an instance first')
      return
    }

    setExportingArchive(true)
    try {
      const archiveBlob = await exportStorageArchive(selectedTenantId)
      const blobUrl = URL.createObjectURL(archiveBlob)
      const link = document.createElement('a')
      const safeName = selectedTenant.name.trim().replace(/[^a-z0-9-_]+/gi, '_') || `storage_${selectedTenantId}`
      link.href = blobUrl
      link.download = `${safeName}-storage-export.zip`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(blobUrl)
      toast.success('Storage archive download started')
    } catch (err) {
      toast.error(`Failed to export storage: ${errorMessage(err)}`)
    } finally {
      setExportingArchive(false)
    }
  }

  const confirmDelete = async () => {
    if (!tenantToDelete) return
    setIsDeleting(true)
    try {
      await deleteGraphStorage(tenantToDelete)
      toast.success('Instance deleted successfully')
      await loadTenants()
      // Select another tenant if the deleted one was selected
      if (selectedTenantId === tenantToDelete) {
        const remainingTenants = tenants.filter(t => t.id !== tenantToDelete)
        if (remainingTenants.length > 0) {
          setSelectedTenant(remainingTenants[0].id)
        } else {
          // If no tenants left, the UI will likely show the welcome overlay or similar
          setSelectedTenant(0)
        }
      }
    } catch (err) {
      toast.error(`Failed to delete instance: ${errorMessage(err)}`)
    } finally {
      setIsDeleting(false)
      setTenantToDelete(null)
    }
  }

  if (loading || isContextLoading)
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="text-primary h-8 w-8 animate-spin" />
      </div>
    )

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto scrollbar-thin">
      <div className="mx-auto w-full max-w-5xl space-y-10 p-6 md:p-10 lg:p-12">

        {/* Header */}
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between border-b border-border/40 pb-10">
          <div className="space-y-2">
            <h1 className="text-4xl font-black tracking-tight text-foreground drop-shadow-sm">
              {pageTitle}
            </h1>
            <p className="text-muted-foreground text-base max-w-2xl leading-relaxed opacity-80">
              {t('documentPanel.settingsPage.description')}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button
              onClick={handleSave}
              disabled={saving}
              variant="outline"
              size="sm"
              className="h-9 px-6 font-bold text-xs border-primary/20 hover:border-primary/50 hover:bg-primary/5 text-primary shadow-sm active:scale-95 transition-all"
            >
              {saving ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <SaveIcon className="mr-2 h-3.5 w-3.5" />
              )}
              Save Changes
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 items-start">
          {/* MAIN CONFIGURATION COLUMN */}
          <div className="lg:col-span-8 space-y-8">
            <Card className="overflow-hidden border-none shadow-2xl glass-card">
              <CardHeader className="bg-muted/20 border-b border-border/40 pb-6 pt-8 px-8">
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary shadow-inner">
                    <Cpu className="h-5 w-5" />
                  </div>
                  <div>
                    <CardTitle className="text-lg font-black tracking-tight">Active Instance Configuration</CardTitle>
                    <p className="text-muted-foreground text-xs font-medium opacity-70">
                      Configure the model parameters and storage engine for the current selection.
                    </p>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-8">
                <InstanceSettingsFields
                  formData={formData}
                  setFormData={setFormData}
                  disabledSections={['storage']}
                  apiKeyEditableWhenDisabled
                />
              </CardContent>
            </Card>
          </div>

          {/* SIDEBAR COLUMN */}
          <div className="lg:col-span-4 space-y-6">
            {/* CURRENT CONTEXT */}
            <Card className="border-none shadow-2xl glass-card">
              <CardHeader className="pb-3 pt-6 px-6" />
              <CardContent className="px-6 pb-6">
                <div className="space-y-4">
                  <div className="rounded-xl bg-muted/30 p-4 ring-1 ring-border/20">
                    <div className="text-sm font-bold truncate">{tenants.find(t => t.id === selectedTenantId)?.name || (selectedTenantId === 1 ? 'Storage 1' : 'Default Instance')}</div>
                    <div className="text-[10px] text-muted-foreground font-mono mt-1 opacity-70">ID: {selectedTenantId || 1}</div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full justify-center gap-2 text-center"
                    onClick={() => void handleExportStorage()}
                    disabled={!selectedTenantId || exportingArchive}
                  >
                    {exportingArchive ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
                    Export Storage Archive
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full justify-center gap-2 text-center"
                    onClick={() => {
                      setShowImportDialog(true)
                    }}
                    disabled={!selectedTenantId}
                  >
                    <ArchiveRestore className="h-4 w-4" />
                    Import Into Existing Storage
                  </Button>
                  <Button
                    size="sm"
                    className="w-full justify-center gap-2 text-center bg-red-600 text-white hover:bg-red-700 border-red-600"
                    onClick={() => setTenantToDelete(selectedTenantId)}
                    disabled={!selectedTenantId}
                  >
                    Remove Storage
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* PREFERENCES */}
            {/* <Card className="border-none shadow-2xl glass-card">
              <CardHeader className="bg-muted/10 pb-4 pt-6 px-6 border-b border-border/20">
                <div className="flex items-center gap-3">
                  <Palette className="h-4 w-4 text-muted-foreground/70" />
                  <CardTitle className="text-xs font-black uppercase tracking-widest text-muted-foreground/70">Interface Info</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="p-6 space-y-6">
                <div className="space-y-3">
                  <label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">{t('settings.language')}</label>
                  <Select value={language} onValueChange={(val) => setLanguage(val as any)}>
                    <SelectTrigger className="h-9 rounded-xl border-muted-foreground/10 bg-muted/20 shadow-none">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="en">English (US)</SelectItem>
                      <SelectItem value="zh">中文</SelectItem>
                      <SelectItem value="fr">Français</SelectItem>
                      <SelectItem value="ar">العربية</SelectItem>
                      <SelectItem value="zh_TW">繁體中文</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </CardContent>
            </Card> */}

            {/* FEEDBACK LINK */}
            <Card className="border-none shadow-2xl glass-card overflow-hidden">
              <CardContent className="p-0">
                <Button
                  onClick={() => navigate('/feedback')}
                  variant="ghost"
                  className="w-full h-auto p-6 flex flex-col items-start gap-4 hover:bg-muted/30 transition-colors rounded-none"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary shadow-inner shrink-0">
                      <MessageSquarePlus className="h-5 w-5" />
                    </div>
                    <div className="text-left">
                      <CardTitle className="text-sm font-bold tracking-tight">{t('header.feedback', 'Feedback & Requests')}</CardTitle>
                      <p className="text-xs text-muted-foreground mt-1 whitespace-normal leading-relaxed opacity-80">
                        Help us improve! Share your ideas, report issues, and vote on upcoming features.
                      </p>
                    </div>
                  </div>
                </Button>
              </CardContent>
            </Card>

            <Card className="border-none shadow-2xl glass-card">
              <CardHeader className="bg-muted/10 pb-4 pt-6 px-6 border-b border-border/20">
                <div className="flex items-center gap-3">
                  <Mail className="h-4 w-4 text-muted-foreground/70" />
                  <CardTitle className="text-xs font-black uppercase tracking-widest text-muted-foreground/70">Analytics</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="p-6 space-y-4">
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Control the optional email used for product analytics.
                </p>
                <Input
                  type="email"
                  placeholder="name@company.com"
                  value={analyticsEmail}
                  onChange={(e) => {
                    setAnalyticsEmail(e.target.value)
                    if (analyticsError) {
                      setAnalyticsError('')
                    }
                  }}
                />
                {analyticsError && (
                  <p className="text-xs text-destructive">{analyticsError}</p>
                )}
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    className="flex-1"
                    onClick={handleSaveAnalyticsEmail}
                  >
                    Save
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="flex-1"
                    onClick={handleRemoveAnalyticsEmail}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Remove
                  </Button>
                </div>
              </CardContent>
            </Card>

          </div>
        </div>
      </div>
      <Dialog open={showImportDialog} onOpenChange={(open) => {
        setShowImportDialog(open)
      }}>
        <DialogContent className="max-w-xl bg-background/98 backdrop-blur-2xl border-none shadow-2xl overflow-hidden p-0 max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="px-8 pt-8 text-2xl font-black">Import Into Existing Storage</DialogTitle>
            <DialogDescription>
              Analyze a storage archive against the current instance, then apply the merge with an explicit conflict policy.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col h-full overflow-y-auto scrollbar-thin p-8 pt-2">
            <StorageArchiveImportFlow
              open={showImportDialog}
              source="custom"
              allowedModes={['merge']}
              lockedMode="merge"
              lockedTargetStorage={selectedTenant ?? null}
              onCompleted={() => {
                setShowImportDialog(false)
              }}
            />
          </div>
        </DialogContent>
      </Dialog>
      <AlertDialog open={!!tenantToDelete} onOpenChange={(open) => !open && setTenantToDelete(null)}>
        <AlertDialogContent className="max-w-[400px]">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Instance?</AlertDialogTitle>
            <AlertDialogDescription className="text-sm">
              This will permanently remove <strong>{tenants.find(t => t.id === tenantToDelete)?.name || 'this storage'}</strong> and all indexed documents. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="mt-4 gap-2">
            <AlertDialogCancel disabled={isDeleting} className="text-xs h-8">Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                confirmDelete()
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 text-xs h-8"
              disabled={isDeleting}
            >
              {isDeleting ? 'Deleting...' : 'Delete Permanently'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog
        open={showEmbeddingChangeConfirm}
        onOpenChange={(open) => {
          setShowEmbeddingChangeConfirm(open)
          if (!open) {
            setPendingSaveData(null)
          }
        }}
      >
        <AlertDialogContent className="max-w-[520px]">
          <AlertDialogHeader>
            <AlertDialogTitle>Change Embedding Settings?</AlertDialogTitle>
            <AlertDialogDescription className="text-sm leading-relaxed">
              This storage already has indexed embeddings. Changing the embedding model/config invalidates existing vectors.
              <br />
              <br />
              After saving, you must run a full re-embedding from the <strong>Documents</strong> page. Until then, retrieval quality can be incorrect.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="mt-4 gap-2">
            <AlertDialogCancel
              disabled={saving}
              className="text-xs h-8"
              onClick={() => setPendingSaveData(null)}
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 text-xs h-8"
              disabled={saving || !pendingSaveData}
              onClick={(e) => {
                e.preventDefault()
                if (!pendingSaveData) {
                  return
                }
                setShowEmbeddingChangeConfirm(false)
                void persistSettings(pendingSaveData)
                setPendingSaveData(null)
              }}
            >
              {saving ? 'Saving...' : 'I Understand, Save Changes'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
