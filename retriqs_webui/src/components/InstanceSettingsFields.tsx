import React, { useState } from 'react'
import Input from '@/components/ui/Input'
import Text from '@/components/ui/Text'
import { LitellmModelSelect } from '@/components/LitellmModelSelect'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue
} from '@/components/ui/Select'
import { Key, Globe, Maximize2, Hash, Database, Zap, Layout, Files, HardDrive } from 'lucide-react'
import {
    disconnectOpenAICodexAuth,
    getOpenAICodexAuthFlowStatus,
    getOpenAICodexAuthStatus,
    OpenAICodexAuthStatus,
    SettingsUpdateRequest,
    startOpenAICodexAuth
} from '@/api/retriqs'
import { isRestrictedStorageProvider } from '@/lib/editionPolicy'
import { UpgradePromptDialog } from '@/components/UpgradePromptDialog'
import Checkbox from '@/components/ui/Checkbox'
import Button from '@/components/ui/Button'
import { toast } from 'sonner'
import { errorMessage } from '@/lib/utils'
import { openExternalUrl } from '@/lib/runtime'

interface InstanceSettingsFieldsProps {
    formData: SettingsUpdateRequest
    setFormData: React.Dispatch<React.SetStateAction<SettingsUpdateRequest>>
    disabledSections?: ('llm' | 'embedding' | 'storage')[]
    apiKeyEditableWhenDisabled?: boolean
}

