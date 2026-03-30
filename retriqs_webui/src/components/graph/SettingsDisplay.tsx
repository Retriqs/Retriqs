import { useSettingsStore } from '@/stores/settings'
import { useTranslation } from 'react-i18next'

/**
 * Component that displays current values of important graph settings
 * Positioned to the right of the toolbar at the bottom-left corner
 */
const SettingsDisplay = () => {
  const { t } = useTranslation()
  const graphQueryMaxDepth = useSettingsStore.use.graphQueryMaxDepth()
  const graphMaxNodes = useSettingsStore.use.graphMaxNodes()

  return (
    <div className="absolute bottom-6 left-[4.5rem] flex items-center gap-3 text-[11px] font-bold tracking-wider uppercase text-muted-foreground/60 bg-card/80 px-4 py-2 rounded-xl border border-border/40 backdrop-blur-xl shadow-lg transition-all hover:bg-card">
      <div className="flex items-center">
        <span className="opacity-70 mr-1.5">{t('graphPanel.sideBar.settings.depth')}:</span>
        <span className="text-foreground/90">{graphQueryMaxDepth}</span>
      </div>
      <div className="w-1 h-1 rounded-full bg-border" />
      <div className="flex items-center">
        <span className="opacity-70 mr-1.5">{t('graphPanel.sideBar.settings.max')}:</span>
        <span className="text-foreground/90">{graphMaxNodes}</span>
      </div>
    </div>
  )
}

export default SettingsDisplay
