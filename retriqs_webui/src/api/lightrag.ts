import axios, { AxiosError } from 'axios'
import {
  popularLabelsDefaultLimit,
  searchLabelsDefaultLimit
} from '@/lib/constants'
import { getBackendBaseUrl } from '@/lib/runtime'
import { errorMessage } from '@/lib/utils'
import { useSettingsStore } from '@/stores/settings'
import { navigationService } from '@/services/navigation'

// Types
export type LightragNodeType = {
  id: string
  labels: string[]
  properties: Record<string, any>
}

export type LightragEdgeType = {
  id: string
  source: string
  target: string
  type: string
  properties: Record<string, any>
}

// Add these types to your types section
export type AppSettings = {
  LLM_BINDING: string
  LLM_MODEL: string
  LLM_BINDING_HOST: string
  LLM_BINDING_API_KEY: string
  EMBEDDING_BINDING: string
  EMBEDDING_MODEL: string
  EMBEDDING_BINDING_HOST: string
  EMBEDDING_BINDING_API_KEY: string
  [key: string]: any // For other settings like OLLAMA_NUM_CTX, etc.
}

export type SettingsUpdateRequest = {
  llm_binding: string
  llm_model: string
  llm_binding_host: string
  llm_binding_api_key: string
  ollama_num_ctx: number
  embedding_binding: string
  embedding_model: string
  embedding_binding_host: string
  embedding_binding_api_key: string
  embedding_dim: number
  embedding_token_limit: number
  max_async: number
  rerank_binding: string
  id: number

  // Storage Configuration
  lightrag_graph_storage?: string
  lightrag_kv_storage?: string
  lightrag_doc_status_storage?: string
  lightrag_vector_storage?: string
  neo4j_uri?: string
  neo4j_username?: string
  neo4j_password?: string

  milvus_uri?: string
  milvus_db_name?: string
  milvus_user?: string
  milvus_password?: string

  redis_uri?: string
}

export type LightragGraphType = {
  nodes: LightragNodeType[]
  edges: LightragEdgeType[]
}

export type GraphStorage = {
  id: number
  name: string
  work_dir: string
  storage_settings: Array<{
    key: string
    value: string
  }>
}

export type StorageArchiveManifest = {
  archive_version: number
  storage_name: string
  source_storage_id?: number | null
  exported_at: string
  backend_scope: string
  required_files: string[]
  storage_settings: Record<string, string>
}

export type StorageMergeNamespaceSummary = {
  additions: number
  no_ops: number
  conflicts: number
}

export type StorageMergeAnalysisResponse = {
  analysis_id: string
  target_storage_id: number
  archive_manifest: StorageArchiveManifest
  summary: {
    additions: number
    no_ops: number
    conflicts: number
    blocking_issues: number
    namespaces: Record<string, StorageMergeNamespaceSummary>
  }
  blocking_issues: string[]
  conflicts: Array<{
    namespace: string
    key: string
    target_preview: any
    archive_preview: any
  }>
  samples: Array<{
    namespace: string
    key: string
    target_preview: any
    archive_preview: any
  }>
}

export type StorageMergeApplyResponse = {
  status: string
  message: string
  merged_counts: {
    additions: number
    no_ops: number
    conflicts: number
  }
}

export type ArchiveEmbeddingImportMode = 'preindexed' | 'local_reembed'
export type RebuildEmbeddingsResponse = {
  status: 'reembedding_completed'
  message: string
  storage_id: number
  counts: {
    chunks: number
    entities: number
    relationships: number
  }
}

export type LightragStatus = {
  status: 'healthy' | 'starting' | 'error' | 'stopping'
  ready?: boolean
  message?: string
  working_directory: string
  input_directory: string
  configuration: {
    llm_binding: string
    llm_binding_host: string
    llm_model: string
    embedding_binding: string
    embedding_binding_host: string
    embedding_model: string
    kv_storage: string
    doc_status_storage: string
    graph_storage: string
    vector_storage: string
    workspace?: string
    max_graph_nodes?: string
    enable_rerank?: boolean
    rerank_binding?: string | null
    rerank_model?: string | null
    rerank_binding_host?: string | null
    summary_language: string
    force_llm_summary_on_merge: boolean
    max_parallel_insert: number
    max_async: number
    embedding_func_max_async: number
    embedding_batch_num: number
    cosine_threshold: number
    min_rerank_score: number
    related_chunk_number: number
  }
  update_status?: Record<string, any>
  core_version?: string
  api_version?: string
  auth_mode?: 'enabled' | 'disabled'
  pipeline_busy: boolean
  current_job?: string | null
  reembedding_busy?: boolean
  pipeline_latest_message?: string | null
  storage_count?: number
  failed_storage_ids?: number[]
  pipeline_status_error?: string
  keyed_locks?: {
    process_id: number
    cleanup_performed: {
      mp_cleaned: number
      async_cleaned: number
    }
    current_status: {
      total_mp_locks: number
      pending_mp_cleanup: number
      total_async_locks: number
      pending_async_cleanup: number
    }
  }
  webui_title?: string
  webui_description?: string
}

export type LightragDocumentsScanProgress = {
  is_scanning: boolean
  current_file: string
  indexed_count: number
  total_files: number
  progress: number
}

/**
 * Specifies the retrieval mode:
 * - "naive": Performs a basic search without advanced techniques.
 * - "local": Focuses on context-dependent information.
 * - "global": Utilizes global knowledge.
 * - "hybrid": Combines local and global retrieval methods.
 * - "mix": Integrates knowledge graph and vector retrieval.
 * - "bypass": Bypasses knowledge retrieval and directly uses the LLM.
 */
