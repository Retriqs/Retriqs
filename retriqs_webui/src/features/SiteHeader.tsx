import Button from '@/components/ui/Button'
import { SiteInfo, webuiPrefix } from '@/lib/constants'
import { useAuthStore } from '@/stores/state'
import { cn } from '@/lib/utils'
import { useTranslation } from 'react-i18next'
import { navigationService } from '@/services/navigation'
import { LogOutIcon, Sun, Moon } from 'lucide-react'
import { TenantSelector } from '@/components/TenantSelector'
import useTheme from '@/hooks/useTheme'

import { NavLink } from 'react-router-dom'

interface NavigationTabProps {
  to: string
  children: React.ReactNode
}

function NavigationTab({ to, children }: NavigationTabProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => cn(
        'relative h-8 cursor-pointer px-4 text-xs font-semibold transition-all duration-300 rounded-full flex items-center justify-center overflow-hidden',
        isActive
          ? 'bg-primary text-primary-foreground shadow-lg scale-105'
          : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground hover:scale-105'
      )}
    >
      <span className="relative z-10">{children}</span>
    </NavLink>
  )
}

function TabsNavigation() {
  const { t } = useTranslation()

  return (
    <div className="flex h-full items-center justify-center">
      <div className="flex h-10 items-center gap-1 glass p-1 rounded-full shadow-inner">
        <NavigationTab to="/documents">
          {t('header.documents')}
        </NavigationTab>
        <NavigationTab to="/knowledge-graph">
          {t('header.knowledgeGraph')}
        </NavigationTab>
        <NavigationTab to="/retrieval">
          {t('header.retrieval')}
        </NavigationTab>
        <NavigationTab to="/marketplace">
          {t('header.marketplace')}
        </NavigationTab>
        <NavigationTab to="/settings">
          {t('header.settings')}
        </NavigationTab>
      </div>
    </div>
  )
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-9 w-9 rounded-full text-muted-foreground transition-all duration-300 hover:bg-muted/50 hover:text-foreground active:scale-90 shadow-sm"
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      tooltip={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
    >
      <div className="relative h-4 w-4">
        <Sun className={cn(
          "h-full w-full absolute transition-all duration-500 transform",
          theme === 'dark' ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-0 opacity-0"
        )} />
        <Moon className={cn(
          "h-full w-full absolute transition-all duration-500 transform",
          theme === 'dark' ? "rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100"
        )} />
      </div>
    </Button>
  )
}

export default function SiteHeader() {
  const { t } = useTranslation()
  const { isGuestMode, username } = useAuthStore()

  const handleLogout = () => {
    navigationService.navigateToLogin()
  }

  return (
    <header className="glass sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b px-6 shadow-sm shadow-primary/5 transition-all duration-300">
      <div className="flex items-center">
        <a href={webuiPrefix} className="flex items-center gap-3 transition-opacity hover:opacity-80">
          <img src={`${webuiPrefix}Logo.png`} className="h-6 w-6 object-contain" />
          <span className="text-sm font-bold tracking-tight text-foreground/90">{SiteInfo.name}</span>
        </a>
      </div>

      <div className="absolute left-1/2 -translate-x-1/2 h-full">
        <TabsNavigation />
      </div>

      <div className="flex items-center gap-4">
        <TenantSelector />
        <ThemeToggle />
        {!isGuestMode && (
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9 rounded-full text-muted-foreground transition-colors hover:bg-muted"
            tooltip={`${t('header.logout')} (${username})`}
            onClick={handleLogout}
          >
            <LogOutIcon className="size-4" aria-hidden="true" />
          </Button>
        )}
      </div>
    </header>
  )
}

