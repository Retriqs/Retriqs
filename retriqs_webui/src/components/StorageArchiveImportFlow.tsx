import { useEffect, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { toast } from 'sonner'
import {
  importStorageArchive,
  analyzeStorageArchiveMerge,
  applyStorageArchiveMerge,
  getGraphStorages,
  ArchiveEmbeddingImportMode,
  GraphStorage,
  StorageMergeAnalysisResponse
} from '@/api/retriqs'
import { useTenant } from '@/contexts/TenantContext'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { ArchiveRestore, ArrowRight, CheckCircle2, Plus, Zap, AlertTriangle } from 'lucide-react'

type ImportSource = 'marketplace' | 'custom'
type ImportMode = 'new' | 'merge'
type ConflictMode = 'archive_wins' | 'keep_existing'

interface StorageArchiveImportFlowProps {
  open: boolean
  source?: ImportSource
  initialArchiveUrl?: string | null
  initialName?: string
  allowedModes?: ImportMode[]
  lockedMode?: ImportMode
  lockedTargetStorage?: GraphStorage | null
  onCompleted?: () => void
}

const DEFAULT_ALLOWED_MODES: ImportMode[] = ['new', 'merge']

export function StorageArchiveImportFlow({
  open,
  source = 'custom',
  initialArchiveUrl = null,
  initialName = '',
  allowedModes = DEFAULT_ALLOWED_MODES,
  lockedMode,
  lockedTargetStorage = null,
  onCompleted,
}: StorageArchiveImportFlowProps) {
  const { loadTenants, setSelectedTenant } = useTenant()
  const [importSource, setImportSource] = useState<ImportSource>(source)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importUrl, setImportUrl] = useState<string | null>(initialArchiveUrl)
  const [importMode, setImportMode] = useState<ImportMode>(lockedMode ?? allowedModes[0] ?? 'new')
  const [targetStorageId, setTargetStorageId] = useState<number | null>(lockedTargetStorage?.id ?? null)
  const [availableStorages, setAvailableStorages] = useState<GraphStorage[]>([])
  const [analysisResult, setAnalysisResult] = useState<StorageMergeAnalysisResponse | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [conflictMode, setConflictMode] = useState<ConflictMode>('archive_wins')
  const [importName, setImportName] = useState(initialName)
  const [embeddingImportMode, setEmbeddingImportMode] = useState<ArchiveEmbeddingImportMode>('preindexed')

  useEffect(() => {
    if (!open) {
      return
    }

    setImportSource(source)
    setImportFile(null)
    setImportUrl(initialArchiveUrl)
    setImportName(initialName)
    setImportMode(lockedMode ?? allowedModes[0] ?? 'new')
    setTargetStorageId(lockedTargetStorage?.id ?? null)
    setAvailableStorages([])
    setAnalysisResult(null)
    setIsProcessing(false)
    setConflictMode('archive_wins')
    setEmbeddingImportMode('preindexed')
  }, [open, source, initialArchiveUrl, initialName, lockedMode, lockedTargetStorage?.id, allowedModes])

  useEffect(() => {
    if (!open || importMode !== 'merge' || lockedTargetStorage) {
      return
    }

    let active = true
    const loadStorages = async () => {
      try {
        const storages = await getGraphStorages()
        if (!active) {
          return
        }
        setAvailableStorages(storages)
        setTargetStorageId((current) => current ?? storages[0]?.id ?? null)
      } catch (error) {
        if (active) {
          console.error('Failed to load storages', error)
        }
      }
    }

    void loadStorages()
    return () => {
      active = false
    }
  }, [open, importMode, lockedTargetStorage])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: (acceptedFiles) => {
      if (acceptedFiles.length > 0) {
        setImportSource('custom')
        setImportUrl(null)
        setImportFile(acceptedFiles[0])
        setImportName(acceptedFiles[0].name.replace('.zip', ''))
        setAnalysisResult(null)
      }
    },
    accept: {
      'application/zip': ['.zip']
    },
    multiple: false
  })

  const archiveSource = importFile || importUrl
  const canSelectNew = allowedModes.includes('new') && !lockedMode
  const canSelectMerge = allowedModes.includes('merge') && !lockedMode
  const effectiveTargetStorageId = lockedTargetStorage?.id ?? targetStorageId

  const handleStartImport = async () => {
    if (!archiveSource) {
      return
    }

    setIsProcessing(true)
    try {
      if (importMode === 'new') {
        const result = await importStorageArchive(
          importName || 'Imported Pack',
          archiveSource,
          embeddingImportMode
        )
        await loadTenants()
        setSelectedTenant(result.storage.id)
        if (embeddingImportMode === 'local_reembed') {
          toast.success('Storage imported without pack vectors. Configure embedding settings and click "Rebuild Embeddings" in Settings.')
        } else {
          toast.success('Successfully created new storage from pack')
        }
        onCompleted?.()
      } else {
        if (!effectiveTargetStorageId) {
          toast.error('Select a target storage first')
          return
        }
        const analysis = await analyzeStorageArchiveMerge(effectiveTargetStorageId, archiveSource)
        setAnalysisResult(analysis)
      }
    } catch (error: any) {
      toast.error(importMode === 'new' ? 'Import failed' : 'Analyze failed', {
        description: error?.message ?? 'Unknown error',
      })
    } finally {
      setIsProcessing(false)
    }
  }

  const handleApplyMerge = async () => {
    if (!effectiveTargetStorageId || !analysisResult) {
      return
    }

    setIsProcessing(true)
    try {
      await applyStorageArchiveMerge(effectiveTargetStorageId, analysisResult.analysis_id, conflictMode)
      await loadTenants()
      toast.success('Successfully merged pack into storage')
      onCompleted?.()
    } catch (error: any) {
      toast.error('Merge failed', { description: error?.message ?? 'Unknown error' })
    } finally {
      setIsProcessing(false)
    }
  }

  return (
    <>
      {!analysisResult ? (
        <div className="space-y-6">
          {importSource === 'custom' ? (
            <div
              {...getRootProps()}
              className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer ${isDragActive ? 'border-primary bg-primary/5' : 'border-border/40 hover:border-primary/20 hover:bg-primary/5'
                }`}
            >
              <input {...getInputProps()} />
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/30">
                <ArchiveRestore className={`h-8 w-8 ${importFile ? 'text-primary' : 'text-muted-foreground/40'}`} />
              </div>
              {importFile ? (
                <div className="space-y-1">
                  <p className="text-sm font-bold text-foreground">{importFile.name}</p>
                  <p className="text-xs text-muted-foreground">{(importFile.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-sm font-bold text-foreground">Click or drag ZIP file here</p>
                  <p className="text-xs text-muted-foreground text-center">Must contain a manifest.json and graph data</p>
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-2xl border ring-1 ring-border/20 bg-muted/20 p-6">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted/40">
                  <ArchiveRestore className="h-6 w-6 text-primary" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-bold text-foreground">{importName || 'Marketplace Pack'}</p>
                  <p className="text-xs text-muted-foreground">Marketplace Knowledge Pack selected for import.</p>
                </div>
              </div>
            </div>
          )}

          {archiveSource && (
            <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-300">
              {(canSelectNew || canSelectMerge) && (
                <div className="space-y-3">
                  <label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">Import Mode</label>
                  <div className={`grid gap-3 ${allowedModes.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}>
                    {allowedModes.includes('new') && (
                      <button
                        onClick={() => setImportMode('new')}
                        className={`flex flex-col items-center gap-2 rounded-xl p-4 transition-all ring-1 ${importMode === 'new' ? 'bg-primary/10 ring-primary shadow-sm' : 'bg-muted/30 ring-border/20 hover:bg-muted/50'
                          }`}
                      >
                        <Plus className={`h-5 w-5 ${importMode === 'new' ? 'text-primary' : 'text-muted-foreground'}`} />
                        <span className="text-xs font-bold">New Storage</span>
                      </button>
                    )}
                    {allowedModes.includes('merge') && (
                      <button
                        onClick={() => setImportMode('merge')}
                        className={`flex flex-col items-center gap-2 rounded-xl p-4 transition-all ring-1 ${importMode === 'merge' ? 'bg-primary/10 ring-primary shadow-sm' : 'bg-muted/30 ring-border/20 hover:bg-muted/50'
                          }`}
                      >
                        <Zap className={`h-5 w-5 ${importMode === 'merge' ? 'text-primary' : 'text-muted-foreground'}`} />
                        <span className="text-xs font-bold">Merge into Existing</span>
                      </button>
                    )}
                  </div>
                </div>
              )}

              {importMode === 'new' ? (
                <div className="space-y-5">
                  <div className="space-y-3">
                    <label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">Storage Name</label>
                    <Input
                      value={importName}
                      onChange={(e) => setImportName(e.target.value)}
                      placeholder="e.g. My Knowledge Base"
                      className="bg-muted/30 border-none ring-1 ring-border/20"
                    />
                  </div>
                  <div className="space-y-3">
                    <label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">Embedding Import</label>
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        onClick={() => setEmbeddingImportMode('preindexed')}
                        className={`text-xs font-bold p-3 rounded-xl ring-1 transition-all ${embeddingImportMode === 'preindexed' ? 'bg-primary text-primary-foreground ring-primary' : 'bg-muted/30 text-muted-foreground ring-border/20'
                          }`}
                      >
                        Use Pack Embeddings
                      </button>
                      <button
                        onClick={() => setEmbeddingImportMode('local_reembed')}
                        className={`text-xs font-bold p-3 rounded-xl ring-1 transition-all ${embeddingImportMode === 'local_reembed' ? 'bg-primary text-primary-foreground ring-primary' : 'bg-muted/30 text-muted-foreground ring-border/20'
                          }`}
                      >
                        Use My Local Setup
                      </button>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      Local setup skips precomputed vectors and uses your current embedding configuration.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">Target Storage</label>
                  {lockedTargetStorage ? (
                    <div className="w-full rounded-xl bg-muted/30 p-3 text-sm font-medium ring-1 ring-border/20">
                      {lockedTargetStorage.name} (ID: {lockedTargetStorage.id})
                    </div>
                  ) : (
                    <select
                      value={targetStorageId || ''}
                      onChange={(e) => setTargetStorageId(Number(e.target.value))}
                      className="w-full rounded-xl bg-muted/30 p-3 text-sm font-medium ring-1 ring-border/20 outline-none focus:ring-primary/50"
                    >
                      {availableStorages.map((storage) => (
                        <option key={storage.id} value={storage.id}>{storage.name} (ID: {storage.id})</option>
                      ))}
                    </select>
                  )}
                </div>
              )}

              <Button
                className="w-full h-12 rounded-xl font-black shadow-lg shadow-primary/20 gap-2"
                disabled={isProcessing}
                onClick={handleStartImport}
              >
                {isProcessing ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-background border-t-transparent" />
                ) : (
                  <ArrowRight className="h-4 w-4" />
                )}
                {importMode === 'new' ? 'Create & Import' : 'Analyze Merge'}
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-6 animate-in fade-in zoom-in-95 duration-300">
          {analysisResult.blocking_issues && analysisResult.blocking_issues.length > 0 ? (
            <div className="rounded-2xl bg-destructive/[0.03] p-6 ring-1 ring-destructive/10 space-y-4">
              <h4 className="text-xs font-black uppercase tracking-widest text-destructive flex items-center gap-2">
                <AlertTriangle className="h-4 w-4" />
                Compatibility Issues
              </h4>
              <div className="space-y-2">
                {analysisResult.blocking_issues.map((issue, idx) => (
                  <div key={idx} className="flex gap-3 text-xs leading-relaxed text-muted-foreground p-3 rounded-xl bg-destructive/5 ring-1 ring-destructive/10">
                    <span className="flex-shrink-0 text-destructive mt-[2px]">•</span>
                    <p className="font-medium">{issue}</p>
                  </div>
                ))}
              </div>
              <p className="text-[10px] font-bold text-muted-foreground italic text-center px-2">
                These settings must match your current storage to allow merging.
              </p>
            </div>
          ) : (
            <div className="rounded-2xl bg-primary/[0.03] p-6 ring-1 ring-primary/10 space-y-4">
              <h4 className="text-xs font-black uppercase tracking-widest text-primary flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4" />
                Analysis Complete
              </h4>
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center p-3 rounded-xl bg-background shadow-sm ring-1 ring-border/5">
                  <p className="text-lg font-black text-primary">{analysisResult.summary.additions}</p>
                  <p className="text-[9px] font-bold text-muted-foreground uppercase">New Info</p>
                </div>
                <div className="text-center p-3 rounded-xl bg-background shadow-sm ring-1 ring-border/5">
                  <p className="text-lg font-black text-muted-foreground">{analysisResult.summary.no_ops}</p>
                  <p className="text-[9px] font-bold text-muted-foreground uppercase">Duplicates</p>
                </div>
                <div className="text-center p-3 rounded-xl bg-background shadow-sm ring-1 ring-border/5">
                  <p className="text-lg font-black text-amber-500">{analysisResult.summary.conflicts}</p>
                  <p className="text-[9px] font-bold text-muted-foreground uppercase">Conflicts</p>
                </div>
              </div>
            </div>
          )}

          <div className="space-y-3">
            <label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">Conflict Resolution Mode</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setConflictMode('archive_wins')}
                className={`text-xs font-bold p-3 rounded-xl ring-1 transition-all ${conflictMode === 'archive_wins' ? 'bg-primary text-primary-foreground ring-primary' : 'bg-muted/30 text-muted-foreground ring-border/20'
                  }`}
              >
                Overwrite Conflicts
              </button>
              <button
                onClick={() => setConflictMode('keep_existing')}
                className={`text-xs font-bold p-3 rounded-xl ring-1 transition-all ${conflictMode === 'keep_existing' ? 'bg-primary text-primary-foreground ring-primary' : 'bg-muted/30 text-muted-foreground ring-border/20'
                  }`}
              >
                Keep Existing Data
              </button>
            </div>
          </div>

          <div className="flex gap-3">
            <Button
              variant="ghost"
              className="flex-1 h-12 rounded-xl font-bold"
              onClick={() => setAnalysisResult(null)}
              disabled={isProcessing}
            >
              Back
            </Button>
            <Button
              className="flex-[2] h-12 rounded-xl font-black shadow-lg shadow-primary/20 gap-2"
              disabled={isProcessing || (analysisResult.blocking_issues && analysisResult.blocking_issues.length > 0)}
              onClick={handleApplyMerge}
            >
              {isProcessing ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-background border-t-transparent" />
              ) : (
                <Zap className="h-4 w-4" />
              )}
              Apply Merge
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
