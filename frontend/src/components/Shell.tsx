import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'
import { BookOpen, ClipboardList, Inbox, ListChecks, MessagesSquare, MessageSquare, UserRound } from 'lucide-react'
import { useI18n } from '../i18n'
import { money } from '../lib/time'
import type { StringKey } from '../i18n/en'
import { useApprovals, useBudget } from '../lib/queries'
import { useRequiredSession, useSession } from '../lib/session'
import { Sheet } from './Sheet'
import { LangToggle, LanguageSwitch, ThemeSwitch } from './Switches'

type Tab = { to: string; label: StringKey; icon: typeof MessageSquare; badge?: boolean }

const EMPLOYEE_TABS: Tab[] = [
  { to: '/chat', label: 'nav.chat', icon: MessageSquare },
  { to: '/requests', label: 'nav.requests', icon: ClipboardList },
  { to: '/knowledge', label: 'nav.knowledge', icon: BookOpen },
]
const SUPPORT_TABS: Tab[] = [
  { to: '/queue', label: 'nav.queue', icon: Inbox, badge: true },
  { to: '/chats', label: 'nav.chats', icon: MessagesSquare },
  { to: '/knowledge', label: 'nav.knowledge', icon: BookOpen },
]

export function PreferencesSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const session = useRequiredSession()
  const { signOut } = useSession()
  const navigate = useNavigate()
  const budget = useBudget(session.tenantId, open)
  const left = budget.data?.session
  const cap = budget.data?.session_cap

  return (
    <Sheet open={open} onClose={onClose} title={t('settings.title')}>
      <div className="space-y-5">
        <div>
          <p className="muted small">{t('settings.signedInAs')}</p>
          <p className="font-semibold">{session.personName}</p>
          <p className="small text-ink-2">
            {t(session.role === 'support' ? 'role.support' : 'role.employee')} · {session.tenantName}
          </p>
          <button type="button" className="btn btn-sm mt-3" onClick={() => {
              onClose()
              signOut()
              navigate('/')
            }}>
            {t('settings.switchPerson')}
          </button>
        </div>

        <LanguageSwitch />
        <ThemeSwitch />

        <div>
          <p className="label">{t('budget.title')}</p>
          {budget.data && left != null && cap != null ? (
            <>
              <p className="small num">{t('budget.left', { left: money(left), cap: money(cap) })}</p>
              <span className="bar mt-2" style={{ width: '100%', '--s': Number(left) / Number(cap) } as React.CSSProperties}>
                <i />
              </span>
            </>
          ) : (
            budget.isSuccess && <p className="small">{t('budget.off')}</p>
          )}
          <p className="muted small mt-2">{t('budget.why')}</p>
        </div>

        <p className="notice">{t('settings.demo')}</p>
      </div>
    </Sheet>
  )
}

export function Shell() {
  const { t } = useI18n()
  const session = useRequiredSession()
  const [prefs, setPrefs] = useState(false)
  const tabs = session.role === 'support' ? SUPPORT_TABS : EMPLOYEE_TABS

  const pending = useApprovals(session.tenantId, { status: 'pending' })
  const waiting = session.role === 'support' ? (pending.data?.length ?? 0) : 0

  const links = (
    <>
      {tabs.map(({ to, label, icon: Icon, badge }) => (
        <NavLink key={to} to={to}>
          <Icon size={20} aria-hidden />
          <span>{t(label)}</span>
          {badge && waiting > 0 && (
            <span className="tab-badge num" aria-label={`${waiting} ${t('stamp.awaiting')}`}>
              {waiting}
            </span>
          )}
        </NavLink>
      ))}
    </>
  )

  return (
    <>
      <a className="skip-link" href="#content">{t('app.skip')}</a>
      <header className="topbar">
        <NavLink to={tabs[0].to} className="wordmark" aria-label={t('app.name')}>
          <ListChecks size={22} aria-hidden />
          {t('app.name')}
        </NavLink>
        <nav className="topnav" aria-label={t('nav.main')}>{links}</nav>
        <span className="spacer" />
        <LangToggle />
        <button
          type="button"
          className="btn btn-sm"
          aria-label={`${t('settings.open')}: ${session.personName}`}
          onClick={() => setPrefs(true)}
        >
          <UserRound size={18} aria-hidden />
          <span className="max-w-[9rem] truncate">{session.personName.split(' ')[0]}</span>
        </button>
      </header>
      <main id="content" tabIndex={-1} className="outline-none">
        <Outlet />
      </main>
      <nav className="tabbar" aria-label={t('nav.main')}>{links}</nav>
      <PreferencesSheet open={prefs} onClose={() => setPrefs(false)} />
    </>
  )
}
