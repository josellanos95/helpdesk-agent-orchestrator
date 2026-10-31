import { Link } from 'react-router'
import { Empty, ErrorBox, Loading } from '../components/StateViews'
import { Stamp, StatusTag } from '../components/Stamp'
import { useI18n } from '../i18n'
import type { StringKey } from '../i18n/en'
import { useApprovals, useEmployees, useTickets } from '../lib/queries'
import { useRequiredSession } from '../lib/session'
import { humanizeTool } from '../lib/lines'
import { ago, shortDate } from '../lib/time'
import type { ApprovalStatus } from '../lib/types'

const STAMP: Record<ApprovalStatus, 'awaiting' | 'approved' | 'rejected' | 'void'> = {
  pending: 'awaiting',
  approved: 'approved',
  rejected: 'rejected',
  expired: 'void',
}

export function RequestsPage() {
  const { t, locale } = useI18n()
  const { tenantId, personId } = useRequiredSession()
  const approvals = useApprovals(tenantId, { status: 'all', requestedBy: personId })
  const tickets = useTickets(tenantId, personId)
  const people = useEmployees(tenantId)
  const names = Object.fromEntries((people.data ?? []).map((p) => [p.id, p.full_name]))

  const sorted = [...(approvals.data ?? [])].reverse()
  return (
    <div className="page">
      <h1 className="page-title">{t('req.title')}</h1>

      <h2 className="section-title">{t('req.approvals')}</h2>
      {approvals.isPending && <Loading rows={3} />}
      {approvals.isError && <ErrorBox error={approvals.error} onRetry={() => approvals.refetch()} />}
      {approvals.isSuccess && sorted.length === 0 && <Empty>{t('req.noApprovals')}</Empty>}
      {sorted.length > 0 && (
        <ul className="ruled banded">
          {sorted.map((a) => {
            const struck = a.status === 'rejected' || a.status === 'expired'
            return (
              <li key={a.id}>
                <Link to={`/chat/${a.conversation_id}`} className="item" aria-label={`${t('req.openChat')}: ${humanizeTool(a.tool_name)}`}>
                  <span className="item-head">
                    <span className={`item-title ${struck ? 'line-through decoration-red' : ''}`}>
                      {humanizeTool(a.tool_name)}
                    </span>
                    <Stamp kind={STAMP[a.status]} />
                    <span className="item-meta num">{ago(a.created_at, locale)}</span>
                  </span>
                  <span className="item-sub block">
                    {Object.values(a.arguments).filter((v) => typeof v === 'string').join(' · ')}
                  </span>
                  {a.decided_by && (
                    <span className="item-meta block mt-1">
                      {t('req.decidedBy', { name: names[a.decided_by] ?? t('line.support') })}
                      {a.decision_note ? ` · “${a.decision_note}”` : ''}
                    </span>
                  )}
                  {a.status === 'pending' && (
                    <span className="item-meta block mt-1">
                      {t('req.expires', { when: shortDate(a.expires_at, locale) })}
                    </span>
                  )}
                </Link>
              </li>
            )
          })}
        </ul>
      )}

      <h2 className="section-title">{t('req.tickets')}</h2>
      {tickets.isPending && <Loading rows={3} />}
      {tickets.isError && <ErrorBox error={tickets.error} onRetry={() => tickets.refetch()} />}
      {tickets.isSuccess && tickets.data.length === 0 && <Empty>{t('req.noTickets')}</Empty>}
      {tickets.data && tickets.data.length > 0 && (
        <ul className="ruled banded">
          {tickets.data.map((ticket) => {
            const body = (
              <>
                <span className="item-head">
                  <span className="item-title">{ticket.subject}</span>
                  <StatusTag label={t(`status.${ticket.status}` as StringKey)} />
                </span>
                <span className="item-sub block">
                  {ticket.category.replace(/_/g, ' ')} · {t('req.priority', { level: ticket.priority })} ·{' '}
                  <span className="num">{ago(ticket.created_at, locale)}</span>
                </span>
              </>
            )
            return (
              <li key={ticket.id}>
                {ticket.conversation_id ? (
                  <Link to={`/chat/${ticket.conversation_id}`} className="item">{body}</Link>
                ) : (
                  <div className="item">{body}</div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
