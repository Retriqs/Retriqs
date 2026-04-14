import { create, StoreApi, UseBoundStore } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { createSelectors } from '@/lib/utils'
import { defaultQueryLabel, DEFAULT_GRAPH_MAX_NODES } from '@/lib/constants'
import { Message, QueryRequest } from '@/api/retriqs'

type Theme = 'dark' | 'light' | 'system'
type Language = 'en' | 'zh' | 'fr' | 'ar' | 'zh_TW'
type Tab = 'documents' | 'knowledge-graph' | 'chat' | 'api' | 'settings' | 'marketplace' | 'feedback'

interface SettingsState {
  // Document manager settings
  showFileName: boolean
  setShowFileName: (show: boolean) => void

  documentsPageSize: number
  setDocumentsPageSize: (size: number) => void

  // User prompt history
  userPromptHistory: string[]
  addUserPromptToHistory: (prompt: string) => void
  setUserPromptHistory: (history: string[]) => void

  // Graph viewer settings
  showPropertyPanel: boolean
  showNodeSearchBar: boolean
  showLegend: boolean
  setShowLegend: (show: boolean) => void

  showNodeLabel: boolean
  enableNodeDrag: boolean

  showEdgeLabel: boolean
  enableHideUnselectedEdges: boolean
  enableEdgeEvents: boolean

  minEdgeSize: number
  setMinEdgeSize: (size: number) => void

  maxEdgeSize: number
  setMaxEdgeSize: (size: number) => void

  graphQueryMaxDepth: number
  setGraphQueryMaxDepth: (depth: number) => void

  graphMaxNodes: number
  setGraphMaxNodes: (nodes: number, triggerRefresh?: boolean) => void

  backendMaxGraphNodes: number | null
  setBackendMaxGraphNodes: (maxNodes: number | null) => void

  graphLayoutMaxIterations: number
  setGraphLayoutMaxIterations: (iterations: number) => void

  // Retrieval settings
  queryLabel: string
  setQueryLabel: (queryLabel: string) => void

  retrievalHistory: Message[]
  setRetrievalHistory: (history: Message[]) => void

  querySettings: Omit<QueryRequest, 'query'>
  updateQuerySettings: (settings: Partial<QueryRequest>) => void

  // Auth settings
  apiKey: string | null
  setApiKey: (key: string | null) => void

  // App settings
  theme: Theme
  setTheme: (theme: Theme) => void

  language: Language
  setLanguage: (lang: Language) => void

  enableHealthCheck: boolean
  setEnableHealthCheck: (enable: boolean) => void

  currentTab: Tab
  setCurrentTab: (tab: Tab) => void

  // Search label dropdown refresh trigger (non-persistent, runtime only)
  searchLabelDropdownRefreshTrigger: number
  triggerSearchLabelDropdownRefresh: () => void
}

type SettingsStore = UseBoundStore<StoreApi<SettingsState>>

const getSettingsStorageKey = (tenantId: number | null) =>
  `settings-storage:${tenantId ?? 'default'}`

const globalAppSettingsStorageKey = 'settings-global'

const getGlobalThemeStorage = (): { state?: { theme?: Theme } } | null => {
  if (typeof localStorage === 'undefined') return null

  try {
    const raw = localStorage.getItem(globalAppSettingsStorageKey)
    if (!raw) return null
    return JSON.parse(raw) as { state?: { theme?: Theme } }
  } catch {
    return null
  }
}

const readGlobalTheme = (): Theme => getGlobalThemeStorage()?.state?.theme ?? 'system'

const hasStoredGlobalTheme = () => getGlobalThemeStorage()?.state?.theme !== undefined

const writeGlobalTheme = (theme: Theme) => {
  if (typeof localStorage === 'undefined') return

  try {
    const parsed = getGlobalThemeStorage() as { state?: Record<string, unknown> } | null

    localStorage.setItem(
      globalAppSettingsStorageKey,
      JSON.stringify({
        ...(parsed ?? {}),
        state: {
          ...(parsed?.state ?? {}),
          theme
        }
      })
    )
  } catch {
    localStorage.setItem(
      globalAppSettingsStorageKey,
      JSON.stringify({
        state: { theme }
      })
    )
  }
}

