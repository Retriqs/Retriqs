import { useState, useMemo } from 'react'
import { Card, CardTitle } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import {
  Search,
  ShieldCheck,
  ArchiveRestore,
  Plus,
  Cloud,
  Code2,
  HelpCircle,
  Zap,
  CheckCircle2,
  ArrowRight,
  AlertTriangle
} from 'lucide-react'
import { toast } from 'sonner'
import Input from '@/components/ui/Input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/Dialog'
import {
  importStorageArchive,
  analyzeStorageArchiveMerge,
  applyStorageArchiveMerge,
  getGraphStorages,
  ArchiveEmbeddingImportMode,
  GraphStorage,
  StorageMergeAnalysisResponse
} from '@/api/retriqs'
import { useDropzone } from 'react-dropzone'
import { useTenant } from '@/contexts/TenantContext'
import { LANGCHAIN_MARKETPLACE_ARCHIVE_URL } from '@/features/marketplaceConfig'

interface RagItem {
  id: string
  name: string
  tagline: string
  description: string
  category: string
  capabilities: string[]
  exampleQueries: string[]
  reasoningSnippet: string
  bestFor: string[]
  author: string
  verified: boolean
  color: string
  repos?: string[]
  doc_urls?: string[]
  archiveUrl?: string
}

const FEATURED_PACKS: RagItem[] = [
  {
    id: 'langchain-beta-v2',
    name: 'LangChain AI Knowledge Pack',
    tagline: 'The starter Knowledge Graph for LangChain & LangGraph',
    description: 'Knowledge graph with 7 documents on LangChain',
    category: 'Development',
    capabilities: [
      'Full LangChain & LangGraph documentation indexing',
      'Understands Agentic workflows and state management',
      'Advanced tool-use and retrieval reasoning',
      'Memory and persistence implementation mapping',
      'Pre-processed from official GitHub docs and URLs'
    ],
    exampleQueries: [
      'Explain the relationship between Pregel and LangGraph state management.',
      'How do I implement long-term memory in a multi-agent system?',
      'Show me the flow from Tool Execution back to Agent Node.',
      'Why is my streaming response not including intermediate steps?',
      'How to bridge LangChain retrieval with LangGraph persistence?'
    ],
    reasoningSnippet: 'State Graph → Node Function → Edge Logic → Persistent Store',
    bestFor: ['AI Developers', 'LangChain Contributors', 'Systems Architects'],
    author: 'Retriqs',
    verified: true,
    color: 'from-blue-600/30 via-indigo-500/20 to-teal-500/30',
    repos: ["https://github.com/langchain-ai/docs.git"],
    doc_urls: [
      "https://docs.langchain.com/oss/python/langchain/overview",
      "https://docs.langchain.com/oss/python/langchain/agents",
      "https://docs.langchain.com/oss/python/langchain/tools",
      "https://docs.langchain.com/oss/python/langchain/runtime",
      "https://docs.langchain.com/oss/python/langchain/middleware/overview",
      "https://docs.langchain.com/oss/python/langchain/short-term-memory",
      "https://docs.langchain.com/oss/python/langchain/long-term-memory",
      "https://docs.langchain.com/oss/python/langchain/retrieval",
      "https://docs.langchain.com/oss/python/langgraph/overview",
      "https://docs.langchain.com/oss/python/langgraph/install",
      "https://docs.langchain.com/oss/python/langgraph/graph-api",
      "https://docs.langchain.com/oss/python/langgraph/pregel",
      "https://docs.langchain.com/oss/python/langgraph/add-memory",
      "https://docs.langchain.com/oss/python/langgraph/streaming"
    ],
    archiveUrl: LANGCHAIN_MARKETPLACE_ARCHIVE_URL
  }
]


