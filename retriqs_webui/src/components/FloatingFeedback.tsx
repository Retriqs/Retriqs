import { MessageSquarePlusIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

export function FloatingFeedback() {
    const { t } = useTranslation()
    const navigate = useNavigate()

    return (
        <div className="fixed bottom-6 right-6 z-40 group">
            <button
                onClick={() => navigate('/feedback')}
                className="flex items-center justify-center gap-2.5 h-12 pl-4 pr-5 rounded-full shadow-2xl hover:-translate-y-1 transition-all duration-300 bg-primary hover:bg-primary/95 text-primary-foreground ring-4 ring-primary/20 hover:ring-primary/40 cursor-pointer"
                aria-label={t('header.feedback', 'Feedback')}
            >
                <MessageSquarePlusIcon className="w-5 h-5" aria-hidden="true" />
                <span className="font-bold text-[13px] tracking-wide whitespace-nowrap">
                    {t('header.feedback', 'Give Feedback')}
                </span>
            </button>
        </div>
    )
}
