import { useMemo, useState } from 'react'
import { Card, CardTitle } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
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
} from 'lucide-react'
import { toast } from 'sonner'
import { useTenant } from '@/contexts/TenantContext'
import { StorageArchiveImportFlow } from '@/components/StorageArchiveImportFlow'
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
    reasoningSnippet: 'State Graph -> Node Function -> Edge Logic -> Persistent Store',
    bestFor: ['AI Developers', 'LangChain Contributors', 'Systems Architects'],
    author: 'Retriqs',
    verified: true,
    color: 'from-blue-600/30 via-indigo-500/20 to-teal-500/30',
    repos: ['https://github.com/langchain-ai/docs.git'],
    doc_urls: [
      'https://docs.langchain.com/oss/python/langchain/overview',
      'https://docs.langchain.com/oss/python/langchain/agents',
      'https://docs.langchain.com/oss/python/langchain/tools',
      'https://docs.langchain.com/oss/python/langchain/runtime',
      'https://docs.langchain.com/oss/python/langchain/middleware/overview',
      'https://docs.langchain.com/oss/python/langchain/short-term-memory',
      'https://docs.langchain.com/oss/python/langchain/long-term-memory',
      'https://docs.langchain.com/oss/python/langchain/retrieval',
      'https://docs.langchain.com/oss/python/langgraph/overview',
      'https://docs.langchain.com/oss/python/langgraph/install',
      'https://docs.langchain.com/oss/python/langgraph/graph-api',
      'https://docs.langchain.com/oss/python/langgraph/pregel',
      'https://docs.langchain.com/oss/python/langgraph/add-memory',
      'https://docs.langchain.com/oss/python/langgraph/streaming'
    ],
    archiveUrl: LANGCHAIN_MARKETPLACE_ARCHIVE_URL
  }
]

