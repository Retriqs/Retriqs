import { useCallback, useMemo } from 'react'
import { QueryMode, QueryRequest } from '@/api/retriqs'
import Checkbox from '@/components/ui/Checkbox'
import Input from '@/components/ui/Input'
import UserPromptInputWithHistory from '@/components/ui/UserPromptInputWithHistory'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/Select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/Tooltip'
import { useSettingsStore } from '@/stores/settings'
import { useTranslation } from 'react-i18next'
import { RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function QuerySettings({ className }: { className?: string }) {
  const { t } = useTranslation()
  const querySettings = useSettingsStore((state) => state.querySettings)
  const userPromptHistory = useSettingsStore((state) => state.userPromptHistory)

  const handleChange = useCallback((key: keyof QueryRequest, value: any) => {
    useSettingsStore.getState().updateQuerySettings({ [key]: value })
  }, [])

  const handleSelectFromHistory = useCallback((prompt: string) => {
    handleChange('user_prompt', prompt)
  }, [handleChange])

  const handleDeleteFromHistory = useCallback((index: number) => {
    const newHistory = [...userPromptHistory]
    newHistory.splice(index, 1)
    useSettingsStore.getState().setUserPromptHistory(newHistory)
  }, [userPromptHistory])

  // Default values for reset functionality
  const defaultValues = useMemo(() => ({
    mode: 'mix' as QueryMode,
    top_k: 40,
    chunk_top_k: 20,
    max_entity_tokens: 6000,
    max_relation_tokens: 8000,
    max_total_tokens: 30000
  }), [])

  const handleReset = useCallback((key: keyof typeof defaultValues) => {
    handleChange(key, defaultValues[key])
  }, [handleChange, defaultValues])

  // Reset button component
  const ResetButton = ({ onClick, title }: { onClick: () => void; title: string }) => (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onClick}
            className="mr-1 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <RotateCcw className="h-3 w-3 text-gray-400 hover:text-primary transition-colors" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="left">
          <p>{title}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )

  return (
    <div className={cn("flex flex-col bg-card border rounded-xl overflow-hidden shadow-2xl", className)}>
      <div className="px-5 py-4 border-b bg-muted/50">
        <h3 className="font-bold tracking-tight text-sm flex items-center gap-2">
          {t('retrievePanel.querySettings.parametersTitle')}
        </h3>
        <p className="text-[10px] text-muted-foreground mt-0.5 uppercase font-medium tracking-wider opacity-70">
          Search Configuration
        </p>
      </div>

      <div className="p-4 flex flex-col gap-5 text-xs overflow-y-auto max-h-[70vh] scrollbar-hide">
        {/* Query Mode */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label htmlFor="query_mode_select" className="text-[11px] font-semibold text-muted-foreground uppercase tracking-tight">
              {t('retrievePanel.querySettings.queryMode')}
            </label>
            <ResetButton onClick={() => handleReset('mode')} title="Reset to default (Mix)" />
          </div>
          <Select
            value={querySettings.mode}
            onValueChange={(v) => handleChange('mode', v as QueryMode)}
          >
            <SelectTrigger id="query_mode_select" className="h-9 focus:ring-1 focus:ring-primary/20 bg-background/50 border-input/50">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="naive">{t('retrievePanel.querySettings.queryModeOptions.naive')}</SelectItem>
                <SelectItem value="local">{t('retrievePanel.querySettings.queryModeOptions.local')}</SelectItem>
                <SelectItem value="global">{t('retrievePanel.querySettings.queryModeOptions.global')}</SelectItem>
                <SelectItem value="hybrid">{t('retrievePanel.querySettings.queryModeOptions.hybrid')}</SelectItem>
                <SelectItem value="mix">{t('retrievePanel.querySettings.queryModeOptions.mix')}</SelectItem>
                <SelectItem value="bypass">{t('retrievePanel.querySettings.queryModeOptions.bypass')}</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        {/* Top K Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="top_k" className="text-[11px] font-semibold text-muted-foreground uppercase tracking-tight">
                {t('retrievePanel.querySettings.topK')}
              </label>
              <ResetButton onClick={() => handleReset('top_k')} title="Reset to default" />
            </div>
            <Input
              id="top_k"
              type="number"
              value={querySettings.top_k ?? ''}
              onChange={(e) => {
                const value = e.target.value
                handleChange('top_k', value === '' ? '' : parseInt(value) || 0)
              }}
              className="h-9 bg-background/50 border-input/50"
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="chunk_top_k" className="text-[11px] font-semibold text-muted-foreground uppercase tracking-tight">
                {t('retrievePanel.querySettings.chunkTopK')}
              </label>
              <ResetButton onClick={() => handleReset('chunk_top_k')} title="Reset to default" />
            </div>
            <Input
              id="chunk_top_k"
              type="number"
              value={querySettings.chunk_top_k ?? ''}
              onChange={(e) => {
                const value = e.target.value
                handleChange('chunk_top_k', value === '' ? '' : parseInt(value) || 0)
              }}
              className="h-9 bg-background/50 border-input/50"
            />
          </div>
        </div>

        {/* Entity/Relation Token Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="max_entity_tokens" className="text-[11px] font-semibold text-muted-foreground uppercase tracking-tight">
                Entity Tokens
              </label>
              <ResetButton onClick={() => handleReset('max_entity_tokens')} title="Reset" />
            </div>
            <Input
              id="max_entity_tokens"
              type="number"
              value={querySettings.max_entity_tokens ?? ''}
              onChange={(e) => {
                const value = e.target.value
                handleChange('max_entity_tokens', value === '' ? '' : parseInt(value) || 0)
              }}
              className="h-9 bg-background/50 border-input/50"
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="max_relation_tokens" className="text-[11px] font-semibold text-muted-foreground uppercase tracking-tight text-right w-full">
                Relation Tokens
              </label>
              <ResetButton onClick={() => handleReset('max_relation_tokens')} title="Reset" />
            </div>
            <Input
              id="max_relation_tokens"
              type="number"
              value={querySettings.max_relation_tokens ?? ''}
              onChange={(e) => {
                const value = e.target.value
                handleChange('max_relation_tokens', value === '' ? '' : parseInt(value) || 0)
              }}
              className="h-9 bg-background/50 border-input/50"
            />
          </div>
        </div>

        {/* Max Total Tokens */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label htmlFor="max_total_tokens" className="text-[11px] font-semibold text-muted-foreground uppercase tracking-tight">
              {t('retrievePanel.querySettings.maxTotalTokens')}
            </label>
            <ResetButton onClick={() => handleReset('max_total_tokens')} title="Reset to default" />
          </div>
          <Input
            id="max_total_tokens"
            type="number"
            value={querySettings.max_total_tokens ?? ''}
            onChange={(e) => {
              const value = e.target.value
              handleChange('max_total_tokens', value === '' ? '' : parseInt(value) || 0)
            }}
            className="h-9 bg-background/50 border-input/50"
          />
        </div>

        {/* Checkbox Group */}
        <div className="pt-2 grid grid-cols-1 gap-3 border-t border-dashed">
          <div className="flex items-center justify-between group cursor-pointer" onClick={() => handleChange('enable_rerank', !querySettings.enable_rerank)}>
            <label className="text-[11px] font-medium text-foreground/80 cursor-pointer">{t('retrievePanel.querySettings.enableRerank')}</label>
            <Checkbox checked={querySettings.enable_rerank} onCheckedChange={(c) => handleChange('enable_rerank', c)} />
          </div>
          <div className="flex items-center justify-between group cursor-pointer" onClick={() => handleChange('stream', !querySettings.stream)}>
            <label className="text-[11px] font-medium text-foreground/80 cursor-pointer">{t('retrievePanel.querySettings.streamResponse')}</label>
            <Checkbox checked={querySettings.stream} onCheckedChange={(c) => handleChange('stream', c)} />
          </div>
          <div className="flex items-center justify-between group cursor-pointer" onClick={() => {
            const newVal = !querySettings.only_need_context;
            handleChange('only_need_context', newVal);
            if (newVal) handleChange('only_need_prompt', false);
          }}>
            <label className="text-[11px] font-medium text-foreground/80 cursor-pointer">{t('retrievePanel.querySettings.onlyNeedContext')}</label>
            <Checkbox checked={querySettings.only_need_context} onCheckedChange={(c) => {
              handleChange('only_need_context', c);
              if (c) handleChange('only_need_prompt', false);
            }} />
          </div>
        </div>
      </div>

      {/* History Section in Drawer style */}
      <div className="mt-auto border-t bg-muted/20 p-4">
        <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-2 block">
          Custom System Prompt History
        </label>
        <UserPromptInputWithHistory
          value={querySettings.user_prompt || ''}
          onChange={(v) => handleChange('user_prompt', v)}
          onSelectFromHistory={handleSelectFromHistory}
          onDeleteFromHistory={handleDeleteFromHistory}
          history={userPromptHistory}
          placeholder="Set custom system instructions..."
          className="text-xs h-20 resize-none"
        />
      </div>
    </div>
  )
}