export type QueryMode = 'naive' | 'local' | 'global' | 'hybrid' | 'mix' | 'bypass'

export type Message = {
  role: 'user' | 'assistant' | 'system'
  content: string
  thinkingContent?: string
  displayContent?: string
  thinkingTime?: number | null
}

export type QueryRequest = {
  query: string
  /** Specifies the retrieval mode. */
  mode: QueryMode
  /** If True, only returns the retrieved context without generating a response. */
  only_need_context?: boolean
  /** If True, only returns the generated prompt without producing a response. */
  only_need_prompt?: boolean
  /** Defines the response format. Examples: 'Multiple Paragraphs', 'Single Paragraph', 'Bullet Points'. */
  response_type?: string
  /** If True, enables streaming output for real-time responses. */
  stream?: boolean
  /** Number of top items to retrieve. Represents entities in 'local' mode and relationships in 'global' mode. */
  top_k?: number
  /** Maximum number of text chunks to retrieve and keep after reranking. */
  chunk_top_k?: number
  /** Maximum number of tokens allocated for entity context in unified token control system. */
  max_entity_tokens?: number
  /** Maximum number of tokens allocated for relationship context in unified token control system. */
  max_relation_tokens?: number
  /** Maximum total tokens budget for the entire query context (entities + relations + chunks + system prompt). */
  max_total_tokens?: number
  /**
   * Stores past conversation history to maintain context.
   * Format: [{"role": "user/assistant", "content": "message"}].
   */
  conversation_history?: Message[]
  /** Number of complete conversation turns (user-assistant pairs) to consider in the response context. */
  history_turns?: number
  /** User-provided prompt for the query. If provided, this will be used instead of the default value from prompt template. */
  user_prompt?: string
  /** Enable reranking for retrieved text chunks. If True but no rerank model is configured, a warning will be issued. Default is True. */
  enable_rerank?: boolean
  /** If True, includes retrieval trace (entities/relationships/chunks/references/metadata) for the same query execution. */
  include_trace?: boolean
  /** If True, includes references list in response payloads. */
  include_references?: boolean
  /** If True, includes chunk content in references payloads. */
  include_chunk_content?: boolean
  /** Existing chat id to append this question to. */
  chat_id?: number
  /** Alias for only_need_context. */
  context_only?: boolean
}

export type QueryTraceData = {
  entities: Array<Record<string, any>>
  relationships: Array<Record<string, any>>
  chunks: Array<{
    reference_id: string
    content: string
    file_path: string
    chunk_id: string
    [key: string]: any
  }>
  references: Array<{
    reference_id: string
    file_path: string
    content?: string[]
    [key: string]: any
  }>
}

export type QueryTrace = {
  data: QueryTraceData
  metadata: Record<string, any>
}

export type QueryResponse = {
  response: string
  references?: Array<{
    reference_id: string
    file_path: string
    content?: string[]
  }> | null
  trace?: QueryTrace | null
  chat_id?: number | null
  user_message_id?: number | null
  assistant_message_id?: number | null
}

export type QueryChatSummary = {
  id: number
  storage_id: number
  title?: string | null
  is_pinned: boolean
  created_at?: string | null
  updated_at?: string | null
  message_count: number
  last_message_preview?: string | null
}

export type QueryChatMessage = {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  sequence_no: number
  created_at?: string | null
  retrieval_snapshot?: {
    mode?: string | null
    data?: Record<string, any>
    metadata?: Record<string, any>
    references?: Array<{ reference_id: string; file_path: string; content?: string[] }>
    trace?: QueryTrace | null
    created_at?: string | null
  } | null
}

export type QueryChatDetail = {
  id: number
  storage_id: number
  title?: string | null
  is_pinned: boolean
  created_at?: string | null
  updated_at?: string | null
  messages: QueryChatMessage[]
}

export type EntityUpdateResponse = {
  status: string
  message: string
  data: Record<string, any>
  operation_summary?: {
    merged: boolean
    merge_status: 'success' | 'failed' | 'not_attempted'
    merge_error: string | null
    operation_status: 'success' | 'partial_success' | 'failure'
    target_entity: string | null
    final_entity?: string | null
    renamed?: boolean
  }
}

export type DocActionResponse = {
  status: 'success' | 'partial_success' | 'failure' | 'duplicated'
  message: string
  track_id?: string
}

export type ScanResponse = {
  status: 'scanning_started'
  message: string
  track_id: string
}

export type ReprocessFailedResponse = {
  status: 'reprocessing_started'
  message: string
  track_id: string
}

export type DeleteDocResponse = {
  status: 'deletion_started' | 'busy' | 'not_allowed'
  message: string
  doc_id: string
}

export type DocStatus = 'pending' | 'processing' | 'preprocessed' | 'processed' | 'failed'

export type DocStatusResponse = {
  id: string
  content_summary: string
  content_length: number
  status: DocStatus
  created_at: string
  updated_at: string
  track_id?: string
  chunks_count?: number
  error_msg?: string
  metadata?: Record<string, any>
  file_path: string
}

export type DocsStatusesResponse = {
  statuses: Record<DocStatus, DocStatusResponse[]>
}

export type TrackStatusResponse = {
  track_id: string
  documents: DocStatusResponse[]
  total_count: number
  status_summary: Record<string, number>
}