const createSettingsStore = (storageKey: string) =>
  create<SettingsState>()(
    persist(
      (set) => ({
        theme: readGlobalTheme(),
        language: 'en',
        showPropertyPanel: true,
        showNodeSearchBar: true,
        showLegend: false,

        showNodeLabel: true,
        enableNodeDrag: true,

        showEdgeLabel: false,
        enableHideUnselectedEdges: true,
        enableEdgeEvents: false,

        minEdgeSize: 1,
        maxEdgeSize: 1,

        graphQueryMaxDepth: 3,
        graphMaxNodes: DEFAULT_GRAPH_MAX_NODES,
        backendMaxGraphNodes: null,
        graphLayoutMaxIterations: 15,

        queryLabel: defaultQueryLabel,

        enableHealthCheck: true,

        apiKey: null,

        currentTab: 'documents',
        showFileName: true,
        documentsPageSize: 10,

        retrievalHistory: [],
        userPromptHistory: [],

        querySettings: {
          mode: 'global',
          top_k: 40,
          chunk_top_k: 20,
          max_entity_tokens: 6000,
          max_relation_tokens: 8000,
          max_total_tokens: 30000,
          only_need_context: false,
          only_need_prompt: false,
          stream: true,
          history_turns: 0,
          user_prompt: '',
          enable_rerank: true
        },

        setTheme: (theme: Theme) => {
          writeGlobalTheme(theme)
          set({ theme })
        },

        setLanguage: (language: Language) => {
          set({ language })
        },

        setGraphLayoutMaxIterations: (iterations: number) =>
          set({
            graphLayoutMaxIterations: iterations
          }),

        setQueryLabel: (queryLabel: string) =>
          set({
            queryLabel
          }),

        setGraphQueryMaxDepth: (depth: number) => set({ graphQueryMaxDepth: depth }),

        setGraphMaxNodes: (nodes: number, triggerRefresh: boolean = false) => {
          const state = useSettingsStore.getState()
          if (state.graphMaxNodes === nodes) {
            return
          }

          if (triggerRefresh) {
            const currentLabel = state.queryLabel
            // Atomically update both the node count and the query label to trigger a refresh.
            set({ graphMaxNodes: nodes, queryLabel: '' })

            // Restore the label after a short delay.
            setTimeout(() => {
              set({ queryLabel: currentLabel })
            }, 300)
          } else {
            set({ graphMaxNodes: nodes })
          }
        },

        setBackendMaxGraphNodes: (maxNodes: number | null) => set({ backendMaxGraphNodes: maxNodes }),

        setMinEdgeSize: (size: number) => set({ minEdgeSize: size }),

        setMaxEdgeSize: (size: number) => set({ maxEdgeSize: size }),

        setEnableHealthCheck: (enable: boolean) => set({ enableHealthCheck: enable }),

        setApiKey: (apiKey: string | null) => set({ apiKey }),

        setCurrentTab: (tab: Tab) => set({ currentTab: tab }),

        setRetrievalHistory: (history: Message[]) => set({ retrievalHistory: history }),

        updateQuerySettings: (settings: Partial<QueryRequest>) => {
          // Filter out history_turns to prevent changes, always keep it as 0
          const filteredSettings = { ...settings }
          delete filteredSettings.history_turns
          set((state) => ({
            querySettings: { ...state.querySettings, ...filteredSettings, history_turns: 0 }
          }))
        },

        setShowFileName: (show: boolean) => set({ showFileName: show }),
        setShowLegend: (show: boolean) => set({ showLegend: show }),
        setDocumentsPageSize: (size: number) => set({ documentsPageSize: size }),

        // User prompt history methods
        addUserPromptToHistory: (prompt: string) => {
          if (!prompt.trim()) return

          set((state) => {
            const newHistory = [...state.userPromptHistory]

            // Remove existing occurrence if found
            const existingIndex = newHistory.indexOf(prompt)
            if (existingIndex !== -1) {
              newHistory.splice(existingIndex, 1)
            }

            // Add to beginning
            newHistory.unshift(prompt)

            // Keep only last 12 items
            if (newHistory.length > 12) {
              newHistory.splice(12)
            }

            return { userPromptHistory: newHistory }
          })
        },

        setUserPromptHistory: (history: string[]) => set({ userPromptHistory: history }),

        // Search label dropdown refresh trigger (not persisted)
        searchLabelDropdownRefreshTrigger: 0,
        triggerSearchLabelDropdownRefresh: () =>
          set((state) => ({
            searchLabelDropdownRefreshTrigger: state.searchLabelDropdownRefreshTrigger + 1
          }))
      }),
      {
        name: storageKey,
        storage: createJSONStorage(() => localStorage),
        partialize: (state) => {
          const { theme, ...persistedState } = state
          return persistedState
        },
        version: 21,
        merge: (persistedState, currentState) => {
          const persistedTheme = (persistedState as Partial<SettingsState>)?.theme
          const theme = hasStoredGlobalTheme() ? readGlobalTheme() : (persistedTheme ?? 'system')

          if (!hasStoredGlobalTheme() && persistedTheme) {
            writeGlobalTheme(persistedTheme)
          }

          return {
            ...currentState,
            ...(persistedState as Partial<SettingsState>),
            theme
          }
        },
        migrate: (state: any, version: number) => {
          if (version < 2) {
            state.showEdgeLabel = false
          }
          if (version < 3) {
            state.queryLabel = defaultQueryLabel
          }
          if (version < 4) {
            state.showPropertyPanel = true
            state.showNodeSearchBar = true
            state.showNodeLabel = true
            state.enableHealthCheck = true
            state.apiKey = null
          }
          if (version < 5) {
            state.currentTab = 'documents'
          }
          if (version < 6) {
            state.querySettings = {
              mode: 'global',
              response_type: 'Multiple Paragraphs',
              top_k: 10,
              max_token_for_text_unit: 4000,
              max_token_for_global_context: 4000,
              max_token_for_local_context: 4000,
              only_need_context: false,
              only_need_prompt: false,
              stream: true,
              history_turns: 0,
              hl_keywords: [],
              ll_keywords: []
            }
            state.retrievalHistory = []
          }
          if (version < 7) {
            state.graphQueryMaxDepth = 3
            state.graphLayoutMaxIterations = 15
          }
          if (version < 8) {
            state.graphMinDegree = 0
            state.language = 'en'
          }
          if (version < 9) {
            state.showFileName = false
          }
          if (version < 10) {
            delete state.graphMinDegree // 删除废弃参数
            state.graphMaxNodes = DEFAULT_GRAPH_MAX_NODES  // 添加新参数
          }
          if (version < 11) {
            state.minEdgeSize = 1
            state.maxEdgeSize = 1
          }
          if (version < 12) {
            // Clear retrieval history to avoid compatibility issues with MessageWithError type
            state.retrievalHistory = []
          }
          if (version < 13) {
            // Add user_prompt field for older versions
            if (state.querySettings) {
              state.querySettings.user_prompt = ''
            }
          }
          if (version < 14) {
            // Add backendMaxGraphNodes field for older versions
            state.backendMaxGraphNodes = null
          }
          if (version < 15) {
            // Add new querySettings
            state.querySettings = {
              ...state.querySettings,
              mode: 'mix',
              response_type: 'Multiple Paragraphs',
              top_k: 40,
              chunk_top_k: 10,
              max_entity_tokens: 10000,
              max_relation_tokens: 10000,
              max_total_tokens: 32000,
              enable_rerank: true,
              history_turns: 0,
            }
          }
          if (version < 16) {
            // Add documentsPageSize field for older versions
            state.documentsPageSize = 10
          }
          if (version < 17) {
            // Force history_turns to 0 for all users
            if (state.querySettings) {
              state.querySettings.history_turns = 0
            }
          }
          if (version < 18) {
            // Add userPromptHistory field for older versions
            state.userPromptHistory = []
          }
          if (version < 19) {
            // Remove deprecated response_type parameter
            if (state.querySettings) {
              delete state.querySettings.response_type
            }
          }
          if (version < 20) {
            // Show file names by default on the documents page.
            state.showFileName = true
          }
          if (version < 21) {
            if (state.currentTab === 'retrieval') {
              state.currentTab = 'chat'
            }
          }
          return state
        }
      }
    )
  )