export default function MarketplacePage() {
  const { loadTenants } = useTenant()
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('All')
  const [detailPack, setDetailPack] = useState<RagItem | null>(null)
  const [isImportingOpen, setIsImportingOpen] = useState(false)
  const [importSource, setImportSource] = useState<'marketplace' | 'custom'>('custom')
  const [selectedArchiveUrl, setSelectedArchiveUrl] = useState<string | null>(null)
  const [importName, setImportName] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)

  const handleInstall = (pack: RagItem) => {
    if (!pack.archiveUrl) {
      toast.error('Installation failed', {
        description: 'No archive URL found for this Knowledge Pack.'
      })
      return
    }

    setImportSource('marketplace')
    setSelectedArchiveUrl(pack.archiveUrl)
    setImportName(pack.name)
    setIsImportingOpen(true)
  }

  const filteredPacks = useMemo(() => {
    return FEATURED_PACKS.filter((pack) => {
      const matchesSearch =
        pack.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        pack.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        pack.tagline.toLowerCase().includes(searchQuery.toLowerCase())

      const matchesCategory = selectedCategory === 'All' || pack.category === selectedCategory

      return matchesSearch && matchesCategory
    })
  }, [searchQuery, selectedCategory])

  const categories = useMemo(() => {
    return ['All', ...new Set(FEATURED_PACKS.map((pack) => pack.category))]
  }, [])

  const resetImport = () => {
    setImportSource('custom')
    setSelectedArchiveUrl(null)
    setImportName('')
    setIsProcessing(false)
  }

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto scrollbar-thin">
      <div className="mx-auto w-full max-w-7xl space-y-12 p-6 md:p-10">
        <div className="relative space-y-6 py-8 text-center">
          <div className="absolute -top-24 left-1/2 -z-10 h-64 w-64 -translate-x-1/2 rounded-full bg-primary/20 blur-[120px]" />

          <h1 className="mx-auto max-w-3xl text-5xl font-black tracking-tight text-foreground lg:text-7xl">
            Explore <span className="text-primary">Knowledge Packs</span>
          </h1>

          <p className="mx-auto max-w-2xl text-lg leading-relaxed text-muted-foreground opacity-80">
            Don't just search-understand. Deploy structured reasoning systems designed for complex problem-solving and architectural clarity.
          </p>

          <div className="mx-auto mt-10 max-w-xl">
            <div className="group relative">
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

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {filteredPacks.map((pack) => (
            <Card key={pack.id} className="glass-card group relative flex h-full flex-col overflow-hidden border-none shadow-xl transition-all hover:-translate-y-2">
              <div className={`h-1.5 w-full bg-gradient-to-r ${pack.color}`} />

              <div className="flex h-full flex-col space-y-6 p-6">
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
                    <CardTitle className="text-lg leading-tight font-black tracking-tight">
                      {pack.name}
                    </CardTitle>
                    {pack.verified && <ShieldCheck className="h-4 w-4 shrink-0 text-primary" />}
                  </div>
                  <p className="line-clamp-1 text-xs font-bold italic text-foreground/70">{pack.tagline}</p>
                </div>

                <p className="line-clamp-4 text-xs leading-relaxed text-muted-foreground">
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
                      className="h-8 rounded-lg bg-muted/30 text-[10px] font-bold hover:bg-primary/10 hover:text-primary"
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

          <Card className="flex min-h-[400px] flex-col items-center justify-center border-2 border-dashed border-border/40 bg-transparent p-6 text-center transition-all hover:border-primary/40 hover:bg-primary/5">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/30 shadow-inner">
              <Plus className="h-8 w-8 text-muted-foreground/40" />
            </div>
            <h3 className="text-lg font-black tracking-tight">Custom Solution?</h3>
            <p className="mt-2 max-w-[200px] text-xs text-muted-foreground opacity-70">
              Import a local ZIP or transform your own docs.
            </p>
            <Button
              variant="outline"
              className="mt-6 h-10 gap-2 rounded-xl border-primary/20 px-4 text-xs font-bold hover:bg-primary/5"
              onClick={() => {
                setImportSource('custom')
                setSelectedArchiveUrl(null)
                setIsImportingOpen(true)
              }}
            >
              <ArchiveRestore className="h-3.5 w-3.5" />
              Import ZIP
            </Button>
          </Card>

          <Dialog open={!!detailPack} onOpenChange={(open) => !open && setDetailPack(null)}>
            <DialogContent className="max-h-[95vh] max-w-7xl overflow-hidden border-none bg-background/98 p-0 shadow-2xl backdrop-blur-2xl flex flex-col">
              {detailPack && (
                <div className="flex h-full flex-col overflow-hidden">
                  <div className={`h-2 w-full bg-gradient-to-r ${detailPack.color}`} />

                  <div className="flex-1 space-y-8 overflow-y-auto scrollbar-thin p-8 md:p-10">
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
                          <DialogDescription className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-primary/80">
                            {detailPack.category}
                            {detailPack.verified && <ShieldCheck className="h-4 w-4" />}
                          </DialogDescription>
                        </div>
                      </div>
                      <div className="space-y-2">
                        <p className="border-l-4 border-primary/20 pl-4 text-xl font-bold italic text-foreground">{detailPack.tagline}</p>
                        <p className="text-base leading-relaxed text-muted-foreground">{detailPack.description}</p>
                      </div>
                    </DialogHeader>

                    <div className="grid grid-cols-1 gap-10 md:grid-cols-3">
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
                            {detailPack.capabilities.map((capability, index) => (
                              <li key={index} className="flex gap-3 text-sm leading-snug text-muted-foreground">
                                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                                {capability}
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="space-y-3">
                          <h4 className="text-[10px] font-black uppercase tracking-widest tracking-wider text-muted-foreground/60">Target Audience</h4>
                          <div className="flex flex-wrap gap-2">
                            {detailPack.bestFor.map((target) => (
                              <div key={target} className="inline-flex items-center gap-2 rounded-xl bg-muted/50 px-3 py-1.5 text-[10px] font-bold text-foreground ring-1 ring-border/5">
                                <CheckCircle2 className="h-3 w-3 text-primary" />
                                {target}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      <div className="space-y-4 text-left">
                        <h4 className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-primary">
                          <HelpCircle className="h-3.5 w-3.5" />
                          Example Queries
                        </h4>
                        <div className="space-y-2.5">
                          {detailPack.exampleQueries.map((query, index) => (
                            <div key={index} className="rounded-2xl bg-muted/40 p-3 text-xs leading-relaxed font-medium text-muted-foreground ring-1 ring-border/10 transition-colors hover:bg-muted/60">
                              "{query}"
                            </div>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-8">
                        {detailPack.repos && detailPack.repos.length > 0 && (
                          <div className="space-y-3">
                            <h4 className="text-[10px] font-black uppercase tracking-widest tracking-wider text-muted-foreground/60">GitHub Repositories</h4>
                            <div className="flex flex-col gap-2">
                              {detailPack.repos.map((repo) => (
                                <a
                                  key={repo}
                                  href={repo}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="group inline-flex truncate items-center gap-2 text-xs font-bold text-primary hover:underline"
                                >
                                  <Code2 className="h-3.5 w-3.5 transition-transform group-hover:scale-110" />
                                  {repo.split('/').pop()?.replace('.git', '') || repo}
                                </a>
                              ))}
                            </div>
                          </div>
                        )}

                        {detailPack.doc_urls && detailPack.doc_urls.length > 0 && (
                          <div className="space-y-3">
                            <h4 className="text-[10px] font-black uppercase tracking-widest tracking-wider text-muted-foreground/60">Indexed Documentation</h4>
                            <div className="flex max-h-44 flex-col gap-1.5 overflow-y-auto border-l-2 border-primary/20 py-0.5 pl-4 pr-4 scrollbar-thin">
                              {detailPack.doc_urls.map((url) => {
                                const label = url.split('/').filter(Boolean).pop() || url
                                return (
                                  <a
                                    key={url}
                                    href={url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="break-all text-[10px] font-medium text-foreground/80 transition-colors hover:text-primary"
                                    title={url}
                                  >
                                    {label.charAt(0).toUpperCase() + label.slice(1).replace(/-/g, ' ')}
                                  </a>
                                )
                              })}
                            </div>
                          </div>
                        )}

                        <div className="border-t border-border/20 pt-4">
                          <p className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/60">Verified Publisher</p>
                          <p className="mt-0.5 text-sm font-black text-foreground">{detailPack.author}</p>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="sticky bottom-0 z-20 flex items-center justify-end border-t border-border/20 bg-background/80 p-6 backdrop-blur-xl md:p-8">
                    <Button
                      className="group h-12 gap-3 rounded-2xl px-8 text-sm font-black shadow-lg shadow-primary/20 transition-all hover:translate-y-[-1px] active:translate-y-0"
                      onClick={() => {
                        handleInstall(detailPack)
                        setDetailPack(null)
                      }}
                      disabled={isProcessing}
                    >
                      {isProcessing ? 'Installing Knowledge Pack...' : 'Install Knowledge Pack'}
                      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                    </Button>
                  </div>
                </div>
              )}
            </DialogContent>
          </Dialog>

          <Dialog
            open={isImportingOpen}
            onOpenChange={(open) => {
              if (!open) {
                resetImport()
              }
              setIsImportingOpen(open)
            }}
          >
            <DialogContent className="max-h-[90vh] max-w-xl overflow-hidden border-none bg-background/98 p-0 shadow-2xl backdrop-blur-2xl flex flex-col">
              <div className="flex h-full flex-col space-y-8 overflow-y-auto scrollbar-thin p-8">
                <DialogHeader>
                  <DialogTitle className="text-2xl font-black">Import Knowledge Pack</DialogTitle>
                  <DialogDescription>
                    Deploy a pre-indexed knowledge graph or merge it with your existing data.
                  </DialogDescription>
                </DialogHeader>

                <StorageArchiveImportFlow
                  open={isImportingOpen}
                  source={importSource}
                  initialArchiveUrl={selectedArchiveUrl}
                  initialName={importName}
                  onCompleted={async () => {
                    setIsProcessing(false)
                    setIsImportingOpen(false)
                    resetImport()
                    await loadTenants()
                  }}
                />
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </div>
  )
}