export type DocumentsRequest = {
  status_filter?: DocStatus | null
  page: number
  page_size: number
  sort_field: 'created_at' | 'updated_at' | 'id' | 'file_path'
  sort_direction: 'asc' | 'desc'
}

export type PaginationInfo = {
  page: number
  page_size: number
  total_count: number
  total_pages: number
  has_next: boolean
  has_prev: boolean
}

export type PaginatedDocsResponse = {
  documents: DocStatusResponse[]
  pagination: PaginationInfo
  status_counts: Record<string, number>
}

export type StatusCountsResponse = {
  status_counts: Record<string, number>
}

export type AuthStatusResponse = {
  auth_configured: boolean
  access_token?: string
  token_type?: string
  auth_mode?: 'enabled' | 'disabled'
  message?: string
  core_version?: string
  api_version?: string
  webui_title?: string
  webui_description?: string
}

type WaitForBackendHealthOptions = {
  timeoutMs?: number
  pollIntervalMs?: number
}

export type PipelineStatusResponse = {
  autoscanned: boolean
  busy: boolean
  job_name: string
  job_start?: string
  docs: number
  batchs: number
  cur_batch: number
  request_pending: boolean
  cancellation_requested?: boolean
  latest_message: string
  history_messages?: string[]
  update_status?: Record<string, any>
}

export type LoginResponse = {
  access_token: string
  token_type: string
  auth_mode?: 'enabled' | 'disabled' // Authentication mode identifier
  message?: string // Optional message
  core_version?: string
  api_version?: string
  webui_title?: string
  webui_description?: string
}

export const InvalidApiKeyError = 'Invalid API Key'
export const RequireApiKeError = 'API Key required'
const hasStorageId = (storageId?: number) => storageId !== undefined && storageId !== null

// Axios instance
const axiosInstance = axios.create({
  headers: {
    'Content-Type': 'application/json'
  }
})

// Interceptor: add api key and check authentication
axiosInstance.interceptors.request.use((config) => {
  config.baseURL = getBackendBaseUrl()
  const apiKey = useSettingsStore.getState().apiKey
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')

  // Always include token if it exists, regardless of path
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey
  }
  return config
})

// Interceptor：hanle error
axiosInstance.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response) {
      if (error.response?.status === 401) {
        // For login API, throw error directly
        if (error.config?.url?.includes('/login')) {
          throw error
        }
        // For other APIs, navigate to login page
        navigationService.navigateToLogin()

        // return a reject Promise
        return Promise.reject(new Error('Authentication required'))
      }
      throw new Error(
        `${error.response.status} ${error.response.statusText}\n${JSON.stringify(
          error.response.data
        )}\n${error.config?.url}`
      )
    }
    throw error
  }
)

// API methods
export const queryGraphs = async (
  label: string,
  maxDepth: number,
  maxNodes: number,
  storageId?: number
): Promise<LightragGraphType> => {
  const url = storageId ? `/storage/${storageId}/graphs` : '/graphs'
  const response = await axiosInstance.get(
    `${url}?label=${encodeURIComponent(label)}&max_depth=${maxDepth}&max_nodes=${maxNodes}`
  )
  return response.data
}

export const getSystemSettings = async (): Promise<AppSettings> => {
  const response = await axiosInstance.get('/api/settings')
  return response.data
}

export const updateSystemSettings = async (
  data: SettingsUpdateRequest
): Promise<{ status: string; message: string }> => {
  const response = await axiosInstance.post('/api/settings', data)
  return response.data
}

export const getGraphStorages = async (): Promise<GraphStorage[]> => {
  const response = await axiosInstance.get('/api/settings/graph_storages')
  return response.data
}

export const deleteGraphStorage = async (id: number): Promise<{ message: string }> => {
  const response = await axiosInstance.delete(`/api/settings/storage/${id}`)
  return response.data
}


export const getPopularLabels = async (
  limit: number = popularLabelsDefaultLimit,
  storageId?: number
): Promise<string[]> => {
  const url = storageId ? `/storage/${storageId}/graph/label/popular` : '/graph/label/popular'
  const response = await axiosInstance.get(`${url}?limit=${limit}`)
  return response.data
}

export const searchLabels = async (
  query: string,
  limit: number = searchLabelsDefaultLimit,
  storageId?: number
): Promise<string[]> => {
  const url = storageId ? `/storage/${storageId}/graph/label/search` : '/graph/label/search'
  const response = await axiosInstance.get(
    `${url}?q=${encodeURIComponent(query)}&limit=${limit}`
  )
  return response.data
}

export const checkHealth = async (): Promise<
  LightragStatus | { status: 'error'; message: string }
> => {
  try {
    const response = await axiosInstance.get('/health')
    return response.data
  } catch (error) {
    return {
      status: 'error',
      message: errorMessage(error)
    }
  }
}

export const getDocuments = async (storageId?: number): Promise<DocsStatusesResponse> => {
  const url = storageId ? `/storage/${storageId}/documents` : '/documents'
  const response = await axiosInstance.get(url)
  return response.data
}

export const scanNewDocuments = async (storageId?: number): Promise<ScanResponse> => {
  const url = storageId ? `/storage/${storageId}/documents/scan` : '/documents/scan'
  const response = await axiosInstance.post(url)
  return response.data
}