export const InstanceSettingsFields: React.FC<InstanceSettingsFieldsProps> = ({
    formData,
    setFormData,
    disabledSections = [],
    apiKeyEditableWhenDisabled = false
}) => {
    const DEFAULT_OLLAMA_LLM_MODEL = 'qwen3:0.6B'
    const DEFAULT_OLLAMA_EMBEDDING_MODEL = 'bge-m3:latest'
    const DEFAULT_OLLAMA_EMBEDDING_DIM = 1024

    const [showUpgradeDialog, setShowUpgradeDialog] = useState(false)
    const [upgradeReason, setUpgradeReason] = useState('')
    const [openAICodexAuth, setOpenAICodexAuth] = useState<OpenAICodexAuthStatus | null>(null)
    const [openAICodexBusy, setOpenAICodexBusy] = useState(false)

    const handleChange = (field: keyof SettingsUpdateRequest, value: any) => {
        setFormData((prev) => ({ ...prev, [field]: value }))
    }

    const handleChanges = (updates: Partial<SettingsUpdateRequest>) => {
        setFormData((prev) => ({ ...prev, ...updates }))
    }

    const normalizeEmbeddingModel = (model: string) => {
        if (!model) return ''
        if (model.startsWith('ollama/')) return model.slice('ollama/'.length)
        return model
    }

    const inferEmbeddingDim = (model: string, metadata?: any): number => {
        const metadataDim = Number(metadata?.output_vector_size ?? 0)
        if (metadataDim > 0) return metadataDim

        const normalizedModel = normalizeEmbeddingModel(model).toLowerCase()
        if (normalizedModel === 'bge-m3:latest' || normalizedModel.startsWith('bge-m3')) {
            return DEFAULT_OLLAMA_EMBEDDING_DIM
        }

        return formData.embedding_dim
    }

    const getDefaultBindingHost = (binding: string) => {
        if (binding === 'openai') return 'https://api.openai.com/v1'
        if (binding === 'openai_codex') return 'https://chatgpt.com/backend-api/codex'
        if (binding === 'ollama') return 'http://localhost:11434'
        if (binding === 'codex_cli') return 'codex'
        return ''
    }

    React.useEffect(() => {
        let active = true
        if (formData.llm_binding !== 'openai_codex') {
            return
        }

        void getOpenAICodexAuthStatus()
            .then((status) => {
                if (active) setOpenAICodexAuth(status)
            })
            .catch(() => {
                if (active) setOpenAICodexAuth({ connected: false })
            })

        return () => {
            active = false
        }
    }, [formData.llm_binding])

    const pollOpenAICodexAuth = async (state: string) => {
        const startedAt = Date.now()
        while (Date.now() - startedAt < 180000) {
            const flow = await getOpenAICodexAuthFlowStatus(state)
            if (flow.status === 'completed') {
                const auth = flow.connection || (await getOpenAICodexAuthStatus())
                setOpenAICodexAuth(auth)
                return
            }
            if (flow.status === 'error') {
                throw new Error(flow.error || 'OpenAI Codex authentication failed')
            }
            await new Promise((resolve) => window.setTimeout(resolve, 1500))
        }
        throw new Error('OpenAI Codex authentication timed out')
    }

    const handleConnectOpenAICodex = async () => {
        setOpenAICodexBusy(true)
        try {
            const start = await startOpenAICodexAuth()
            try {
                await openExternalUrl(start.authorization_url)
            } catch (openError) {
                try {
                    await navigator.clipboard.writeText(start.authorization_url)
                    toast.info(
                        `Could not open browser automatically. Login URL copied to clipboard. ${errorMessage(openError)}`
                    )
                } catch {
                    toast.info(
                        `Could not open browser automatically. Open this URL manually: ${start.authorization_url}`
                    )
                }
            }
            await pollOpenAICodexAuth(start.state)
            toast.success('OpenAI ChatGPT/Codex connected')
        } catch (err) {
            toast.error(`Failed to connect OpenAI Codex: ${errorMessage(err)}`)
        } finally {
            setOpenAICodexBusy(false)
        }
    }

    const handleDisconnectOpenAICodex = async () => {
        setOpenAICodexBusy(true)
        try {
            await disconnectOpenAICodexAuth()
            setOpenAICodexAuth({ connected: false })
            toast.success('OpenAI ChatGPT/Codex disconnected')
        } catch (err) {
            toast.error(`Failed to disconnect OpenAI Codex: ${errorMessage(err)}`)
        } finally {
            setOpenAICodexBusy(false)
        }
    }

    const handleStorageProviderChange = (field: keyof SettingsUpdateRequest, value: string) => {
        if (isRestrictedStorageProvider(value)) {
            setUpgradeReason('Third-party storage providers are available in Pro.')
            setShowUpgradeDialog(true)
            return
        }
        handleChange(field, value)
    }

    const isLlmDisabled = disabledSections.includes('llm')
    const isEmbeddingDisabled = disabledSections.includes('embedding')
    const isStorageDisabled = disabledSections.includes('storage')
    const isLlmApiKeyEditable = !isLlmDisabled || apiKeyEditableWhenDisabled
    const isEmbeddingApiKeyEditable = !isEmbeddingDisabled || apiKeyEditableWhenDisabled
    const isLlmConsentEditable = !isLlmDisabled || apiKeyEditableWhenDisabled
    const isEmbeddingConsentEditable = !isEmbeddingDisabled || apiKeyEditableWhenDisabled

    return (
        <div className="space-y-6">
            {/* LLM Settings */}
            <div className={`space-y-4 ${isLlmDisabled && !apiKeyEditableWhenDisabled ? 'opacity-70' : ''}`}>
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold uppercase text-muted-foreground">LLM Configuration</h3>
                    {isLlmDisabled && (
                        <span className="text-[10px] bg-muted px-2 py-0.5 rounded text-muted-foreground">
                            {apiKeyEditableWhenDisabled ? 'READ-ONLY (EXCEPT API KEY)' : 'READ-ONLY'}
                        </span>
                    )}
                </div>

                <div className="space-y-2">
                    <Text text="LLM Provider" className="text-xs font-bold uppercase" />
                    <Select
                        value={formData.llm_binding}
                        onValueChange={(val) => {
                            handleChanges({
                                llm_binding: val,
                                llm_model: val === 'ollama' ? DEFAULT_OLLAMA_LLM_MODEL : (val === 'openai_codex' ? 'gpt-5.4' : ''),
                                llm_binding_host: getDefaultBindingHost(val),
                                llm_binding_api_key: val === 'codex_cli' || val === 'openai_codex' ? '' : formData.llm_binding_api_key
                            })
                        }}
                        disabled={isLlmDisabled}
                    >
                        <SelectTrigger>
                            <SelectValue placeholder="Select Provider" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="openai">OpenAI (GPT-4o, etc.)</SelectItem>
                            <SelectItem value="openai_codex">OpenAI ChatGPT/Codex Login</SelectItem>
                            <SelectItem value="codex_cli">Codex CLI (ChatGPT Login)</SelectItem>
                            <SelectItem value="ollama">Ollama (Local)</SelectItem>
                            {/* <SelectItem value="gemini">Google Gemini</SelectItem> */}
                            {/* <SelectItem value="azure_openai">Azure OpenAI</SelectItem> */}
                        </SelectContent>
                    </Select>
                    {formData.llm_binding === 'codex_cli' && (
                        <p className="text-[10px] text-muted-foreground">
                            Uses local `codex` CLI login. No API key required. `CLI Path` defaults to `codex`.
                        </p>
                    )}
                    {formData.llm_binding === 'openai_codex' && (
                        <div className="space-y-3 rounded-md border border-border/50 bg-muted/20 p-3">
                            <p className="text-[10px] text-muted-foreground">
                                Sign in with your ChatGPT/Codex account. Retriqs opens the official OpenAI login flow and stores local OAuth tokens for this app.
                            </p>
                            <div className="flex flex-wrap items-center gap-2">
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    onClick={() => void handleConnectOpenAICodex()}
                                    disabled={openAICodexBusy || isLlmDisabled}
                                >
                                    {openAICodexBusy ? 'Connecting...' : (openAICodexAuth?.connected ? 'Reconnect' : 'Connect OpenAI')}
                                </Button>
                                {openAICodexAuth?.connected && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => void handleDisconnectOpenAICodex()}
                                        disabled={openAICodexBusy || isLlmDisabled}
                                    >
                                        Disconnect
                                    </Button>
                                )}
                            </div>
                            <div className="text-[10px] text-muted-foreground">
                                Status: {openAICodexAuth?.connected
                                    ? `Connected${openAICodexAuth.email ? ` as ${openAICodexAuth.email}` : ''}`
                                    : 'Not connected'}
                            </div>
                        </div>
                    )}
                    {(formData.llm_binding === 'openai' || formData.llm_binding === 'openai_codex') && (
                        <div 
                            className={`flex items-start space-x-2 mt-2 p-3 bg-amber-500/5 focus-within:ring-1 focus-within:ring-amber-500/20 border border-amber-500/20 rounded-md transition-colors ${
                                isLlmConsentEditable ? 'cursor-pointer hover:bg-amber-500/10' : 'cursor-not-allowed opacity-70'
                            }`}
                            onClick={() => {
                                if (!isLlmConsentEditable) return
                                handleChange('openai_consent' as any, !(formData as any).openai_consent)
                            }}
                        >
                            <Checkbox 
                                id="llm-openai-consent" 
                                checked={!!(formData as any).openai_consent}
                                onCheckedChange={(checked) => handleChange('openai_consent' as any, checked)}
                                className="mt-0.5"
                                onClick={(e) => e.stopPropagation()}
                                disabled={!isLlmConsentEditable}
                            />
                            <div className="grid gap-1.5 leading-none">
                                <label
                                    htmlFor="llm-openai-consent"
                                    className="text-xs font-bold uppercase tracking-widest text-amber-600 dark:text-amber-500 cursor-pointer"
                                    onClick={(e) => e.preventDefault()}
                                >
                                    External Data Processing
                                </label>
                                <p className="text-[10px] text-muted-foreground w-[95%]">
                                    You agree to send document and query data to OpenAI.
                                </p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                        <Text text="Model" className="text-xs font-bold uppercase" />
                        {formData.llm_binding === 'openai' || formData.llm_binding === 'ollama' ? (
                            <LitellmModelSelect
                                key={formData.llm_binding}
                                mode="chat"
                                value={formData.llm_model}
                                onChange={(val) => {
                                    handleChange('llm_model', val)
                                }}
                                disabled={isLlmDisabled}
                                allowedProviders={[formData.llm_binding]}
                            />
                        ) : (
                            <Input
                                value={formData.llm_model}
                                onChange={(e) => handleChange('llm_model', e.target.value)}
                                placeholder={formData.llm_binding === 'openai_codex' ? 'gpt-5.4' : 'gpt-4o-mini'}
                                disabled={isLlmDisabled}
                            />
                        )}
                    </div>
                    {formData.llm_binding === 'ollama' && (
                        <div className="space-y-2">
                            <Text text="Context Size" className="text-xs font-bold uppercase" />
                            <Input
                                type="number"
                                value={formData.ollama_num_ctx}
                                onChange={(e) =>
                                    handleChange('ollama_num_ctx', Number(e.target.value))
                                }
                                disabled={isLlmDisabled}
                            />
                        </div>
                    )}
                </div>

                <div className="space-y-2">
                    <Text text="Max Async Runners" className="text-xs font-bold uppercase" />
                    <div className="relative">
                        <Hash className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                        <Input
                            type="number"
                            className="pl-9"
                            value={formData.max_async}
                            onChange={(e) => handleChange('max_async', Number(e.target.value))}
                            disabled={isLlmDisabled}
                        />
                    </div>
                </div>

                <div className="space-y-2">
                    <Text text={formData.llm_binding === 'codex_cli' ? 'CLI Path' : 'API Host'} className="text-xs font-bold uppercase" />
                    <div className="relative">
                        <Globe className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                        <Input
                            className="pl-9"
                            value={formData.llm_binding_host}
                            onChange={(e) => handleChange('llm_binding_host', e.target.value)}
                            disabled={isLlmDisabled}
                        />
                    </div>
                </div>

                {formData.llm_binding !== 'ollama' && formData.llm_binding !== 'codex_cli' && formData.llm_binding !== 'openai_codex' && (
                    <div className="space-y-2">
                        <Text text="API Key" className="text-xs font-bold uppercase" />
                        <div className="relative">
                            <Key className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                            <Input
                                type="password"
                                className="pl-9"
                                value={formData.llm_binding_api_key}
                                onChange={(e) =>
                                    handleChange('llm_binding_api_key', e.target.value)
                                }
                                disabled={!isLlmApiKeyEditable}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* Embedding Settings */}
            <div className={`space-y-4 border-t pt-4 ${isEmbeddingDisabled && !apiKeyEditableWhenDisabled ? 'opacity-70' : ''}`}>
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold uppercase text-muted-foreground">Embedding Configuration</h3>
                    {isEmbeddingDisabled && (
                        <span className="text-[10px] bg-muted px-2 py-0.5 rounded text-muted-foreground">
                            {apiKeyEditableWhenDisabled ? 'READ-ONLY (EXCEPT API KEY)' : 'READ-ONLY'}
                        </span>
                    )}
                </div>

                <div className="space-y-2">
                    <Text text="Embedding Provider" className="text-xs font-bold uppercase" />
                    <Select
                        value={formData.embedding_binding}
                        onValueChange={(val) => {
                            handleChanges({
                                embedding_binding: val,
                                embedding_model: val === 'ollama' ? DEFAULT_OLLAMA_EMBEDDING_MODEL : '',
                                embedding_binding_host: getDefaultBindingHost(val),
                                embedding_dim: val === 'ollama' ? DEFAULT_OLLAMA_EMBEDDING_DIM : 1536
                            })
                        }}
                        disabled={isEmbeddingDisabled}
                    >
                        <SelectTrigger>
                            <SelectValue placeholder="Select Provider" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="openai">OpenAI Embeddings</SelectItem>
                            <SelectItem value="ollama">Ollama (Local Embeddings)</SelectItem>
                            {/* <SelectItem value="gemini">Gemini Embedding</SelectItem> */}
                            {/* <SelectItem value="jina">Jina AI</SelectItem> */}
                        </SelectContent>
                    </Select>
                    {formData.embedding_binding === 'openai' && formData.llm_binding !== 'openai' && (
                        <div 
                            className={`flex items-start space-x-2 mt-2 p-3 bg-amber-500/5 focus-within:ring-1 focus-within:ring-amber-500/20 border border-amber-500/20 rounded-md transition-colors ${
                                isEmbeddingConsentEditable ? 'cursor-pointer hover:bg-amber-500/10' : 'cursor-not-allowed opacity-70'
                            }`}
                            onClick={() => {
                                if (!isEmbeddingConsentEditable) return
                                handleChange('openai_consent' as any, !(formData as any).openai_consent)
                            }}
                        >
                            <Checkbox 
                                id="embed-openai-consent" 
                                checked={!!(formData as any).openai_consent}
                                onCheckedChange={(checked) => handleChange('openai_consent' as any, checked)}
                                className="mt-0.5"
                                onClick={(e) => e.stopPropagation()}
                                disabled={!isEmbeddingConsentEditable}
                            />
                            <div className="grid gap-1.5 leading-none">
                                <label
                                    htmlFor="embed-openai-consent"
                                    className="text-xs font-bold uppercase tracking-widest text-amber-600 dark:text-amber-500 cursor-pointer"
                                    onClick={(e) => e.preventDefault()}
                                >
                                    External Data Processing
                                </label>
                                <p className="text-[10px] text-muted-foreground w-[95%]">
                                    You agree to send document and query data to OpenAI.
                                </p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                        <Text text="Model" className="text-xs font-bold uppercase" />
                        {formData.embedding_binding === 'openai' || formData.embedding_binding === 'ollama' ? (
                            <LitellmModelSelect
                                key={formData.embedding_binding}
                                mode="embedding"
                                value={formData.embedding_model}
                                onChange={(val, opt) => {
                                    handleChange('embedding_model', val)
                                    handleChange('embedding_dim', inferEmbeddingDim(val, opt?.metadata))
                                    if (opt && opt.metadata.max_input_tokens) {
                                        // Auto-fill token limit when LiteLLM metadata includes it.
                                        handleChange('embedding_token_limit', opt.metadata.max_input_tokens)
                                    }
                                }}
                                disabled={isEmbeddingDisabled}
                                allowedProviders={[formData.embedding_binding]}
                            />
                        ) : (
                            <Input
                                value={formData.embedding_model}
                                onChange={(e) => handleChange('embedding_model', e.target.value)}
                                placeholder="text-embedding-3-small"
                                disabled={isEmbeddingDisabled}
                            />
                        )}
                    </div>
                    <div className="space-y-2">
                        <Text text="Dimension" className="text-xs font-bold uppercase" />
                        <div className="relative">
                            <Maximize2 className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                            <Input
                                type="number"
                                className="pl-9"
                                value={formData.embedding_dim}
                                onChange={(e) =>
                                    handleChange('embedding_dim', Number(e.target.value))
                                }
                                disabled={isEmbeddingDisabled}
                            />
                        </div>
                    </div>
                </div>

                <div className="space-y-2">
                    <Text text="API Host" className="text-xs font-bold uppercase" />
                    <Input
                        value={formData.embedding_binding_host}
                        onChange={(e) => handleChange('embedding_binding_host', e.target.value)}
                        disabled={isEmbeddingDisabled}
                    />
                </div>

                {formData.embedding_binding !== 'ollama' && (
                    <div className="space-y-2">
                        <Text text="API Key" className="text-xs font-bold uppercase" />
                        <div className="relative">
                            <Key className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                            <Input
                                type="password"
                                className="pl-9"
                                value={formData.embedding_binding_api_key}
                                onChange={(e) =>
                                    handleChange('embedding_binding_api_key', e.target.value)
                                }
                                disabled={!isEmbeddingApiKeyEditable}
                            />
                        </div>
                    </div>
                )}

                <div className="space-y-2">
                    <Text text="Token Limit" className="text-xs font-bold uppercase" />
                    <div className="relative">
                        <Hash className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                        <Input
                            type="number"
                            className="pl-9"
                            value={formData.embedding_token_limit}
                            onChange={(e) =>
                                handleChange('embedding_token_limit', Number(e.target.value))
                            }
                            disabled={isEmbeddingDisabled}
                        />
                    </div>
                </div>
            </div>

            {/* Storage Configuration */}
            <div className={`space-y-6 border-t pt-6 ${isStorageDisabled ? 'opacity-70' : ''}`}>
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold uppercase text-muted-foreground flex items-center gap-2">
                        <Database className="h-4 w-4" />
                        Storage Configuration
                    </h3>
                    {isStorageDisabled && <span className="text-[10px] bg-muted px-2 py-0.5 rounded text-muted-foreground tracking-widest font-mono">LOCKED</span>}
                </div>

                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                    {/* Graph Storage */}
                    <div className="group space-y-3 rounded-xl border bg-muted/20 p-4 transition-all hover:bg-muted/40">
                        <div className="flex items-center gap-2">
                            <div className="rounded-lg bg-blue-500/10 p-2 text-blue-500">
                                <Layout className="h-4 w-4" />
                            </div>
                            <Text text="Graph Storage" className="text-xs font-bold uppercase text-muted-foreground" />
                        </div>
                        <Select
                            value={formData.lightrag_graph_storage || 'GrafeoGraphStorage'}
                            onValueChange={(val) => handleStorageProviderChange('lightrag_graph_storage', val)}
                            disabled={isStorageDisabled}
                        >
                            <SelectTrigger className="bg-background border-none shadow-none focus:ring-0">
                            <SelectValue placeholder="Select Graph Storage" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="GrafeoGraphStorage">Grafeo</SelectItem>
                                <SelectItem value="NetworkXStorage">NetworkX (Local / File-based)</SelectItem>
                                <SelectItem value="Neo4JStorage">Neo4J (External DB)</SelectItem>
                            </SelectContent>
                        </Select>
                        <p className="text-[10px] text-muted-foreground px-1 italic">Stores entities and relations as a knowledge graph.</p>
                    </div>

                    {/* Vector Storage */}
                    <div className="group space-y-3 rounded-xl border bg-muted/20 p-4 transition-all hover:bg-muted/40">
                        <div className="flex items-center gap-2">
                            <div className="rounded-lg bg-purple-500/10 p-2 text-purple-500">
                                <Zap className="h-4 w-4" />
                            </div>
                            <Text text="Vector Storage" className="text-xs font-bold uppercase text-muted-foreground" />
                        </div>
                        <Select
                            value={formData.lightrag_vector_storage || 'GrafeoVectorStorage'}
                            onValueChange={(val) => handleStorageProviderChange('lightrag_vector_storage', val)}
                            disabled={isStorageDisabled}
                        >
                            <SelectTrigger className="bg-background border-none shadow-none focus:ring-0">
                            <SelectValue placeholder="Select Vector Storage" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="GrafeoVectorStorage">Grafeo</SelectItem>
                                <SelectItem value="MilvusVectorDBStorage">Milvus (Scaleable / Production)</SelectItem>
                                <SelectItem value="NanoVectorDBStorage">NanoVectorDB (Local / Fast)</SelectItem>
                            </SelectContent>
                        </Select>
                        <p className="text-[10px] text-muted-foreground px-1 italic">Stores embedded text for semantic search.</p>
                    </div>

                    {/* KV Storage */}
                    <div className="group space-y-3 rounded-xl border bg-muted/20 p-4 transition-all hover:bg-muted/40">
                        <div className="flex items-center gap-2">
                            <div className="rounded-lg bg-amber-500/10 p-2 text-amber-500">
                                <HardDrive className="h-4 w-4" />
                            </div>
                            <Text text="KV Storage" className="text-xs font-bold uppercase text-muted-foreground" />
                        </div>
                        <Select
                            value={formData.lightrag_kv_storage || 'JsonKVStorage'}
                            onValueChange={(val) => handleStorageProviderChange('lightrag_kv_storage', val)}
                            disabled={isStorageDisabled}
                        >
                            <SelectTrigger className="bg-background border-none shadow-none focus:ring-0">
                                <SelectValue placeholder="Select KV Storage" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="RedisKVStorage">Redis (Scalable)</SelectItem>
                                <SelectItem value="JsonKVStorage">JSON (Local)</SelectItem>
                            </SelectContent>
                        </Select>
                        <p className="text-[10px] text-muted-foreground px-1 italic">Stores structured key-value metadata.</p>
                    </div>

                    {/* Doc Status Storage */}
                    <div className="group space-y-3 rounded-xl border bg-muted/20 p-4 transition-all hover:bg-muted/40">
                        <div className="flex items-center gap-2">
                            <div className="rounded-lg bg-emerald-500/10 p-2 text-emerald-500">
                                <Files className="h-4 w-4" />
                            </div>
                            <Text text="Doc Status" className="text-xs font-bold uppercase text-muted-foreground" />
                        </div>
                        <Select
                            value={formData.lightrag_doc_status_storage || 'JsonDocStatusStorage'}
                            onValueChange={(val) => handleStorageProviderChange('lightrag_doc_status_storage', val)}
                            disabled={isStorageDisabled}
                        >
                            <SelectTrigger className="bg-background border-none shadow-none focus:ring-0">
                                <SelectValue placeholder="Select Doc Status Storage" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="RedisDocStatusStorage">Redis (Recommended)</SelectItem>
                                <SelectItem value="JsonDocStatusStorage">JSON (Local)</SelectItem>
                            </SelectContent>
                        </Select>
                        <p className="text-[10px] text-muted-foreground px-1 italic">Tracks document processing and indexing state.</p>
                    </div>
                </div>

                {/* Connection Settings */}
                <div className="mt-4 space-y-4">
                    {/* Neo4J-specific fields */}
                    {formData.lightrag_graph_storage === 'Neo4JStorage' && (
                        <div className="space-y-4 rounded-lg bg-muted/30 p-4 border border-border/50">
                            <h4 className="text-xs font-bold uppercase text-muted-foreground flex items-center gap-2 border-b pb-2">
                                <Globe className="h-3 w-3" /> Neo4J Connection
                            </h4>
                            <div className="space-y-2">
                                <Text text="Neo4J URI" className="text-xs font-bold uppercase opacity-70" />
                                <div className="relative">
                                    <Globe className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                                    <Input
                                        className="pl-9"
                                        value={formData.neo4j_uri || ''}
                                        onChange={(e) => handleChange('neo4j_uri', e.target.value)}
                                        placeholder="bolt://localhost:7687"
                                        disabled={isStorageDisabled}
                                    />
                                </div>
                            </div>
                            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div className="space-y-2">
                                    <Text text="Username" className="text-xs font-bold uppercase opacity-70" />
                                    <Input
                                        value={formData.neo4j_username || ''}
                                        onChange={(e) => handleChange('neo4j_username', e.target.value)}
                                        placeholder="neo4j"
                                        disabled={isStorageDisabled}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Text text="Password" className="text-xs font-bold uppercase opacity-70" />
                                    <div className="relative">
                                        <Key className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                                        <Input
                                            type="password"
                                            className="pl-9"
                                            value={formData.neo4j_password || ''}
                                            onChange={(e) => handleChange('neo4j_password', e.target.value)}
                                            placeholder="••••••••"
                                            disabled={isStorageDisabled}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Milvus-specific fields */}
                    {formData.lightrag_vector_storage === 'MilvusVectorDBStorage' && (
                        <div className="space-y-4 rounded-lg bg-muted/30 p-4 border border-border/50">
                            <h4 className="text-xs font-bold uppercase text-muted-foreground flex items-center gap-2 border-b pb-2">
                                <Globe className="h-3 w-3" /> Milvus Connection
                            </h4>
                            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div className="space-y-2">
                                    <Text text="Milvus URI" className="text-xs font-bold uppercase opacity-70" />
                                    <div className="relative">
                                        <Globe className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                                        <Input
                                            className="pl-9"
                                            value={formData.milvus_uri || ''}
                                            onChange={(e) => handleChange('milvus_uri', e.target.value)}
                                            placeholder="http://localhost:19530"
                                            disabled={isStorageDisabled}
                                        />
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    <Text text="Database Name" className="text-xs font-bold uppercase opacity-70" />
                                    <Input
                                        value={formData.milvus_db_name || ''}
                                        onChange={(e) => handleChange('milvus_db_name', e.target.value)}
                                        placeholder="lightrag"
                                        disabled={isStorageDisabled}
                                    />
                                </div>
                            </div>
                            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div className="space-y-2">
                                    <Text text="Username" className="text-xs font-bold uppercase opacity-70" />
                                    <Input
                                        value={formData.milvus_user || ''}
                                        onChange={(e) => handleChange('milvus_user', e.target.value)}
                                        placeholder="root"
                                        disabled={isStorageDisabled}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Text text="Password" className="text-xs font-bold uppercase opacity-70" />
                                    <div className="relative">
                                        <Key className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                                        <Input
                                            type="password"
                                            className="pl-9"
                                            value={formData.milvus_password || ''}
                                            onChange={(e) => handleChange('milvus_password', e.target.value)}
                                            placeholder="••••••••"
                                            disabled={isStorageDisabled}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Redis-specific fields (for KV or Doc Status) */}
                    {(formData.lightrag_kv_storage === 'RedisKVStorage' || formData.lightrag_doc_status_storage === 'RedisDocStatusStorage') && (
                        <div className="space-y-4 rounded-lg bg-muted/30 p-4 border border-border/50">
                            <h4 className="text-xs font-bold uppercase text-muted-foreground flex items-center gap-2 border-b pb-2">
                                <Globe className="h-3 w-3" /> Redis Connection
                            </h4>
                            <div className="space-y-2">
                                <Text text="Redis URI" className="text-xs font-bold uppercase opacity-70" />
                                <div className="relative">
                                    <Globe className="text-muted-foreground absolute top-3 left-3 h-4 w-4" />
                                    <Input
                                        className="pl-9"
                                        value={formData.redis_uri || ''}
                                        onChange={(e) => handleChange('redis_uri', e.target.value)}
                                        placeholder="redis://localhost:6379"
                                        disabled={isStorageDisabled}
                                    />
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
            <UpgradePromptDialog
                open={showUpgradeDialog}
                onOpenChange={setShowUpgradeDialog}
                reason={upgradeReason}
            />
        </div>
    )
}
