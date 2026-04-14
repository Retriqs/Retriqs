import Textarea from '@/components/ui/Textarea'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { throttle, cn } from '@/lib/utils'
import {
  createQueryChat,
  deleteQueryChat,
  getQueryChat,
  listQueryChats,
  queryText,
  queryTextStream,
  updateQueryChat,
  type QueryChatDetail,
  type QueryChatSummary,
  type QueryResponse,
  type QueryTrace
} from '@/api/retriqs'
import { errorMessage } from '@/lib/utils'
import { useSettingsStore } from '@/stores/settings'
import { useDebounce } from '@/hooks/useDebounce'
import { useTenant } from '@/contexts/TenantContext'
import QuerySettings from '@/components/retrieval/QuerySettings'
import { ChatMessage, MessageWithError } from '@/components/retrieval/ChatMessage'
import EvidencePanel from '@/components/retrieval/EvidencePanel'
import RetrievalChatSidebar from '@/components/retrieval/RetrievalChatSidebar'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import {
  EraserIcon,
  SendIcon,
  CopyIcon,
  Sparkles,
  Settings2,
  Loader2,
  PanelRightOpen,
  PanelRightClose
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { copyToClipboard } from '@/utils/clipboard'
import type { QueryMode } from '@/api/retriqs'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover'
import { trackEvent } from '@/lib/analytics'

// Helper function to generate unique IDs with browser compatibility
const generateUniqueId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
};

// LaTeX completeness detection function
const detectLatexCompleteness = (content: string): boolean => {
  const blockLatexMatches = content.match(/\$\$/g) || []
  const hasUnclosedBlock = blockLatexMatches.length % 2 !== 0
  const contentWithoutBlocks = content.replace(/\$\$[\s\S]*?\$\$/g, '')
  const inlineLatexMatches = contentWithoutBlocks.match(/(?<!\$)\$(?!\$)/g) || []
  return !hasUnclosedBlock && (inlineLatexMatches.length % 2 === 0)
}

// Robust COT parsing function
const parseCOTContent = (content: string) => {
  const thinkStartTag = '<think>'
  const thinkEndTag = '</think>'
  const startMatches: number[] = []
  const endMatches: number[] = []
  let startIndex = 0
  while ((startIndex = content.indexOf(thinkStartTag, startIndex)) !== -1) {
    startMatches.push(startIndex)
    startIndex += thinkStartTag.length
  }
  let endIndex = 0
  while ((endIndex = content.indexOf(thinkEndTag, endIndex)) !== -1) {
    endMatches.push(endIndex)
    endIndex += thinkEndTag.length
  }
  const hasThinkStart = startMatches.length > 0
  const hasThinkEnd = endMatches.length > 0
  const isThinking = hasThinkStart && (startMatches.length > endMatches.length)
  let thinkingContent = ''
  let displayContent = content
  if (hasThinkStart) {
    if (hasThinkEnd && startMatches.length === endMatches.length) {
      const lastStartIndex = startMatches[startMatches.length - 1]
      const lastEndIndex = endMatches[endMatches.length - 1]
      if (lastEndIndex > lastStartIndex) {
        thinkingContent = content.substring(lastStartIndex + thinkStartTag.length, lastEndIndex).trim()
        displayContent = content.substring(lastEndIndex + thinkEndTag.length).trim()
      }
    } else if (isThinking) {
      const lastStartIndex = startMatches[startMatches.length - 1]
      thinkingContent = content.substring(lastStartIndex + thinkStartTag.length)
      displayContent = ''
    }
  }
  return { isThinking, thinkingContent, displayContent, hasValidThinkBlock: hasThinkStart && hasThinkEnd && startMatches.length === endMatches.length }
}

type RetrievalMessage = MessageWithError & {
  dbMessageId?: number | null
  chatId?: number | null
  linkedUserMessageId?: number | null
  trace?: QueryTrace | null
  references?: QueryResponse['references']
  storageId?: number | null
}