export const reprocessFailedDocuments = async (storageId?: number): Promise<ReprocessFailedResponse> => {
  const url = storageId ? `/storage/${storageId}/documents/reprocess_failed` : '/documents/reprocess_failed'
  const response = await axiosInstance.post(url)
  return response.data
}

export const getDocumentsScanProgress = async (storageId?: number): Promise<LightragDocumentsScanProgress> => {
  const url = storageId ? `/storage/${storageId}/documents/scan-progress` : '/documents/scan-progress'
  const response = await axiosInstance.get(url)
  return response.data
}

export const queryText = async (request: QueryRequest, storageId?: number): Promise<QueryResponse> => {
  const url = hasStorageId(storageId) ? `/storage/${storageId}/query` : '/query'
  const response = await axiosInstance.post(url, request)
  return response.data
}

export const listQueryChats = async (storageId?: number): Promise<QueryChatSummary[]> => {
  const url = hasStorageId(storageId) ? `/storage/${storageId}/query/chats` : '/query/chats'
  const response = await axiosInstance.get(url)
  return response.data
}

export const createQueryChat = async (
  payload: { title?: string },
  storageId?: number
): Promise<QueryChatSummary> => {
  const url = hasStorageId(storageId) ? `/storage/${storageId}/query/chats` : '/query/chats'
  const response = await axiosInstance.post(url, payload)
  return response.data
}

export const getQueryChat = async (
  chatId: number,
  storageId?: number
): Promise<QueryChatDetail> => {
  const url = hasStorageId(storageId)
    ? `/storage/${storageId}/query/chats/${chatId}`
    : `/query/chats/${chatId}`
  const response = await axiosInstance.get(url)
  return response.data
}

export const updateQueryChat = async (
  chatId: number,
  payload: { title?: string; is_pinned?: boolean },
  storageId?: number
): Promise<QueryChatSummary> => {
  const url = hasStorageId(storageId)
    ? `/storage/${storageId}/query/chats/${chatId}`
    : `/query/chats/${chatId}`
  const response = await axiosInstance.patch(url, payload)
  return response.data
}

export const deleteQueryChat = async (
  chatId: number,
  storageId?: number
): Promise<{ status: string; chat_id: number }> => {
  const url = hasStorageId(storageId)
    ? `/storage/${storageId}/query/chats/${chatId}`
    : `/query/chats/${chatId}`
  const response = await axiosInstance.delete(url)
  return response.data
}

export const queryTextStream = async (
  request: QueryRequest,
  onChunk: (chunk: string) => void,
  onError?: (error: string) => void,
  onReferences?: (references: QueryResponse['references']) => void,
  onTrace?: (trace: QueryTrace | null | undefined) => void,
  onChat?: (chat: {
    chat_id?: number | null
    user_message_id?: number | null
    assistant_message_id?: number | null
  }) => void,
  storageId?: number
) => {
  const apiKey = useSettingsStore.getState().apiKey
  const token = localStorage.getItem('LIGHTRAG-API-TOKEN')
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    Accept: 'application/x-ndjson'
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  if (apiKey) {
    headers['X-API-Key'] = apiKey
  }

  const endpoint = hasStorageId(storageId) ? `/storage/${storageId}/query/stream` : '/query/stream'

  try {
    const response = await fetch(`${getBackendBaseUrl()}${endpoint}`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(request)
    })

    if (!response.ok) {
      // Handle 401 Unauthorized error specifically
      if (response.status === 401) {
        // For consistency with axios interceptor, navigate to login page
        navigationService.navigateToLogin()

        // Create a specific authentication error
        const authError = new Error('Authentication required')
        throw authError
      }

      // Handle other common HTTP errors with specific messages
      let errorBody = 'Unknown error'
      try {
        errorBody = await response.text() // Try to get error details from body
      } catch {
        /* ignore */
      }

      // Format error message similar to axios interceptor for consistency
      const url = `${getBackendBaseUrl()}${endpoint}`
      throw new Error(
        `${response.status} ${response.statusText}\n${JSON.stringify({ error: errorBody })}\n${url}`
      )
    }

    if (!response.body) {
      throw new Error('Response body is null')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        break // Stream finished
      }

      // Decode the chunk and add to buffer
      buffer += decoder.decode(value, { stream: true }) // stream: true handles multi-byte chars split across chunks

      // Process complete lines (NDJSON)
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // Keep potentially incomplete line in buffer

      for (const line of lines) {
        if (line.trim()) {
          try {
            const parsed = JSON.parse(line)
            if (parsed.references !== undefined && onReferences) {
              onReferences(parsed.references)
            }
            if (parsed.trace !== undefined && onTrace) {
              onTrace(parsed.trace)
            }
            if (parsed.chat !== undefined && onChat) {
              onChat(parsed.chat)
            }
            if (parsed.response) {
              onChunk(parsed.response)
            } else if (parsed.error && onError) {
              onError(parsed.error)
            }
          } catch (error) {
            console.error('Error parsing stream chunk:', line, error)
            if (onError) onError(`Error parsing server response: ${line}`)
          }
        }
      }
    }

    // Process any remaining data in the buffer after the stream ends
    if (buffer.trim()) {
      try {
        const parsed = JSON.parse(buffer)
        if (parsed.references !== undefined && onReferences) {
          onReferences(parsed.references)
        }
        if (parsed.trace !== undefined && onTrace) {
          onTrace(parsed.trace)
        }
        if (parsed.chat !== undefined && onChat) {
          onChat(parsed.chat)
        }
        if (parsed.response) {
          onChunk(parsed.response)
        } else if (parsed.error && onError) {
          onError(parsed.error)
        }
      } catch (error) {
        console.error('Error parsing final chunk:', buffer, error)
        if (onError) onError(`Error parsing final server response: ${buffer}`)
      }
    }
  } catch (error) {
    const message = errorMessage(error)

    // Check if this is an authentication error
    if (message === 'Authentication required') {
      // Already navigated to login page in the response.status === 401 block
      console.error('Authentication required for stream request')
      if (onError) {
        onError('Authentication required')
      }
      return // Exit early, no need for further error handling
    }

    // Check for specific HTTP error status codes in the error message
    const statusCodeMatch = message.match(/^(\d{3})\s/)
    if (statusCodeMatch) {
      const statusCode = parseInt(statusCodeMatch[1], 10)

      // Handle specific status codes with user-friendly messages
      let userMessage = message

      switch (statusCode) {
      case 403:
        userMessage = 'You do not have permission to access this resource (403 Forbidden)'
        console.error('Permission denied for stream request:', message)
        break
      case 404:
        userMessage = 'The requested resource does not exist (404 Not Found)'
        console.error('Resource not found for stream request:', message)
        break
      case 429:
        userMessage = 'Too many requests, please try again later (429 Too Many Requests)'
        console.error('Rate limited for stream request:', message)
        break
      case 500:
      case 502:
      case 503:
      case 504:
        userMessage = `Server error, please try again later (${statusCode})`
        console.error('Server error for stream request:', message)
        break
      default:
        console.error('Stream request failed with status code:', statusCode, message)
      }

      if (onError) {
        onError(userMessage)
      }
      return
    }

    // Handle network errors (like connection refused, timeout, etc.)
    if (
      message.includes('NetworkError') ||
      message.includes('Failed to fetch') ||
      message.includes('Network request failed')
    ) {
      console.error('Network error for stream request:', message)
      if (onError) {
        onError('Network connection error, please check your internet connection')
      }
      return
    }

    // Handle JSON parsing errors during stream processing
    if (message.includes('Error parsing') || message.includes('SyntaxError')) {
      console.error('JSON parsing error in stream:', message)
      if (onError) {
        onError('Error processing response data')
      }
      return
    }

    // Handle other errors
    console.error('Unhandled stream error:', message)
    if (onError) {
      onError(message)
    } else {
      console.error('No error handler provided for stream error:', message)
    }
  }
}

