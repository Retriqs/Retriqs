import { useMemo, useState } from 'react'
import type { QueryChatSummary } from '@/api/retriqs'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { cn } from '@/lib/utils'
import {
  MessageSquareText,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Trash2
} from 'lucide-react'

type RetrievalChatSidebarProps = {
  chats: QueryChatSummary[]
  activeChatId: number | null
  onSelectChat: (chatId: number) => void
  onCreateChat: () => void
  onRenameChat: (chatId: number, title: string) => void
  onTogglePinChat: (chatId: number, value: boolean) => void
  onDeleteChat: (chatId: number) => void
  isLoading?: boolean
}

export default function RetrievalChatSidebar({
  chats,
  activeChatId,
  onSelectChat,
  onCreateChat,
  onRenameChat,
  onTogglePinChat,
  onDeleteChat,
  isLoading = false
}: RetrievalChatSidebarProps) {
  const [editingChatId, setEditingChatId] = useState<number | null>(null)
  const [draftTitle, setDraftTitle] = useState('')

  const orderedChats = useMemo(
    () =>
      [...chats].sort((a, b) => {
        if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1
        const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0
        const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0
        return bTime - aTime
      }),
    [chats]
  )

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b bg-muted/30 flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Chats</h3>
        <Button
          size="sm"
          className="h-7 px-2 text-[11px]"
          onClick={onCreateChat}
          disabled={isLoading}
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          New
        </Button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1.5">
        {orderedChats.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-xs text-muted-foreground px-4">
            <MessageSquareText className="h-5 w-5 mb-2 opacity-60" />
            No chats yet.
          </div>
        ) : (
          orderedChats.map((chat) => (
            <div
              key={chat.id}
              className={cn(
                'group rounded-lg border bg-background/80 hover:bg-muted/40',
                activeChatId === chat.id ? 'border-primary/40 ring-1 ring-primary/30' : 'border-border'
              )}
            >
              <button
                type="button"
                onClick={() => onSelectChat(chat.id)}
                className="w-full text-left px-2.5 py-2"
              >
                {editingChatId === chat.id ? (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault()
                      onRenameChat(chat.id, draftTitle)
                      setEditingChatId(null)
                    }}
                  >
                    <Input
                      autoFocus
                      value={draftTitle}
                      className="h-7 text-xs"
                      onChange={(e) => setDraftTitle(e.target.value)}
                      onBlur={() => {
                        onRenameChat(chat.id, draftTitle)
                        setEditingChatId(null)
                      }}
                    />
                  </form>
                ) : (
                  <>
                    <div className="text-xs font-semibold flex items-center gap-1.5">
                      {chat.is_pinned && <Pin className="h-3 w-3 text-primary" />}
                      <span className="truncate">{chat.title || 'New chat'}</span>
                    </div>
                    <div className="text-[10px] text-muted-foreground truncate mt-0.5">
                      {chat.last_message_preview || 'No messages yet'}
                    </div>
                  </>
                )}
              </button>

              <div className="px-2.5 pb-2 hidden group-hover:flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => {
                    setEditingChatId(chat.id)
                    setDraftTitle(chat.title || '')
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => onTogglePinChat(chat.id, !chat.is_pinned)}
                >
                  {chat.is_pinned ? (
                    <PinOff className="h-3.5 w-3.5" />
                  ) : (
                    <Pin className="h-3.5 w-3.5" />
                  )}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-destructive hover:text-destructive"
                  onClick={() => onDeleteChat(chat.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

