import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, ListChecks, ShieldAlert } from 'lucide-react'
import { ErrorBox, Loading } from '../components/StateViews'
import { LangToggle, LanguageSwitch, ThemeSwitch } from '../components/Switches'
import { useI18n } from '../i18n'
import { request } from '../lib/api'
import { useDirectory } from '../lib/queries'
import { useSession } from '../lib/session'
import type { Company, DemoSession, Person, Role } from '../lib/types'

function CompanyRow({
  company,
  open,
  onToggle,
  onEnter,
  starting,
}: {
  company: Company
  open: boolean
  onToggle: () => void
  onEnter: (person: Person) => void
  starting: boolean
}) {
  const { t } = useI18n()
  const [role, setRole] = useState<Role>('employee')
  const people = company.people.filter((p) => p.is_support_agent === (role === 'support'))
  const panel = `people-${company.id}`

  return (
    <li>
      <button
        type="button"
        className="company"
        aria-expanded={open}
        aria-controls={panel}
        aria-label={t('entry.pick', { company: company.name })}
        onClick={onToggle}
      >
        <span>
          <span className="company-name block">{company.name}</span>
          <span className="item-meta num">
            {t('common.people', { n: company.people.length })}
            {' · '}
            {t('common.articles', { n: company.articles })}
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

          {people.length === 0 && <p className="muted small mt-3">{t('entry.noPeople')}</p>}
          {people.map((person) => (
            <button
              key={person.id}
              type="button"
              className="person"
              disabled={starting}
              onClick={() => onEnter(person)}
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
  const { session, expired, signIn } = useSession()
  const navigate = useNavigate()
  const directory = useDirectory()
  const [open, setOpen] = useState<string | null>(null)

  const start = useMutation({
    mutationFn: ({ company, person }: { company: Company; person: Person }) =>
      request<DemoSession>('/demo/session', {
        method: 'POST',
        body: { tenant_id: company.id, employee_id: person.id },
      }),
    onSuccess: (created) => {
      signIn({
        token: created.token,
        expiresAt: created.expires_at,
        tenantId: created.tenant.id,
        tenantName: created.tenant.name,
        personId: created.person.id,
        personName: created.person.full_name,
        role: created.role,
      })
      navigate(created.role === 'support' ? '/queue' : '/chat')
    },
  })

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
      {expired && (
        <p className="notice error-box mt-3" role="status">
          {t('entry.expired')}
        </p>
      )}

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
      {directory.isPending && <Loading />}
      {directory.isError && <ErrorBox error={directory.error} onRetry={() => directory.refetch()} />}
      {directory.isSuccess && (
        <ul className="ruled">
          {directory.data.map((company) => (
            <CompanyRow
              key={company.id}
              company={company}
              open={open === company.id}
              starting={start.isPending}
              onToggle={() => setOpen(open === company.id ? null : company.id)}
              onEnter={(person) => start.mutate({ company, person })}
            />
          ))}
        </ul>
      )}
      {start.isPending && (
        <p className="muted small mt-3" role="status">
          {t('entry.starting')}
        </p>
      )}
      {start.isError && (
        <div className="mt-3">
          <ErrorBox error={start.error} />
        </div>
      )}

      <div className="mt-10 flex flex-wrap gap-x-10 gap-y-5">
        <LanguageSwitch />
        <ThemeSwitch />
      </div>
    </div>
  )
}