const buildDocumentFileEndpoints = (filePath: string, storageId?: number): string[] => {
  const endpoint = hasStorageId(storageId) ? `/storage/${storageId}/documents/file` : '/documents/file'
  const query = `file_path=${encodeURIComponent(filePath)}`
  const candidates: string[] = []
  const pushUnique = (value: string) => {
    if (!candidates.includes(value)) candidates.push(value)
  }

  pushUnique(`${endpoint}?${query}`)
  if (hasStorageId(storageId)) {
    pushUnique(`/documents/file?${query}`)
  }
  pushUnique(`/api${endpoint}?${query}`)
  if (hasStorageId(storageId)) {
    pushUnique(`/api/documents/file?${query}`)
  }

  return candidates
}

const buildDocumentPreviewEndpoints = (filePath: string, storageId?: number): string[] => {
  const endpoint = hasStorageId(storageId)
    ? `/storage/${storageId}/documents/file_preview`
    : '/documents/file_preview'
  const query = `file_path=${encodeURIComponent(filePath)}`
  const candidates: string[] = []
  const pushUnique = (value: string) => {
    if (!candidates.includes(value)) candidates.push(value)
  }

  pushUnique(`${endpoint}?${query}`)
  if (hasStorageId(storageId)) {
    pushUnique(`/documents/file_preview?${query}`)
  }
  pushUnique(`/api${endpoint}?${query}`)
  if (hasStorageId(storageId)) {
    pushUnique(`/api/documents/file_preview?${query}`)
  }

  return candidates
}

export const buildDocumentFileUrl = (filePath: string, storageId?: number): string => {
  return `${getBackendBaseUrl()}${buildDocumentFileEndpoints(filePath, storageId)[0]}`
}

export const buildDocumentFileCandidateUrls = (
  filePath: string,
  storageId?: number
): string[] => {
  return buildDocumentFileEndpoints(filePath, storageId).map((endpoint) => `${getBackendBaseUrl()}${endpoint}`)
}

export const fetchDocumentFileBlob = async (
  filePath: string,
  storageId?: number
): Promise<{ blob: Blob; contentType: string; sourceUrl: string }> => {
  const endpoints = buildDocumentFileEndpoints(filePath, storageId)
  let lastError: unknown = null
  let sawHtmlResponse = false

  for (const endpoint of endpoints) {
    try {
      const response = await axiosInstance.get(endpoint, {
        responseType: 'blob',
        params: { _ts: Date.now() },
        headers: {
          'Cache-Control': 'no-cache',
          Pragma: 'no-cache'
        }
      })
      const contentType = String(response.headers?.['content-type'] || '')
      if (contentType.toLowerCase().includes('text/html')) {
        sawHtmlResponse = true
        continue
      }
      return {
        blob: response.data,
        contentType,
        sourceUrl: `${getBackendBaseUrl()}${endpoint}`
      }
    } catch (error) {
      lastError = error
    }
  }

  if (sawHtmlResponse) {
    throw new Error('Expected binary document but received HTML response')
  }

  throw lastError || new Error('Unable to fetch document file')
}

