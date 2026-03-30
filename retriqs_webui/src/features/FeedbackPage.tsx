import { useTranslation } from 'react-i18next'
import useTheme from '@/hooks/useTheme'

export default function FeedbackPage() {
    const { t } = useTranslation()
    const { theme } = useTheme()

    // Featurebase supports a ?theme= param on their hosted portals
    // that accepts 'light', 'dark', or 'system'
    const portalUrl = `https://d3vs.featurebase.app?theme=${theme}`

    return (
        <div className="flex h-full w-full flex-col overflow-hidden bg-background">
            <div className="flex-1 relative">
                <iframe
                    src={portalUrl}
                    className="absolute inset-0 h-full w-full border-0"
                    title={t('header.feedback', 'Feedback')}
                    allow="clipboard-write"
                />
            </div>
        </div>
    )
}
