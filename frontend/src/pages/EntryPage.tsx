import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ChevronDown, ChevronRight, ListChecks, ShieldAlert } from 'lucide-react'
import { ErrorBox, Loading } from '../components/StateViews'
import { LangToggle, LanguageSwitch, ThemeSwitch } from '../components/Switches'
import { useI18n } from '../i18n'
import { useArticles, useEmployees, useTenants } from '../lib/queries'
import { useSession } from '../lib/session'
import type { Role, Tenant } from '../lib/types'

function Company({
  tenant,
  open,
  onToggle,
  onEnter,
}: {
  tenant: Tenant
  open: boolean
  onToggle: () => void
  onEnter: (role: Role, personId: string, personName: string) => void
}) {
  const { t } = useI18n()
  const employees = useEmployees(tenant.id)
  const articles = useArticles(tenant.id)
  const [role, setRole] = useState<Role>('employee')
  const people = (employees.data ?? []).filter((p) => p.is_support_agent === (role === 'support'))
  const panel = `people-${tenant.id}`

  return (
    <li>
      <button
        type="button"
        className="company"
        aria-expanded={open}
        aria-controls={panel}
        aria-label={t('entry.pick', { company: tenant.name })}
        onClick={onToggle}
      >
        <span>
          <span className="company-name block">{tenant.name}</span>
          <span className="item-meta num">
            {employees.data ? t('common.people', { n: employees.data.length }) : '…'}
            {' · '}
            {articles.data ? t('common.articles', { n: articles.data.length }) : '…'}
          </span>
        </span>
        {open ? <ChevronDown size={20} aria-hidden /> : <ChevronRight size={20} aria-hidden />}
      </button>

      {open && (
        <div className="people" id={panel}>
          <p className="label" id={`${panel}-as`}>{t('entry.enterAs')}</p>
          <div className="seg" role="radiogroup" aria-labelledby={`${panel}-as`}>
            <button type="button" role="radio" aria-checked={role === 'employee'} onClick={() => setRole('employee')}>
              {t('entry.employee')}
            </button>
            <button type="button" role="radio" aria-checked={role === 'support'} onClick={() => setRole('support')}>
              {t('entry.support')}
            </button>
          </div>
          <p className="item-meta mt-2">{t(role === 'support' ? 'entry.supportHint' : 'entry.employeeHint')}</p>

          {employees.isPending && <Loading rows={2} />}
          {employees.isError && <ErrorBox error={employees.error} onRetry={() => employees.refetch()} />}
          {employees.isSuccess && people.length === 0 && <p className="muted small mt-3">{t('entry.noPeople')}</p>}
          {people.map((person) => (
            <button
              key={person.id}
              type="button"
              className="person"
              onClick={() => onEnter(role, person.id, person.full_name)}
            >
              <span>
                <span className="item-title block">{person.full_name}</span>
                <span className="item-meta">{person.job_title}</span>
              </span>
              <ChevronRight size={18} aria-hidden />
            </button>
          ))}
        </div>
      )}
    </li>
  )
}

export function EntryPage() {
  const { t } = useI18n()
  const { session, signIn } = useSession()
  const navigate = useNavigate()
  const tenants = useTenants()
  const [open, setOpen] = useState<string | null>(null)

  const enter = (tenant: Tenant) => (role: Role, personId: string, personName: string) => {
    signIn({ tenantId: tenant.id, tenantName: tenant.name, personId, personName, role })
    navigate(role === 'support' ? '/queue' : '/chat')
  }

  return (
    <div className="page entry">
      <div className="mb-8 flex items-center justify-between">
        <p className="wordmark">
          <ListChecks size={22} aria-hidden />
          {t('app.name')}
        </p>
        <LangToggle />
      </div>
      <h1>{t('entry.title')}</h1>
      <p className="page-lead">{t('entry.lead')}</p>

      <p className="notice mt-5">
        <ShieldAlert size={18} aria-hidden className="mt-0.5 shrink-0" />
        <span>{t('entry.demo')}</span>
      </p>

      {session && (
        <button
          type="button"
          className="btn btn-primary btn-stack mt-6"
          onClick={() => navigate(session.role === 'support' ? '/queue' : '/chat')}
        >
          <span>{t('entry.continue', { name: session.personName })}</span>
          <span className="font-normal">
            {t('entry.continueIn', { company: session.tenantName, role: t(`role.${session.role}`) })}
          </span>
        </button>
      )}

      <h2 className="section-title">{t('entry.companies')}</h2>
      {tenants.isPending && <Loading />}
      {tenants.isError && <ErrorBox error={tenants.error} onRetry={() => tenants.refetch()} />}
      {tenants.isSuccess && (
        <ul className="ruled">
          {tenants.data.map((tenant) => (
            <Company
              key={tenant.id}
              tenant={tenant}
              open={open === tenant.id}
              onToggle={() => setOpen(open === tenant.id ? null : tenant.id)}
              onEnter={enter(tenant)}
            />
          ))}
        </ul>
      )}

      <div className="mt-10 flex flex-wrap gap-x-10 gap-y-5">
        <LanguageSwitch />
        <ThemeSwitch />
      </div>
    </div>
  )
}