export const fetchDocumentPreviewHtml = async (
  filePath: string,
  storageId?: number
): Promise<string> => {
  const endpoints = buildDocumentPreviewEndpoints(filePath, storageId)
  let lastError: unknown = null

  for (const endpoint of endpoints) {
    try {
      const response = await axiosInstance.get(endpoint, {
        responseType: 'text',
        params: { _ts: Date.now() },
        headers: {
          Accept: 'text/html',
          'Cache-Control': 'no-cache',
          Pragma: 'no-cache'
        }
      })
      const contentType = String(response.headers?.['content-type'] || '').toLowerCase()
      if (!contentType.includes('text/html')) {
        continue
      }
      return String(response.data || '')
    } catch (error) {
      lastError = error
    }
  }

  throw lastError || new Error('Unable to fetch document preview')
}

export const insertText = async (text: string, storageId?: number): Promise<DocActionResponse> => {
  const url = storageId ? `/storage/${storageId}/documents/text` : '/documents/text'
  const response = await axiosInstance.post(url, { text })
  return response.data
}

export const insertTexts = async (texts: string[], storageId?: number): Promise<DocActionResponse> => {
  const url = storageId ? `/storage/${storageId}/documents/texts` : '/documents/texts'
  const response = await axiosInstance.post(url, { texts })
  return response.data
}

export const uploadDocument = async (
  file: File,
  onUploadProgress?: (percentCompleted: number) => void,
  storageId?: number
): Promise<DocActionResponse> => {
  const formData = new FormData()
  formData.append('file', file)

  const url = storageId ? `/storage/${storageId}/documents/upload` : '/documents/upload'

  const response = await axiosInstance.post(url, formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    // prettier-ignore
    onUploadProgress:
      onUploadProgress !== undefined
        ? (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total!)
          onUploadProgress(percentCompleted)
        }
        : undefined
  })
  return response.data
}

export const batchUploadDocuments = async (
  files: File[],
  onUploadProgress?: (fileName: string, percentCompleted: number) => void
): Promise<DocActionResponse[]> => {
  return await Promise.all(
    files.map(async (file) => {
      return await uploadDocument(file, (percentCompleted) => {
        onUploadProgress?.(file.name, percentCompleted)
      })
    })
  )
}

export const clearDocuments = async (storageId?: number): Promise<DocActionResponse> => {
  const url = storageId ? `/storage/${storageId}/documents` : '/documents'
  const response = await axiosInstance.delete(url)
  return response.data
}

export const clearCache = async (storageId?: number): Promise<{
  status: 'success' | 'fail'
  message: string
}> => {
  const url = storageId ? `/storage/${storageId}/documents/clear_cache` : '/documents/clear_cache'
  const response = await axiosInstance.post(url, {})
  return response.data
}

export const deleteDocuments = async (
  docIds: string[],
  deleteFile: boolean = false,
  deleteLLMCache: boolean = false,
  storageId?: number
): Promise<DeleteDocResponse> => {
  const url = storageId ? `/storage/${storageId}/documents/delete_document` : '/documents/delete_document'
  const response = await axiosInstance.delete(url, {
    data: { doc_ids: docIds, delete_file: deleteFile, delete_llm_cache: deleteLLMCache }
  })
  return response.data
}

export const getAuthStatus = async (): Promise<AuthStatusResponse> => {
  const authStatusUrl = `${getBackendBaseUrl()}/auth-status`
  try {
    console.log('[auth] Requesting auth status from:', authStatusUrl)
    // Add a timeout to the request to prevent hanging
    const response = await axiosInstance.get('/auth-status', {
      timeout: 5000, // 5 second timeout
      headers: {
        Accept: 'application/json' // Explicitly request JSON
      }
    })

    console.log('[auth] Auth status response:', {
      url: authStatusUrl,
      status: response.status,
      contentType: response.headers['content-type'] || '',
      data: response.data
    })

    // Check if response is HTML (which indicates a redirect or wrong endpoint)
    const contentType = response.headers['content-type'] || ''
    if (contentType.includes('text/html')) {
      console.warn('Received HTML response instead of JSON for auth-status endpoint')
      console.warn('[auth] Falling back to auth_configured=true because auth-status returned HTML')
      return {
        auth_configured: true,
        auth_mode: 'enabled'
      }
    }

    // Strict validation of the response data
    if (
      response.data &&
      typeof response.data === 'object' &&
      'auth_configured' in response.data &&
      typeof response.data.auth_configured === 'boolean'
    ) {
      // For unconfigured auth, ensure we have an access token
      if (!response.data.auth_configured) {
        if (response.data.access_token && typeof response.data.access_token === 'string') {
          console.log('[auth] Auth disabled with guest token available')
          return response.data
        } else {
          console.warn('Auth not configured but no valid access token provided')
          console.warn('[auth] Falling back to auth_configured=true because guest token is missing or invalid')
        }
      } else {
        // For configured auth, just return the data
        console.log('[auth] Auth is configured according to backend response')
        return response.data
      }
    }

    // If response data is invalid but we got a response, log it
    console.warn('Received invalid auth status response:', response.data)
    console.warn('[auth] Falling back to auth_configured=true because auth-status payload was invalid')

    // Default to auth configured if response is invalid
    return {
      auth_configured: true,
      auth_mode: 'enabled'
    }
  } catch (error) {
    // If the request fails, assume authentication is configured
    console.error('Failed to get auth status:', errorMessage(error))
    console.error('[auth] Falling back to auth_configured=true because auth-status request failed:', {
      url: authStatusUrl,
      error
    })
    return {
      auth_configured: true,
      auth_mode: 'enabled'
    }
  }
}