const settingsStoreRef = {
  current: createSettingsStore(getSettingsStorageKey(null))
}

let currentStorageKey = getSettingsStorageKey(null)

type SubscriptionEntry = {
  listener: (state: SettingsState, prevState: SettingsState) => void
  selector?: (state: SettingsState) => unknown
  options?: { equalityFn?: (a: unknown, b: unknown) => boolean; fireImmediately?: boolean }
  unsubscribe: () => void
}

const subscriptions = new Set<SubscriptionEntry>()

const useSettingsStoreBase = ((selector: any, equality: any) =>
  (settingsStoreRef.current as any)(selector, equality)) as SettingsStore

useSettingsStoreBase.getState = () => settingsStoreRef.current.getState()
useSettingsStoreBase.setState = (partial: any, replace: any) =>
  settingsStoreRef.current.setState(partial, replace)
useSettingsStoreBase.subscribe = (listener: any, selector?: any, options?: any) => {
  const unsubscribe = (settingsStoreRef.current as any).subscribe(listener, selector, options)
  const entry: SubscriptionEntry = { listener, selector, options, unsubscribe }
  subscriptions.add(entry)
  return () => {
    entry.unsubscribe()
    subscriptions.delete(entry)
  }
}

const useSettingsStore = createSelectors(useSettingsStoreBase)

const setSettingsStoreTenant = (tenantId: number | null) => {
  const nextKey = getSettingsStorageKey(tenantId)
  if (nextKey === currentStorageKey) return

  const previousTab = settingsStoreRef.current.getState().currentTab
  currentStorageKey = nextKey
  settingsStoreRef.current = createSettingsStore(nextKey)
  settingsStoreRef.current.setState({ currentTab: previousTab })

  subscriptions.forEach((entry) => {
    entry.unsubscribe()
    entry.unsubscribe = (settingsStoreRef.current as any).subscribe(
      entry.listener,
      entry.selector as any,
      entry.options as any
    )
  })
}

export { setSettingsStoreTenant, useSettingsStore, type Theme }