const mapChatDetailToMessages = (
  detail: QueryChatDetail,
  tenantId: number | null
): RetrievalMessage[] => {
  let lastUserMessageId: number | null = null
  return detail.messages.map((msg, index) => {
    const snapshot = msg.retrieval_snapshot
    const traceFromSnapshot = (snapshot?.trace as QueryTrace | null | undefined)
      || (snapshot
        ? {
          data: (snapshot.data || {}) as any,
          metadata: (snapshot.metadata || {}) as any
        }
        : null)
    const referencesFromSnapshot = snapshot?.references || null
    if (msg.role === 'user') {
      lastUserMessageId = msg.id
    }

    return {
      id: `chat-${detail.id}-msg-${msg.id}-${index}`,
      dbMessageId: msg.id,
      chatId: detail.id,
      linkedUserMessageId: msg.role === 'assistant' ? lastUserMessageId : null,
      content: msg.content,
      role: msg.role,
      mermaidRendered: true,
      latexRendered: true,
      storageId: tenantId ?? undefined,
      trace: msg.role === 'user' ? traceFromSnapshot || null : null,
      references: msg.role === 'user' ? referencesFromSnapshot : null
    } as RetrievalMessage
  })
}

export default function RetrievalTesting() {
  const { t } = useTranslation()
  const { selectedTenantId } = useTenant()
  const currentTab = useSettingsStore.use.currentTab()
  const isRetrievalTabActive = currentTab === 'chat'

  const [messages, setMessages] = useState<RetrievalMessage[]>([])
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null)
  const selectedMessageIdRef = useRef<string | null>(null)
  
  useEffect(() => {
    selectedMessageIdRef.current = selectedMessageId
  }, [selectedMessageId])

  const [activeChatId, setActiveChatId] = useState<number | null>(null)
  const [chatList, setChatList] = useState<QueryChatSummary[]>([])
  const [sideTab, setSideTab] = useState<'evidence' | 'chats'>('evidence')
  const [isChatListLoading, setIsChatListLoading] = useState(false)
  const [isEvidenceCollapsed, setIsEvidenceCollapsed] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [inputError, setInputError] = useState('')
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)

  const hasMultipleLines = inputValue.includes('\n')

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setInputValue(e.target.value)
    if (inputError) setInputError('')
  }, [inputError])

  const loadChatList = useCallback(async (autoSelectFirst: boolean = false) => {
    if (!selectedTenantId) return
    setIsChatListLoading(true)
    try {
      const chats = await listQueryChats(selectedTenantId)
      setChatList(chats)
      if (autoSelectFirst && chats.length > 0) {
        setActiveChatId((prev) => prev ?? chats[0].id)
      }
    } catch (error) {
      console.error('Failed to load chat list:', error)
    } finally {
      setIsChatListLoading(false)
    }
  }, [selectedTenantId])

  const loadChatDetail = useCallback(async (chatId: number) => {
    if (!selectedTenantId) return
    try {
      const detail = await getQueryChat(chatId, selectedTenantId)
      const mapped = mapChatDetailToMessages(detail, selectedTenantId)
      setMessages((prev) => {
        let nextSelectedId: string | null = null
        const currentSelected = selectedMessageIdRef.current
        const currentMessage = prev.find((m) => m.id === currentSelected)

        if (currentMessage?.dbMessageId) {
          const matchingNew = mapped.find((m) => m.dbMessageId === currentMessage.dbMessageId)
          if (matchingNew) nextSelectedId = matchingNew.id
        }

        if (!nextSelectedId) {
          const lastQuestion = [...mapped].reverse().find((m) => m.role === 'user')
          nextSelectedId = lastQuestion?.id || mapped[mapped.length - 1]?.id || null
        }

        setTimeout(() => setSelectedMessageId(nextSelectedId), 0)
        return mapped
      })
    } catch (error) {
      console.error('Failed to load chat detail:', error)
      toast.error('Failed to load chat')
    }
  }, [selectedTenantId])

  useEffect(() => {
    setMessages([])
    setSelectedMessageId(null)
    setActiveChatId(null)
    setChatList([])
    loadChatList(true)
  }, [selectedTenantId, loadChatList])

  useEffect(() => {
    if (activeChatId) {
      loadChatDetail(activeChatId)
    } else {
      setMessages([])
      setSelectedMessageId(null)
    }
  }, [activeChatId, loadChatDetail])

  useEffect(() => {
    const syncLayout = () => {
      const mobile = window.innerWidth < 1024
      setIsMobile(mobile)
      setIsEvidenceCollapsed(mobile)
    }
    syncLayout()
    window.addEventListener('resize', syncLayout)
    return () => window.removeEventListener('resize', syncLayout)
  }, [])

  useEffect(() => {
    if (!selectedMessageId || !messages.some((m) => m.id === selectedMessageId)) {
      const firstQuestion = messages.find((m) => m.role === 'user')
      setSelectedMessageId(firstQuestion?.id || messages[messages.length - 1]?.id || null)
    }
  }, [messages, selectedMessageId])

  const adjustTextareaHeight = useCallback((element: HTMLTextAreaElement) => {
    requestAnimationFrame(() => {
      element.style.height = 'auto'
      element.style.height = Math.min(element.scrollHeight, 150) + 'px'
    })
  }, [])

  const scrollToBottom = useCallback(() => {
    programmaticScrollRef.current = true
    requestAnimationFrame(() => {
      if (messagesEndRef.current) {
        messagesEndRef.current.scrollIntoView({ behavior: 'auto' })
      }
    })
  }, [])

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!inputValue.trim() || isLoading || !selectedTenantId) return
      const allowedModes: QueryMode[] = ['naive', 'local', 'global', 'hybrid', 'mix', 'bypass']
      const prefixMatch = inputValue.match(/^\/(\w+)\s+([\s\S]+)/)
      let modeOverride: QueryMode | undefined = undefined
      let actualQuery = inputValue
      if (/^\/\S+/.test(inputValue) && !prefixMatch) {
        setInputError(t('retrievePanel.retrieval.queryModePrefixInvalid'))
        return
      }
      if (prefixMatch) {
        const mode = prefixMatch[1] as QueryMode
        const query = prefixMatch[2]
        if (!allowedModes.includes(mode)) {
          setInputError(t('retrievePanel.retrieval.queryModeError', { modes: 'naive, local, global, hybrid, mix, bypass' }))
          return
        }
        modeOverride = mode
        actualQuery = query
      }
      setInputError('')
      thinkingStartTime.current = null
      thinkingProcessed.current = false
      let resolvedChatId: number | null = activeChatId
      const userMessage: RetrievalMessage = {
        id: generateUniqueId(),
        content: inputValue,
        role: 'user',
        chatId: activeChatId ?? null,
        storageId: selectedTenantId
      }
      const assistantMessage: RetrievalMessage = {
        id: generateUniqueId(),
        content: '',
        role: 'assistant',
        mermaidRendered: false,
        latexRendered: false,
        thinkingTime: null,
        isThinking: false,
        linkedUserMessageId: null,
        trace: null,
        references: null,
        chatId: activeChatId ?? null,
        storageId: selectedTenantId
      }
      const prevMessages = [...messages]
      setMessages([...prevMessages, userMessage, assistantMessage])
      setSelectedMessageId(userMessage.id)
      shouldFollowScrollRef.current = true
      isReceivingResponseRef.current = true
      setTimeout(() => { scrollToBottom() }, 0)
      setInputValue('')
      setIsLoading(true)
      if (inputRef.current && 'style' in inputRef.current) { inputRef.current.style.height = '40px' }
      const updateAssistantMessage = (chunk: string, isError?: boolean) => {
        assistantMessage.content += chunk
        if (assistantMessage.content.includes('<think>') && !thinkingStartTime.current) { thinkingStartTime.current = Date.now() }
        const cotResult = parseCOTContent(assistantMessage.content)
        assistantMessage.isThinking = cotResult.isThinking
        if (cotResult.hasValidThinkBlock && !thinkingProcessed.current) {
          if (thinkingStartTime.current && !assistantMessage.thinkingTime) {
            const duration = (Date.now() - thinkingStartTime.current) / 1000
            assistantMessage.thinkingTime = parseFloat(duration.toFixed(2))
          }
          thinkingProcessed.current = true
        }
        assistantMessage.thinkingContent = cotResult.thinkingContent
        if (cotResult.isThinking) { assistantMessage.displayContent = '' } else { assistantMessage.displayContent = cotResult.displayContent || assistantMessage.content }
        const mermaidBlockRegex = /```mermaid\s+([\s\S]+?)```/g
        let mermaidRendered = false
        let match
        while ((match = mermaidBlockRegex.exec(assistantMessage.content)) !== null) {
          if (match[1] && match[1].trim().length > 10) { mermaidRendered = true; break }
        }
        assistantMessage.mermaidRendered = mermaidRendered
        assistantMessage.latexRendered = detectLatexCompleteness(assistantMessage.content)
        setMessages((prev) => {
          const newMessages = [...prev]
          const lastMessage = newMessages[newMessages.length - 1]
          if (lastMessage && lastMessage.id === assistantMessage.id) {
            Object.assign(lastMessage, { content: assistantMessage.content, thinkingContent: assistantMessage.thinkingContent, displayContent: assistantMessage.displayContent, isThinking: assistantMessage.isThinking, isError: isError, mermaidRendered: assistantMessage.mermaidRendered, latexRendered: assistantMessage.latexRendered, thinkingTime: assistantMessage.thinkingTime })
          }
          return newMessages
        })
        if (shouldFollowScrollRef.current) { setTimeout(() => { scrollToBottom() }, 30) }
      }
      const updateAssistantReferences = (references: QueryResponse['references']) => {
        assistantMessage.references = references
        setMessages((prev) => {
          const newMessages = [...prev]
          const lastMessage = newMessages[newMessages.length - 1] as RetrievalMessage | undefined
          if (lastMessage && lastMessage.id === assistantMessage.id) {
            lastMessage.references = references
          }
          const userIdx = newMessages.findIndex((m) => m.id === userMessage.id)
          if (userIdx >= 0) {
            newMessages[userIdx].references = references
          }
          return newMessages
        })
      }
      const updateAssistantTrace = (trace: QueryTrace | null | undefined) => {
        assistantMessage.trace = trace || null
        setMessages((prev) => {
          const newMessages = [...prev]
          const lastMessage = newMessages[newMessages.length - 1] as RetrievalMessage | undefined
          if (lastMessage && lastMessage.id === assistantMessage.id) {
            lastMessage.trace = trace || null
          }
          const userIdx = newMessages.findIndex((m) => m.id === userMessage.id)
          if (userIdx >= 0) {
            newMessages[userIdx].trace = trace || null
          }
          return newMessages
        })
      }
      const state = useSettingsStore.getState()
      if (state.querySettings.user_prompt && state.querySettings.user_prompt.trim()) { state.addUserPromptToHistory(state.querySettings.user_prompt.trim()) }
      const effectiveMode = modeOverride || state.querySettings.mode
      const configuredHistoryTurns = state.querySettings.history_turns || 0
      const effectiveHistoryTurns = (effectiveMode === 'bypass' && configuredHistoryTurns === 0) ? 3 : configuredHistoryTurns
      const queryParams = {
        ...state.querySettings,
        query: actualQuery,
        response_type: 'Multiple Paragraphs',
        include_references: true,
        include_chunk_content: true,
        include_trace: true,
        conversation_history: effectiveHistoryTurns > 0
          ? prevMessages.filter((m) => m.isError !== true).slice(-effectiveHistoryTurns * 2).map((m) => ({ role: m.role, content: m.content }))
          : [],
        chat_id: activeChatId ?? undefined,
        ...(modeOverride ? { mode: modeOverride } : {})
      }
      try {
        if (state.querySettings.stream) {
          let errorMessage = ''
          await queryTextStream(
            queryParams,
            updateAssistantMessage,
            (error) => { errorMessage += error },
            (references) => updateAssistantReferences(references),
            (trace) => updateAssistantTrace(trace),
            (chatPayload) => {
              if (chatPayload?.chat_id) {
                resolvedChatId = chatPayload.chat_id
              }
            },
            selectedTenantId
          )
          if (errorMessage) { if (assistantMessage.content) { errorMessage = assistantMessage.content + '\n' + errorMessage }; updateAssistantMessage(errorMessage, true) }
        } else {
          const response = await queryText(queryParams, selectedTenantId)
          updateAssistantMessage(response.response)
          updateAssistantReferences(response.references || null)
          updateAssistantTrace(response.trace || null)
          if (response.chat_id) {
            resolvedChatId = response.chat_id
          }
        }
        trackEvent('query_completed', {
          mode: effectiveMode,
          stream: state.querySettings.stream,
          has_trace: Boolean(assistantMessage.trace),
          has_references: Boolean(assistantMessage.references?.length),
          response_length: assistantMessage.content.length,
          storage_id: selectedTenantId
        })
      } catch (err) {
        const queryFailure = errorMessage(err)
        trackEvent('query_failed', {
          mode: effectiveMode,
          stream: state.querySettings.stream,
          error_message: queryFailure,
          storage_id: selectedTenantId
        })
        updateAssistantMessage(`${t('retrievePanel.retrieval.error')}\n${queryFailure}`, true)
      } finally {
        setIsLoading(false)
        isReceivingResponseRef.current = false
        try {
          const finalCotResult = parseCOTContent(assistantMessage.content)
          assistantMessage.isThinking = false
          if (finalCotResult.hasValidThinkBlock && thinkingStartTime.current && !assistantMessage.thinkingTime) {
            const duration = (Date.now() - thinkingStartTime.current) / 1000
            assistantMessage.thinkingTime = parseFloat(duration.toFixed(2))
          }
          if (finalCotResult.displayContent !== undefined) { assistantMessage.displayContent = finalCotResult.displayContent }
        } catch (error) {
          console.error('Error in final COT state validation:', error)
          assistantMessage.isThinking = false
        } finally { thinkingStartTime.current = null }
        await loadChatList()
        if (resolvedChatId && activeChatId !== resolvedChatId) {
          setActiveChatId(resolvedChatId)
        } else if (resolvedChatId) {
          await loadChatDetail(resolvedChatId)
        }
      }
    },
    [
      activeChatId,
      inputValue,
      isLoading,
      loadChatDetail,
      loadChatList,
      messages,
      selectedTenantId,
      setMessages,
      t,
      scrollToBottom
    ]
  )

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault()
      const target = e.target as any
      const start = target.selectionStart || 0
      const end = target.selectionEnd || 0
      const newValue = inputValue.slice(0, start) + '\n' + inputValue.slice(end)
      setInputValue(newValue)
      setTimeout(() => {
        if (target.setSelectionRange) { target.setSelectionRange(start + 1, start + 1) }
        if (inputRef.current && inputRef.current.tagName === 'TEXTAREA') { adjustTextareaHeight(inputRef.current as HTMLTextAreaElement) }
      }, 0)
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e as any)
    }
  }, [inputValue, handleSubmit, adjustTextareaHeight])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const pastedText = e.clipboardData.getData('text')
    if (pastedText.includes('\n')) {
      e.preventDefault()
      const target = e.target as any
      const start = target.selectionStart || 0
      const end = target.selectionEnd || 0
      const newValue = inputValue.slice(0, start) + pastedText + inputValue.slice(end)
      setInputValue(newValue)
      setTimeout(() => {
        if (inputRef.current && inputRef.current.setSelectionRange) {
          const newCursorPosition = start + pastedText.length
          inputRef.current.setSelectionRange(newCursorPosition, newCursorPosition)
        }
      }, 0)
    }
  }, [inputValue])

  useEffect(() => {
    if (inputRef.current) {
      const currentElement = inputRef.current
      const cursorPosition = currentElement.selectionStart || inputValue.length
      requestAnimationFrame(() => {
        currentElement.focus()
        if (currentElement.setSelectionRange) { currentElement.setSelectionRange(cursorPosition, cursorPosition) }
      })
    }
  }, [hasMultipleLines, inputValue.length])

  useEffect(() => {
    if (hasMultipleLines && inputRef.current && inputRef.current.tagName === 'TEXTAREA') {
      adjustTextareaHeight(inputRef.current as HTMLTextAreaElement)
    }
  }, [hasMultipleLines, inputValue, adjustTextareaHeight])

  const shouldFollowScrollRef = useRef(true)
  const thinkingStartTime = useRef<number | null>(null)
  const thinkingProcessed = useRef(false)
  const isFormInteractionRef = useRef(false)
  const programmaticScrollRef = useRef(false)
  const isReceivingResponseRef = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)

  useEffect(() => { return () => { if (thinkingStartTime.current) { thinkingStartTime.current = null } } }, [])

  useEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return
    const handleWheel = (e: WheelEvent) => { if (Math.abs(e.deltaY) > 10 && !isFormInteractionRef.current) { shouldFollowScrollRef.current = false } }
    const handleScroll = throttle(() => {
      if (programmaticScrollRef.current) { programmaticScrollRef.current = false; return }
      const container = messagesContainerRef.current
      if (container) {
        const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 20
        if (isAtBottom) { shouldFollowScrollRef.current = true } else if (!isFormInteractionRef.current && !isReceivingResponseRef.current) { shouldFollowScrollRef.current = false }
      }
    }, 30)
    container.addEventListener('wheel', handleWheel as EventListener)
    container.addEventListener('scroll', handleScroll as EventListener)
    return () => {
      container.removeEventListener('wheel', handleWheel as EventListener)
      container.removeEventListener('scroll', handleScroll as EventListener)
    }
  }, [])

  useEffect(() => {
    const form = document.querySelector('form')
    if (!form) return
    const handleFormMouseDown = () => { isFormInteractionRef.current = true; setTimeout(() => { isFormInteractionRef.current = false }, 500) }
    form.addEventListener('mousedown', handleFormMouseDown)
    return () => { form.removeEventListener('mousedown', handleFormMouseDown) }
  }, [])

  const debouncedMessages = useDebounce(messages, 150)
  useEffect(() => { if (shouldFollowScrollRef.current) { scrollToBottom() } }, [debouncedMessages, scrollToBottom])

  const handleCreateChat = useCallback(async () => {
    if (!selectedTenantId) return
    try {
      const created = await createQueryChat({ title: 'New chat' }, selectedTenantId)
      setChatList((prev) => [created, ...prev])
      setActiveChatId(created.id)
      setMessages([])
      setSelectedMessageId(null)
      setSideTab('chats')
      setIsEvidenceCollapsed(false)
    } catch {
      toast.error('Failed to create chat')
    }
  }, [selectedTenantId])

  const handleRenameChat = useCallback(
    async (chatId: number, title: string) => {
      if (!selectedTenantId) return
      try {
        const updated = await updateQueryChat(chatId, { title }, selectedTenantId)
        setChatList((prev) => prev.map((chat) => (chat.id === chatId ? { ...chat, ...updated } : chat)))
      } catch {
        toast.error('Failed to rename chat')
      }
    },
    [selectedTenantId]
  )

  const handleTogglePinChat = useCallback(
    async (chatId: number, nextPinned: boolean) => {
      if (!selectedTenantId) return
      try {
        const updated = await updateQueryChat(chatId, { is_pinned: nextPinned }, selectedTenantId)
        setChatList((prev) => prev.map((chat) => (chat.id === chatId ? { ...chat, ...updated } : chat)))
      } catch {
        toast.error('Failed to update pin')
      }
    },
    [selectedTenantId]
  )

  const handleDeleteChat = useCallback(
    async (chatId: number) => {
      if (!selectedTenantId) return
      try {
        await deleteQueryChat(chatId, selectedTenantId)
        const nextList = chatList.filter((chat) => chat.id !== chatId)
        setChatList(nextList)
        if (activeChatId === chatId) {
          const nextActive = nextList[0]?.id ?? null
          setActiveChatId(nextActive)
        }
      } catch {
        toast.error('Failed to delete chat')
      }
    },
    [activeChatId, chatList, selectedTenantId]
  )

  const handleCopyMessage = useCallback(async (message: MessageWithError) => {
    const contentToCopy = message.role === 'user' ? (message.content || '') : (message.displayContent !== undefined ? message.displayContent : (message.content || ''))
    if (!contentToCopy.trim()) { toast.error(t('retrievePanel.chatMessage.copyEmpty')); return }
    try {
      const result = await copyToClipboard(contentToCopy)
      if (result.success) { toast.success(t('retrievePanel.chatMessage.copySuccess')) } else { toast.error(t('retrievePanel.chatMessage.copyFailed')) }
    } catch { toast.error(t('retrievePanel.chatMessage.copyError')) }
  }, [t])

  const selectedEvidenceSource = useMemo(() => {
    if (!messages.length) return null
    const selected = selectedMessageId
      ? messages.find((m) => m.id === selectedMessageId)
      : null
    if (!selected) return messages[messages.length - 1]

    if (selected.role === 'user') return selected
    if (selected.trace || selected.references) return selected
    if (selected.linkedUserMessageId) {
      const linked = messages.find((m) => m.dbMessageId === selected.linkedUserMessageId)
      if (linked) return linked
    }
    const selectedIndex = messages.findIndex((m) => m.id === selected.id)
    for (let i = selectedIndex - 1; i >= 0; i -= 1) {
      const candidate = messages[i]
      if (candidate.role === 'user' && (candidate.trace || candidate.references)) {
        return candidate
      }
    }
    return selected
  }, [messages, selectedMessageId])

  return (
    <div className="flex h-full premium-bg overflow-hidden relative">
      <div className={cn('h-full flex flex-col min-w-0 transition-all duration-200', isEvidenceCollapsed ? 'w-full' : 'w-full lg:w-[60%]')}>
        <div ref={messagesContainerRef} className="flex-1 overflow-y-auto w-full scrollbar-thin" onClick={() => { if (shouldFollowScrollRef.current) { shouldFollowScrollRef.current = false } }}>
          <div className="mx-auto max-w-3xl lg:max-w-4xl w-full px-4 py-8 flex flex-col gap-8">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center min-h-[50vh] text-center space-y-6 animate-in fade-in slide-in-from-bottom-5 duration-700">
                <div className="h-20 w-20 rounded-3xl bg-primary/10 flex items-center justify-center text-primary shadow-inner">
                  <Sparkles className="h-10 w-10" />
                </div>
                <div className="space-y-2">
                  <h2 className="text-2xl font-black tracking-tight">{t('retrievePanel.retrieval.startPrompt')}</h2>
                  <p className="text-muted-foreground text-sm max-w-sm mx-auto opacity-70">Ask anything about your knowledge base.</p>
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <div key={message.id} className={`flex w-full ${message.role === 'user' ? 'justify-end' : 'justify-start'} animate-in fade-in duration-300 px-2`}>
                  <div className={cn('flex flex-col gap-1.5', message.role === 'user' ? 'max-w-[70%] items-end' : 'max-w-[85%] lg:max-w-[90%] items-start')}>
                    <div
                      className={cn(
                        'group relative transition-all rounded-2xl',
                        selectedMessageId === message.id && 'ring-2 ring-primary/40 shadow-lg shadow-primary/10'
                      )}
                      onClick={() => {
                        setSelectedMessageId(message.id)
                        if (isEvidenceCollapsed) setIsEvidenceCollapsed(false)
                        setSideTab('evidence')
                      }}
                    >
                      <ChatMessage message={message} isTabActive={isRetrievalTabActive} />
                      <div className={cn('absolute top-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1', message.role === 'user' ? '-left-8' : '-right-8')}>
                        <Button onClick={() => handleCopyMessage(message)} className="size-6 rounded-lg bg-card/80 glass border-none shadow-sm" variant="ghost" size="icon"><CopyIcon className="size-3" /></Button>
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
            <div ref={messagesEndRef} className="h-4" />
          </div>
        </div>

        <div className="shrink-0 pb-6 px-4">
          <div className="mx-auto max-w-3xl lg:max-w-4xl w-full">
            <form onSubmit={handleSubmit} className="relative group glass-card border border-border/10 rounded-2xl shadow-2xl shadow-primary/5 focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/20 transition-all duration-500 overflow-hidden" autoComplete="on" method="post" action="#" role="search">
              <div className="absolute inset-0 bg-gradient-to-b from-primary/5 to-transparent opacity-0 group-focus-within:opacity-100 transition-opacity pointer-events-none" />
              <div className="flex items-end p-2 gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={handleCreateChat}
                  disabled={isLoading}
                  size="icon"
                  className="h-10 w-10 shrink-0 text-muted-foreground hover:text-primary hover:bg-primary/5"
                  tooltip="New chat"
                >
                  <EraserIcon className="h-4 w-4" />
                </Button>
                <div className="flex-1 relative pb-1">
                  {hasMultipleLines ? (
                    <Textarea ref={inputRef as React.RefObject<HTMLTextAreaElement>} id="query-input" className="w-full border-0 focus-visible:ring-0 shadow-none scrollbar-hide py-3 text-sm min-h-[44px]" value={inputValue} onChange={handleChange} onKeyDown={handleKeyDown} onPaste={handlePaste} placeholder={t('retrievePanel.retrieval.placeholder')} disabled={isLoading} style={{ resize: 'none' }} />
                  ) : (
                    <Input ref={inputRef as React.RefObject<HTMLInputElement>} id="query-input" className="w-full border-0 focus-visible:ring-0 shadow-none h-10 text-sm" value={inputValue} onChange={handleChange} onKeyDown={handleKeyDown} onPaste={handlePaste} placeholder={t('retrievePanel.retrieval.placeholder')} disabled={isLoading} />
                  )}
                </div>
                <div className="flex items-center gap-1.5 shrink-0 px-1 pb-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-10 w-10 text-muted-foreground hover:bg-primary/5 hover:text-primary transition-all duration-300 rounded-xl"
                    onClick={() => setIsEvidenceCollapsed((prev) => !prev)}
                    tooltip={isEvidenceCollapsed ? 'Show evidence panel' : 'Hide evidence panel'}
                  >
                    {isEvidenceCollapsed ? <PanelRightOpen className="h-4.5 w-4.5" /> : <PanelRightClose className="h-4.5 w-4.5" />}
                  </Button>
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10 text-muted-foreground hover:bg-primary/5 hover:text-primary transition-all duration-300 rounded-xl"
                        tooltip="Tune Search Parameters"
                      >
                        <Settings2 className="h-4.5 w-4.5" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      className="w-[450px] p-0 border-none shadow-2xl bg-transparent"
                      align="end"
                      side="top"
                      sideOffset={16}
                      alignOffset={-10}
                    >
                      <QuerySettings className="w-full" />
                    </PopoverContent>
                  </Popover>
                  <Button type="submit" disabled={isLoading || !inputValue.trim()} size="sm" className="h-9 px-4 rounded-xl font-bold text-xs shadow-lg shadow-primary/20 active:scale-95 transition-all">
                    {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Send</span><SendIcon className="ml-2 h-3.5 w-3.5" /></>}
                  </Button>
                </div>
              </div>
              {inputError && <div className="absolute left-4 -top-8 px-2 py-1 bg-destructive/10 text-destructive text-[10px] font-bold rounded-md border border-destructive/20 animate-in fade-in slide-in-from-bottom-1">{inputError}</div>}
            </form>
            <p className="mt-3 text-center text-[11px] text-muted-foreground leading-relaxed">
              <span className="opacity-60 block mb-0.5">Retriqs provides the data context; responses are generated by your configured model and may be inaccurate.</span>
              <span className="opacity-40 font-medium">Check your model provider&apos;s privacy terms.</span>
            </p>
          </div>
        </div>

      </div>

      {!isEvidenceCollapsed && (
        <div
          className={cn(
            'h-full glass-card z-20 relative border-l border-border/10 shadow-[-10px_0_30px_rgba(0,0,0,0.05)] transition-all duration-500',
            isMobile ? 'absolute inset-y-0 right-0 w-full' : 'hidden lg:block lg:w-[40%]'
          )}
        >
          {isMobile && (
            <div className="absolute right-2 top-2 z-30">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 bg-background/90 border"
                onClick={() => setIsEvidenceCollapsed(true)}
              >
                <PanelRightClose className="h-4 w-4" />
              </Button>
            </div>
          )}
          <Tabs
            value={sideTab}
            onValueChange={(next) => setSideTab(next as 'evidence' | 'chats')}
            className="h-full flex flex-col"
          >
            <div className="p-2 border-b bg-muted/30">
              <TabsList className="h-8">
                <TabsTrigger value="evidence" className="text-xs px-3 py-1">
                  Evidence
                </TabsTrigger>
                <TabsTrigger value="chats" className="text-xs px-3 py-1">
                  Chats
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="evidence" className="flex-1 min-h-0 m-0">
              <EvidencePanel
                trace={selectedEvidenceSource?.trace || null}
                references={selectedEvidenceSource?.references || null}
                storageId={selectedEvidenceSource?.storageId ?? selectedTenantId ?? undefined}
              />
            </TabsContent>

            <TabsContent value="chats" className="flex-1 min-h-0 m-0">
              <RetrievalChatSidebar
                chats={chatList}
                activeChatId={activeChatId}
                onSelectChat={(chatId) => {
                  setActiveChatId(chatId)
                  if (isMobile && isEvidenceCollapsed) {
                    setIsEvidenceCollapsed(false)
                  }
                }}
                onCreateChat={handleCreateChat}
                onRenameChat={handleRenameChat}
                onTogglePinChat={handleTogglePinChat}
                onDeleteChat={handleDeleteChat}
                isLoading={isChatListLoading}
              />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </div>
  )
}