export const waitForBackendHealth = async (
  options: WaitForBackendHealthOptions = {}
): Promise<LightragStatus> => {
  const timeoutMs = options.timeoutMs ?? 45000
  const pollIntervalMs = options.pollIntervalMs ?? 500
  const deadline = Date.now() + timeoutMs
  let lastError: string | null = null

  console.log('[health] Waiting for backend health:', {
    url: `${getBackendBaseUrl()}/health`,
    timeoutMs,
    pollIntervalMs
  })

  while (Date.now() < deadline) {
    const health = await checkHealth()
    if (health.status === 'healthy') {
      console.log('[health] Backend reported healthy:', health)
      return health
    }

    lastError = health.message || `Backend reported status: ${health.status}`
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs))
  }

  throw new Error(lastError || 'Timed out waiting for backend health')
}

export const getPipelineStatus = async (storageId?: number): Promise<PipelineStatusResponse> => {
  const url = storageId ? `/storage/${storageId}/documents/pipeline_status` : '/documents/pipeline_status'
  const response = await axiosInstance.get(url)
  return response.data
}

export const cancelPipeline = async (storageId?: number): Promise<{
  status: 'cancellation_requested' | 'not_busy'
  message: string
}> => {
  const url = storageId ? `/storage/${storageId}/documents/cancel_pipeline` : '/documents/cancel_pipeline'
  const response = await axiosInstance.post(url)
  return response.data
}

export const loginToServer = async (username: string, password: string): Promise<LoginResponse> => {
  const formData = new FormData()
  formData.append('username', username)
  formData.append('password', password)

  const response = await axiosInstance.post('/login', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })

  return response.data
}

/**
 * Updates an entity's properties in the knowledge graph
 * @param entityName The name of the entity to update
 * @param updatedData Dictionary containing updated attributes
 * @param allowRename Whether to allow renaming the entity (default: false)
 * @param allowMerge Whether to merge into an existing entity when renaming to a duplicate name
 * @returns Promise with the updated entity information
 */
export const updateEntity = async (
  entityName: string,
  updatedData: Record<string, any>,
  allowRename: boolean = false,
  allowMerge: boolean = false,
  storageId?: number
): Promise<EntityUpdateResponse> => {
  const url = storageId ? `/storage/${storageId}/graph/entity/edit` : '/graph/entity/edit'
  const response = await axiosInstance.post(url, {
    entity_name: entityName,
    updated_data: updatedData,
    allow_rename: allowRename,
    allow_merge: allowMerge
  })
  return response.data
}

/**
 * Updates a relation's properties in the knowledge graph
 * @param sourceEntity The source entity name
 * @param targetEntity The target entity name
 * @param updatedData Dictionary containing updated attributes
 * @returns Promise with the updated relation information
 */
export const updateRelation = async (
  sourceEntity: string,
  targetEntity: string,
  updatedData: Record<string, any>,
  storageId?: number
): Promise<DocActionResponse> => {
  const url = storageId ? `/storage/${storageId}/graph/relation/edit` : '/graph/relation/edit'
  const response = await axiosInstance.post(url, {
    source_id: sourceEntity,
    target_id: targetEntity,
    updated_data: updatedData
  })
  return response.data
}

/**
 * Checks if an entity name already exists in the knowledge graph
 * @param entityName The entity name to check
 * @returns Promise with boolean indicating if the entity exists
 */
export const checkEntityNameExists = async (entityName: string, storageId?: number): Promise<boolean> => {
  try {
    const url = storageId ? `/storage/${storageId}/graph/entity/exists` : '/graph/entity/exists'
    const response = await axiosInstance.get(
      `${url}?name=${encodeURIComponent(entityName)}`
    )
    return response.data.exists
  } catch (error) {
    console.error('Error checking entity name:', error)
    return false
  }
}

/**
 * Get the processing status of documents by tracking ID
 * @param trackId The tracking ID returned from upload, text, or texts endpoints
 * @returns Promise with the track status response containing documents and summary
 */
export const getTrackStatus = async (trackId: string, storageId?: number): Promise<TrackStatusResponse> => {
  const url = storageId
    ? `/storage/${storageId}/documents/track_status/${encodeURIComponent(trackId)}`
    : `/documents/track_status/${encodeURIComponent(trackId)}`
  const response = await axiosInstance.get(url)
  return response.data
}

/**
 * Get documents with pagination support
 * @param request The pagination request parameters
 * @returns Promise with paginated documents response
 */
export const getDocumentsPaginated = async (
  request: DocumentsRequest,
  storageId?: number
): Promise<PaginatedDocsResponse> => {
  // Use path parameter format: /storage/{id}/documents/paginated
  const url = storageId ? `/storage/${storageId}/documents/paginated` : '/documents/paginated'
  const response = await axiosInstance.post(url, request)
  return response.data
}

/**
 * Get counts of documents by status
 * @returns Promise with status counts response
 */
export const getDocumentStatusCounts = async (storageId?: number): Promise<StatusCountsResponse> => {
  const url = storageId ? `/storage/${storageId}/documents/status_counts` : '/documents/status_counts'
  const response = await axiosInstance.get(url)
  return response.data
}