export default function MarketplacePage() {
  const { loadTenants, setSelectedTenant } = useTenant()
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('All')
  const [detailPack, setDetailPack] = useState<RagItem | null>(null)
  const [isImportingOpen, setIsImportingOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importUrl, setImportUrl] = useState<string | null>(null)
  const [importMode, setImportMode] = useState<'new' | 'merge'>('new')
  const [targetStorageId, setTargetStorageId] = useState<number | null>(null)
  const [availableStorages, setAvailableStorages] = useState<GraphStorage[]>([])
  const [analysisResult, setAnalysisResult] = useState<StorageMergeAnalysisResponse | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [conflictMode, setConflictMode] = useState<'archive_wins' | 'keep_existing'>('archive_wins')
  const [importName, setImportName] = useState('')
  const [embeddingImportMode, setEmbeddingImportMode] = useState<ArchiveEmbeddingImportMode>('preindexed')

  const handleInstall = async (pack: RagItem) => {
    if (!pack.archiveUrl) {
      toast.error('Installation failed', {
        description: 'No archive URL found for this Knowledge Pack.'
      })
      return
    }

    setImportUrl(pack.archiveUrl)
    setImportName(pack.name)
    await loadStorages()
    setIsImportingOpen(true)
  }

  const filteredPacks = useMemo(() => {
    return FEATURED_PACKS.filter(pack => {
      const matchesSearch =
        pack.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        pack.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        pack.tagline.toLowerCase().includes(searchQuery.toLowerCase())

      const matchesCategory = selectedCategory === 'All' || pack.category === selectedCategory

      return matchesSearch && matchesCategory
    })
  }, [searchQuery, selectedCategory])

  const categories = useMemo(() => {
    return ['All', ...new Set(FEATURED_PACKS.map(p => p.category))]
  }, [])

  const loadStorages = async () => {
    try {
      const storages = await getGraphStorages()
      setAvailableStorages(storages)
      if (storages.length > 0 && !targetStorageId) {
        setTargetStorageId(storages[0].id)
      }
    } catch (error) {
      console.error('Failed to load storages', error)
    }
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: (acceptedFiles) => {
      if (acceptedFiles.length > 0) {
        setImportUrl(null)
        setImportFile(acceptedFiles[0])
        setImportName(acceptedFiles[0].name.replace('.zip', ''))
      }
    },
    accept: {
      'application/zip': ['.zip']
    },
    multiple: false
  })

  const handleStartImport = async () => {
    const fileOrUrl = importFile || importUrl
    if (!fileOrUrl) return
    setIsProcessing(true)

    try {
      if (importMode === 'new') {
        const result = await importStorageArchive(
          importName || 'Imported Pack',
          fileOrUrl,
          embeddingImportMode
        )
        await loadTenants()
        setSelectedTenant(result.storage.id)
        if (embeddingImportMode === 'local_reembed') {
          toast.success('Storage imported without pack vectors. Configure embedding settings and click "Rebuild Embeddings" in Settings.')
        } else {
          toast.success('Successfully created new storage from pack')
        }
        setIsImportingOpen(false)
        resetImport()
      } else {
        if (!targetStorageId) return
        const analysis = await analyzeStorageArchiveMerge(targetStorageId, fileOrUrl)
        setAnalysisResult(analysis)
      }
    } catch (error: any) {
      toast.error('Import failed', { description: error.message })
    } finally {
      setIsProcessing(false)
    }
  }

  const handleApplyMerge = async () => {
    if (!targetStorageId || !analysisResult) return
    setIsProcessing(true)
    try {
      await applyStorageArchiveMerge(targetStorageId, analysisResult.analysis_id, conflictMode)
      toast.success('Successfully merged pack into storage')
      setIsImportingOpen(false)
      resetImport()
    } catch (error: any) {
      toast.error('Merge failed', { description: error.message })
    } finally {
      setIsProcessing(false)
    }
  }

  const resetImport = () => {
    setImportFile(null)
    setImportUrl(null)
    setImportMode('new')
    setAnalysisResult(null)
    setImportName('')
    setEmbeddingImportMode('preindexed')
  }


  return (
    <div className="flex h-full w-full flex-col overflow-y-auto scrollbar-thin">
      <div className="mx-auto w-full max-w-7xl space-y-12 p-6 md:p-10">

        {/* Hero Section */}
        <div className="relative space-y-6 text-center py-8">
          <div className="absolute -top-24 left-1/2 -z-10 h-64 w-64 -translate-x-1/2 rounded-full bg-primary/20 blur-[120px]" />

          <h1 className="mx-auto max-w-3xl text-5xl font-black tracking-tight text-foreground lg:text-7xl">
            Explore <span className="text-primary">Knowledge Packs</span>
          </h1>

          <p className="mx-auto max-w-2xl text-lg leading-relaxed text-muted-foreground opacity-80">
            Don't just search—understand. Deploy structured reasoning systems designed for complex problem-solving and architectural clarity.
          </p>

          <div className="mx-auto mt-10 max-w-xl">
            <div className="relative group">
              <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary" />
              <Input
                type="text"
                placeholder="Find a solution for your problem..."
                className="h-14 w-full rounded-2xl border-none bg-muted/40 pl-12 pr-6 text-base ring-1 ring-border/50 transition-all focus:bg-muted/60 focus:outline-none focus:ring-2 focus:ring-primary/50"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* Categories Bar */}
        <div className="flex flex-wrap items-center justify-center gap-3">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`rounded-full px-5 py-2 text-xs font-bold transition-all ring-1 ${selectedCategory === cat
                ? 'bg-primary text-primary-foreground ring-primary shadow-lg shadow-primary/20'
                : 'bg-muted/30 text-muted-foreground ring-border/20 hover:bg-primary/10 hover:text-primary hover:ring-primary/30'
                }`}
            >
              {cat === 'All' ? 'All Solutions' : cat}
            </button>
          ))}
        </div>

        {/* Packs Grid */}
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {filteredPacks.map((pack) => (
            <Card key={pack.id} className="group relative flex flex-col h-full overflow-hidden border-none shadow-xl transition-all hover:-translate-y-2 glass-card">
              <div className={`h-1.5 w-full bg-gradient-to-r ${pack.color}`} />

              <div className="flex flex-col p-6 h-full space-y-6">
                <div className="flex items-start justify-between">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-background shadow-lg ring-1 ring-border/20">
                    {pack.id === 'langchain-beta-v2' ? (
                      <img src="/Langchain.png" alt="LangChain Logo" className="h-6 w-6 object-contain" />
                    ) : (
                      <>
                        {pack.category === 'Development' && <Code2 className="h-6 w-6 text-blue-500" />}
                        {pack.category === 'Cloud' && <Cloud className="h-6 w-6 text-sky-500" />}
                      </>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-lg font-black tracking-tight leading-tight">
                      {pack.name}
                    </CardTitle>
                    {pack.verified && <ShieldCheck className="h-4 w-4 text-primary shrink-0" />}
                  </div>
                  <p className="text-xs font-bold text-foreground/70 italic line-clamp-1">{pack.tagline}</p>
                </div>

                <p className="text-xs leading-relaxed text-muted-foreground line-clamp-4">
                  {pack.description}
                </p>

                <div className="mt-auto flex items-center justify-between border-t border-border/20 pt-4">
                  <div className="text-left">
                    <p className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/60">Publisher</p>
                    <p className="text-[10px] font-bold">{pack.author}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 rounded-lg text-[10px] font-bold bg-muted/30 hover:bg-primary/10 hover:text-primary"
                      onClick={() => setDetailPack(pack)}
                    >
                      Details
                    </Button>
                    <Button
                      size="sm"
                      className="h-8 rounded-lg px-4 text-[10px] font-bold shadow-lg shadow-primary/20"
                      onClick={() => handleInstall(pack)}
                      disabled={isProcessing}
                    >
                      {isProcessing ? 'Installing...' : 'Install'}
                      <ArrowRight className="ml-1.5 h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
            </Card>
          ))}

          {/* Import Card */}
          <Card className="flex flex-col items-center justify-center border-2 border-dashed border-border/40 bg-transparent p-6 text-center transition-all hover:border-primary/40 hover:bg-primary/5 min-h-[400px]">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/30 shadow-inner">
              <Plus className="h-8 w-8 text-muted-foreground/40" />
            </div>
            <h3 className="text-lg font-black tracking-tight">Custom Solution?</h3>
            <p className="mt-2 max-w-[200px] text-xs text-muted-foreground opacity-70">
              Import a local ZIP or transform your own docs.
            </p>
            <Button
              variant="outline"
              className="mt-6 gap-2 border-primary/20 font-bold hover:bg-primary/5 rounded-xl h-10 px-4 text-xs"
              onClick={() => {
                loadStorages()
                setIsImportingOpen(true)
              }}
            >
              <ArchiveRestore className="h-3.5 w-3.5" />
              Import ZIP
            </Button>
          </Card>
          {/* Detail Dialog */}
          <Dialog open={!!detailPack} onOpenChange={(open) => !open && setDetailPack(null)}>
            <DialogContent className="max-w-7xl bg-background/98 backdrop-blur-2xl border-none shadow-2xl overflow-hidden p-0 max-h-[95vh] flex flex-col">
              {detailPack && (
                <div className="flex flex-col h-full overflow-hidden">
                  <div className={`h-2 w-full bg-gradient-to-r ${detailPack.color}`} />

                  {/* Scrollable Content Area */}
                  <div className="flex-1 overflow-y-auto scrollbar-thin p-8 md:p-10 space-y-8">
                    <DialogHeader className="space-y-4">
                      <div className="flex items-center gap-4">
                        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted shadow-lg ring-1 ring-border/20">
                          {detailPack.id === 'langchain-beta-v2' ? (
                            <img src="/Langchain.png" alt="LangChain Logo" className="h-8 w-8 object-contain" />
                          ) : (
                            <>
                              {detailPack.category === 'Development' && <Code2 className="h-8 w-8 text-blue-500" />}
                              {detailPack.category === 'Cloud' && <Cloud className="h-8 w-8 text-sky-500" />}
                            </>
                          )}
                        </div>
                        <div className="space-y-0.5">
                          <DialogTitle className="text-3xl font-black">{detailPack.name}</DialogTitle>
                          <DialogDescription className="text-sm font-bold text-primary/80 uppercase tracking-widest flex items-center gap-2">
                            {detailPack.category}
                            {detailPack.verified && <ShieldCheck className="h-4 w-4" />}
                          </DialogDescription>
                        </div>
                      </div>
                      <div className="space-y-2">
                        <p className="text-xl font-bold text-foreground italic border-l-4 border-primary/20 pl-4">{detailPack.tagline}</p>
                        <p className="text-muted-foreground leading-relaxed text-base">{detailPack.description}</p>
                      </div>
                    </DialogHeader>

                    {/* 3-Column Content Grid */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
                      {/* Column 1: Capabilities & Audience */}
                      <div className="space-y-8">
                        <div className="space-y-4">
                          <h4 className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-primary">
                            {detailPack.id === 'langchain-beta-v2' ? (
                              <img src="/Langchain.png" alt="" className="h-3.5 w-3.5 object-contain" />
                            ) : (
                              <Zap className="h-3.5 w-3.5" />
                            )}
                            Key Capabilities
                          </h4>
                          <ul className="space-y-2">
                            {detailPack.capabilities.map((cap: string, i: number) => (
                              <li key={i} className="flex gap-3 text-sm text-muted-foreground leading-snug">
                                <CheckCircle2 className="h-4 w-4 shrink-0 text-primary mt-0.5" />
                                {cap}
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="space-y-3">
                          <h4 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60 tracking-wider">Target Audience</h4>
                          <div className="flex flex-wrap gap-2">
                            {detailPack.bestFor.map((target: string) => (
                              <div key={target} className="inline-flex items-center gap-2 rounded-xl bg-muted/50 px-3 py-1.5 text-[10px] font-bold text-foreground ring-1 ring-border/5">
                                <CheckCircle2 className="h-3 w-3 text-primary" />
                                {target}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Column 2: Suggested Queries */}
                      <div className="space-y-4 text-left">
                        <h4 className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-primary">
                          <HelpCircle className="h-3.5 w-3.5" />
                          Example Queries
                        </h4>
                        <div className="space-y-2.5">
                          {detailPack.exampleQueries.map((query: string, i: number) => (
                            <div key={i} className="rounded-2xl bg-muted/40 p-3 text-xs font-medium text-muted-foreground ring-1 ring-border/10 leading-relaxed hover:bg-muted/60 transition-colors">
                              "{query}"
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Column 3: Sources */}
                      <div className="space-y-8">
                        {detailPack.repos && detailPack.repos.length > 0 && (
                          <div className="space-y-3">
                            <h4 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60 tracking-wider">GitHub Repositories</h4>
                            <div className="flex flex-col gap-2">
                              {detailPack.repos.map((repo) => (
                                <a
                                  key={repo}
                                  href={repo}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-2 text-xs font-bold text-primary hover:underline group truncate"
                                >
                                  <Code2 className="h-3.5 w-3.5 group-hover:scale-110 transition-transform" />
                                  {repo.split('/').pop()?.replace('.git', '') || repo}
                                </a>
                              ))}
                            </div>
                          </div>
                        )}

                        {detailPack.doc_urls && detailPack.doc_urls.length > 0 && (
                          <div className="space-y-3">
                            <h4 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60 tracking-wider">Indexed Documentation</h4>
                            <div className="flex flex-col gap-1.5 max-h-44 overflow-y-auto scrollbar-thin pr-4 border-l-2 border-primary/20 pl-4 py-0.5">
                              {detailPack.doc_urls.map((url) => {
                                const label = url.split('/').filter(Boolean).pop() || url;
                                return (
                                  <a
                                    key={url}
                                    href={url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-[10px] font-medium text-foreground/80 hover:text-primary transition-colors break-all"
                                    title={url}
                                  >
                                    {label.charAt(0).toUpperCase() + label.slice(1).replace(/-/g, ' ')}
                                  </a>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        <div className="pt-4 border-t border-border/20">
                          <p className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/60">Verified Publisher</p>
                          <p className="text-sm font-black text-foreground mt-0.5">{detailPack.author}</p>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Sticky Footer for Action Button */}
                  <div className="sticky bottom-0 bg-background/80 backdrop-blur-xl border-t border-border/20 p-6 md:p-8 flex items-center justify-end z-20">
                    <Button
                      className="rounded-2xl px-8 h-12 font-black shadow-lg shadow-primary/20 gap-3 text-sm hover:translate-y-[-1px] active:translate-y-0 transition-all group"
                      onClick={() => {
                        handleInstall(detailPack);
                        setDetailPack(null);
                      }}
                      disabled={isProcessing}
                    >
                      {isProcessing ? 'Installing Knowledge Pack...' : 'Install Knowledge Pack'}
                      <ArrowRight className="h-4 w-4 group-hover:translate-x-1 transition-transform" />
                    </Button>
                  </div>
                </div>
              )}
            </DialogContent>
          </Dialog>



          {/* Import Dialog */}
          <Dialog open={isImportingOpen} onOpenChange={(open) => {
            if (!open) resetImport()
            setIsImportingOpen(open)
          }}>
            <DialogContent className="max-w-xl bg-background/98 backdrop-blur-2xl border-none shadow-2xl overflow-hidden p-0 max-h-[90vh] flex flex-col">
              <div className="flex flex-col h-full overflow-y-auto scrollbar-thin p-8 space-y-8">
                <DialogHeader>
                  <DialogTitle className="text-2xl font-black">Import Knowledge Pack</DialogTitle>
                  <DialogDescription>
                    Deploy a pre-indexed knowledge graph or merge it with your existing data.
                  </DialogDescription>
                </DialogHeader>

                {!analysisResult ? (
                  <div className="space-y-6">
                    {/* Dropzone */}
                    <div
                      {...getRootProps()}
                      className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer ${isDragActive ? 'border-primary bg-primary/5' : 'border-border/40 hover:border-primary/20 hover:bg-primary/5'
                        }`}
                    >
                      <input {...getInputProps()} />
                      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/30 mb-4">
                        <ArchiveRestore className={`h-8 w-8 ${importFile || importUrl ? 'text-primary' : 'text-muted-foreground/40'}`} />
                      </div>
                      {importFile ? (
                        <div className="space-y-1">
                          <p className="text-sm font-bold text-foreground">{importFile.name}</p>
                          <p className="text-xs text-muted-foreground">{(importFile.size / 1024 / 1024).toFixed(2)} MB</p>
                        </div>
                      ) : importUrl ? (
                        <div className="space-y-1">
                          <p className="text-sm font-bold text-foreground">{importName || 'Marketplace_Pack'}.zip</p>
                          <p className="text-xs text-muted-foreground">Marketplace Knowledge Pack</p>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <p className="text-sm font-bold text-foreground">Click or drag ZIP file here</p>
                          <p className="text-xs text-muted-foreground text-center">Must contain a manifest.json and graph data</p>
                        </div>
                      )}
                    </div>

                    {(importFile || importUrl) && (
                      <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-300">
                        <div className="space-y-3">
                          <label className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">Import Mode</label>
                          <div className="grid grid-cols-2 gap-3">
                            <button
                              onClick={() => setImportMode('new')}
                              className={`flex flex-col items-center gap-2 rounded-xl p-4 transition-all ring-1 ${importMode === 'new' ? 'bg-primary/10 ring-primary shadow-sm' : 'bg-muted/30 ring-border/20 hover:bg-muted/50'
                                }`}
                            >
                              <Plus className={`h-5 w-5 ${importMode === 'new' ? 'text-primary' : 'text-muted-foreground'}`} />
                              <span className="text-xs font-bold">New Storage</span>
                            </button>
                            <button
                              onClick={() => setImportMode('merge')}
                              className={`flex flex-col items-center gap-2 rounded-xl p-4 transition-all ring-1 ${importMode === 'merge' ? 'bg-primary/10 ring-primary shadow-sm' : 'bg-muted/30 ring-border/20 hover:bg-muted/50'
                                }`}
                            >
                              <Zap className={`h-5 w-5 ${importMode === 'merge' ? 'text-primary' : 'text-muted-foreground'}`} />
                              <span className="text-xs font-bold">Merge into Existing</span>
                            </button>
                          </div>
                        </div>

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
                            <select
                              value={targetStorageId || ''}
                              onChange={(e) => setTargetStorageId(Number(e.target.value))}
                              className="w-full rounded-xl bg-muted/30 p-3 text-sm font-medium ring-1 ring-border/20 outline-none focus:ring-primary/50"
                            >
                              {availableStorages.map(s => (
                                <option key={s.id} value={s.id}>{s.name} (ID: {s.id})</option>
                              ))}
                            </select>
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
              </div>
            </DialogContent>
          </Dialog>

        </div>
      </div>
    </div>
  )
}