const resolveArchiveCandidateUrls = (fileOrUrl: string): string[] => {
  const trimmed = fileOrUrl.trim()
  if (!trimmed) return []

  if (/^[a-zA-Z][a-zA-Z\d+\-.]*:/.test(trimmed)) {
    return [trimmed]
  }

  const normalizedPath = trimmed.startsWith('/') ? trimmed : `/${trimmed}`
  const candidates = new Set<string>([normalizedPath])

  if (typeof window !== 'undefined') {
    try {
      candidates.add(new URL(trimmed, window.location.href).toString())
    } catch {
      // Ignore URL parsing errors and continue with other candidates.
    }

    if (window.location.origin) {
      candidates.add(`${window.location.origin}${normalizedPath}`)

      const basePath =
        (import.meta.env.BASE_URL || '/').startsWith('/')
          ? import.meta.env.BASE_URL || '/'
          : `/${import.meta.env.BASE_URL || ''}`
      const normalizedBasePath = basePath.endsWith('/') ? basePath.slice(0, -1) : basePath
      if (normalizedBasePath && normalizedBasePath !== '/') {
        candidates.add(`${window.location.origin}${normalizedBasePath}${normalizedPath}`)
      }
    }
  }

  return Array.from(candidates)
}

export const isAbsoluteHttpUrl = (value: string): boolean => {
  const trimmed = value.trim()
  return /^https?:\/\//i.test(trimmed)
}

const downloadArchiveAsBlob = async (fileOrUrl: string): Promise<Blob> => {
  const attempted: string[] = []

  for (const candidate of resolveArchiveCandidateUrls(fileOrUrl)) {
    attempted.push(candidate)
    try {
      const response = await fetch(candidate)
      if (!response.ok) {
        continue
      }
      return await response.blob()
    } catch {
      continue
    }
  }

  throw new Error(
    `Failed to fetch archive from ${fileOrUrl}. Tried: ${attempted.join(', ')}`
  )
}

export const appendArchiveImportSource = async (
  formData: FormData,
  fileOrUrl: File | string,
  fallbackFileName: string
): Promise<void> => {
  if (typeof fileOrUrl === 'string') {
    const trimmedSource = fileOrUrl.trim()
    if (isAbsoluteHttpUrl(trimmedSource)) {
      formData.append('source_url', trimmedSource)
      return
    }

    const blob = await downloadArchiveAsBlob(trimmedSource)
    const file = new File([blob], fallbackFileName, { type: 'application/zip' })
    formData.append('file', file)
    return
  }

  formData.append('file', fileOrUrl)
}

/**
 * Create a new storage instance (tenant) with its own configuration
 * @param name The name for the new storage instance
 * @param settings The LLM and embedding settings for this instance
 * @returns Promise with the created storage information
 */
export const createNewStorage = async (
  name: string,
  settings: SettingsUpdateRequest
): Promise<{
  status: string
  message: string
  storage: {
    id: number
    name: string
    work_dir: string
  }
}> => {
  const response = await axiosInstance.post('/api/settings/new_storage', {
    name,
    storage_settings: settings
  })
  return response.data
}

export const importStorageArchive = async (
  name: string,
  fileOrUrl: File | string,
  embeddingImportMode: ArchiveEmbeddingImportMode = 'preindexed'
): Promise<{
  status: string
  message: string
  embedding_import_mode?: ArchiveEmbeddingImportMode
  storage: {
    id: number
    name: string
    work_dir: string
  }
}> => {
  const formData = await buildImportStorageArchiveFormData(
    name,
    fileOrUrl,
    embeddingImportMode
  )

  const response = await axiosInstance.post('/api/settings/storage/import', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
  return response.data
}

export const buildImportStorageArchiveFormData = async (
  name: string,
  fileOrUrl: File | string,
  embeddingImportMode: ArchiveEmbeddingImportMode = 'preindexed'
): Promise<FormData> => {
  const formData = new FormData()
  formData.append('name', name)
  formData.append('embedding_import_mode', embeddingImportMode)
  const safeName = name.replace(/[^a-z0-9]/gi, '_').toLowerCase() || 'imported_archive'
  await appendArchiveImportSource(formData, fileOrUrl, `${safeName}.zip`)
  return formData
}

export const exportStorageArchive = async (storageId: number): Promise<Blob> => {
  const response = await axiosInstance.get(`/api/settings/storage/${storageId}/export`, {
    responseType: 'blob'
  })
  return response.data
}

export const rebuildStorageEmbeddings = async (
  storageId: number
): Promise<RebuildEmbeddingsResponse> => {
  const response = await axiosInstance.post(`/api/settings/storage/${storageId}/reembed`)
  return response.data
}

export const analyzeStorageArchiveMerge = async (
  storageId: number,
  fileOrUrl: File | string
): Promise<StorageMergeAnalysisResponse> => {
  const formData = new FormData()
  await appendArchiveImportSource(formData, fileOrUrl, 'imported_archive.zip')

  const response = await axiosInstance.post(
    `/api/settings/storage/${storageId}/import/analyze`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    }
  )
  return response.data
}

export const applyStorageArchiveMerge = async (
  storageId: number,
  analysisId: string,
  conflictMode: 'archive_wins' | 'keep_existing'
): Promise<StorageMergeApplyResponse> => {
  const response = await axiosInstance.post(
    `/api/settings/storage/${storageId}/import/apply`,
    {
      analysis_id: analysisId,
      conflict_mode: conflictMode
    }
  )
  return response.data
}

