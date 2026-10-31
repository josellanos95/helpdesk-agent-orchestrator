import { useState } from 'react'
import { Link } from 'react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, MessageSquareText, NotebookPen, X } from 'lucide-react'
import { Empty, ErrorBox, Loading } from '../components/StateViews'
import { Stamp, StatusTag } from '../components/Stamp'
import { useI18n } from '../i18n'
import type { StringKey } from '../i18n/en'
import { ApiError, request } from '../lib/api'
import { tenantKey, useApprovals, useEmployees, useEscalations } from '../lib/queries'
import { useRequiredSession } from '../lib/session'
import { humanizeTool } from '../lib/lines'
import { ago, shortDate } from '../lib/time'
import type { Approval, ApprovalStatus, Escalation } from '../lib/types'

const STAMP: Record<ApprovalStatus, 'awaiting' | 'approved' | 'rejected' | 'void'> = {
  pending: 'awaiting',
  approved: 'approved',
  rejected: 'rejected',
  expired: 'void',
}

function PendingApproval({ approval }: { approval: Approval }) {
  const { t, locale } = useI18n()
  const { tenantId, personId } = useRequiredSession()
  const queryClient = useQueryClient()
  const [noting, setNoting] = useState(false)
  const [note, setNote] = useState('')
  const own = approval.requested_by === personId

  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject') =>
      request(`/approvals/${approval.id}/decision`, {
        method: 'POST',
        tenantId,
        body: { decision, approver_id: personId, note: note.trim() || null },
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: tenantKey(tenantId) }),
  })
  const conflict = decide.error instanceof ApiError && decide.error.status === 409

  const args = Object.entries(approval.arguments)
  const panel = `decide-${approval.id}`
  return (
    <li>
      <div className="item">
        <div className="item-head">
          <span className="item-title">{humanizeTool(approval.tool_name)}</span>
          <Stamp kind="awaiting" />
          <span className="item-meta num">{ago(approval.created_at, locale)}</span>
        </div>
        <p className="item-sub">{t('queue.askedBy', { name: approval.requested_by_name })}</p>
        <dl className="mt-2 space-y-0.5 text-[0.9375rem]">
          {args.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="text-ink-3 shrink-0">{key.replace(/_/g, ' ')}</dt>
              <dd className="m-0">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
            </div>
          ))}
        </dl>
        <p className="item-meta mt-1">{t('queue.expires', { when: shortDate(approval.expires_at, locale) })}</p>

        {own ? (
          <p className="notice mt-3">{t('queue.cantSignOwn')}</p>
        ) : (
          <div className="mt-3 max-w-lg">
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn btn-primary"
                disabled={decide.isPending}
                onClick={() => decide.mutate('approve')}
              >
                <Check size={18} aria-hidden /> {decide.isPending ? t('queue.sending') : t('queue.approve')}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={decide.isPending}
                onClick={() => decide.mutate('reject')}
              >
                <X size={18} aria-hidden /> {t('queue.reject')}
              </button>
            </div>
            <div className="mt-1 -ml-3 flex flex-wrap">
              <button
                type="button"
                className="btn btn-sm btn-quiet"
                aria-expanded={noting}
                aria-controls={panel}
                onClick={() => setNoting(!noting)}
              >
                <NotebookPen size={16} aria-hidden /> {t('queue.addNote')}
              </button>
              <Link to={`/chats/${approval.conversation_id}`} className="btn btn-sm btn-quiet">
                <MessageSquareText size={16} aria-hidden /> {t('queue.openChat')}
              </Link>
            </div>
            {noting && (
              <div id={panel} className="mt-3">
                <label className="label" htmlFor={`${panel}-note`}>{t('queue.note')}</label>
                <textarea
                  id={`${panel}-note`}
                  className="field"
                  rows={2}
                  maxLength={500}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>
            )}
            {decide.isError && (
              <div className="mt-3">
                <ErrorBox error={conflict ? new ApiError(409, t('queue.conflict')) : decide.error} />
              </div>
            )}
          </div>
        )}
        {own && (
          <div className="mt-1 -ml-3">
            <Link to={`/chats/${approval.conversation_id}`} className="btn btn-sm btn-quiet">
              <MessageSquareText size={16} aria-hidden /> {t('queue.openChat')}
            </Link>
          </div>
        )}
      </div>
    </li>
  )
}

function SignedApproval({ approval, signer }: { approval: Approval; signer?: string }) {
  const { t, locale } = useI18n()
  const struck = approval.status === 'rejected' || approval.status === 'expired'
  return (
    <li>
      <Link to={`/chats/${approval.conversation_id}`} className="item">
        <span className="item-head">
          <span className={`item-title ${struck ? 'line-through decoration-red' : ''}`}>
            {humanizeTool(approval.tool_name)}
          </span>
          <Stamp kind={STAMP[approval.status]} />
          <span className="item-meta num">{ago(approval.decided_at ?? approval.created_at, locale)}</span>
        </span>
        <span className="item-sub block">
          {t('queue.askedBy', { name: approval.requested_by_name })}
          {signer ? ` · ${t('req.decidedBy', { name: signer })}` : ''}
          {approval.decision_note ? ` · “${approval.decision_note}”` : ''}
        </span>
      </Link>
    </li>
  )
}

function EscalationItem({ escalation }: { escalation: Escalation }) {
  const { t, locale } = useI18n()
  const { tenantId, personId } = useRequiredSession()
  const queryClient = useQueryClient()
  const move = useMutation({
    mutationFn: (action: 'acknowledge' | 'resolve') =>
      request(`/escalations/${escalation.id}/${action}`, {
        method: 'POST',
        tenantId,
        body: { approver_id: personId },
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: tenantKey(tenantId) }),
  })
  return (
    <li>
      <div className="item">
        <div className="item-head">
          <span className="item-title">{escalation.ticket_subject}</span>
          <StatusTag label={t(`status.${escalation.status}` as StringKey)} />
          <span className="item-meta num">{ago(escalation.created_at, locale)}</span>
        </div>
        <p className="item-sub">
          {t('queue.urgency', { level: escalation.urgency })} · {escalation.reason}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {escalation.status === 'pending' && (
            <button type="button" className="btn btn-sm" disabled={move.isPending} onClick={() => move.mutate('acknowledge')}>
              {t('queue.acknowledge')}
            </button>
          )}
          <button type="button" className="btn btn-sm btn-primary" disabled={move.isPending} onClick={() => move.mutate('resolve')}>
            <Check size={16} aria-hidden /> {t('queue.resolve')}
          </button>
        </div>
        {move.isError && (
          <div className="mt-3">
            <ErrorBox error={move.error} />
          </div>
        )}
      </div>
    </li>
  )
}

export function QueuePage() {
  const { t } = useI18n()
  const { tenantId } = useRequiredSession()
  const [tab, setTab] = useState<'approvals' | 'escalations'>('approvals')
  const approvals = useApprovals(tenantId, { status: 'all' })
  const escalations = useEscalations(tenantId)
  const people = useEmployees(tenantId)
  const names = Object.fromEntries((people.data ?? []).map((p) => [p.id, p.full_name]))

  const waiting = (approvals.data ?? []).filter((a) => a.status === 'pending')
  const signed = (approvals.data ?? []).filter((a) => a.status !== 'pending').reverse()

  return (
    <div className="page">
      <h1 className="page-title">{t('queue.title')}</h1>

      <div className="seg mt-4" role="tablist" aria-label={t('queue.title')}>
        <button type="button" role="tab" id="tab-approvals" aria-selected={tab === 'approvals'} aria-controls="panel-approvals" onClick={() => setTab('approvals')}>
          {t('queue.tabApprovals')} <span className="num">({waiting.length})</span>
        </button>
        <button type="button" role="tab" id="tab-escalations" aria-selected={tab === 'escalations'} aria-controls="panel-escalations" onClick={() => setTab('escalations')}>
          {t('queue.tabEscalations')} <span className="num">({escalations.data?.length ?? 0})</span>
        </button>
      </div>

      {tab === 'approvals' && (
        <div role="tabpanel" id="panel-approvals" aria-labelledby="tab-approvals">
          {approvals.isPending && <Loading />}
          {approvals.isError && <ErrorBox error={approvals.error} onRetry={() => approvals.refetch()} />}
          {approvals.isSuccess && (
            <>
              <h2 className="section-title">{t('queue.waiting')}</h2>
              {waiting.length === 0 ? (
                <Empty>{t('queue.noWaiting')}</Empty>
              ) : (
                <ul className="ruled banded">
                  {waiting.map((a) => (
                    <PendingApproval key={a.id} approval={a} />
                  ))}
                </ul>
              )}
              <h2 className="section-title">{t('queue.signed')}</h2>
              {signed.length === 0 ? (
                <Empty>{t('queue.noSigned')}</Empty>
              ) : (
                <ul className="ruled banded">
                  {signed.map((a) => (
                    <SignedApproval key={a.id} approval={a} signer={a.decided_by ? names[a.decided_by] : undefined} />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}

      {tab === 'escalations' && (
        <div role="tabpanel" id="panel-escalations" aria-labelledby="tab-escalations">
          <h2 className="section-title">{t('queue.openEscalations')}</h2>
          {escalations.isPending && <Loading />}
          {escalations.isError && <ErrorBox error={escalations.error} onRetry={() => escalations.refetch()} />}
          {escalations.isSuccess &&
            (escalations.data.length === 0 ? (
              <Empty>{t('queue.noEscalations')}</Empty>
            ) : (
              <ul className="ruled banded">
                {escalations.data.map((e) => (
                  <EscalationItem key={e.id} escalation={e} />
                ))}
              </ul>
            ))}
        </div>
      )}
    </div>
  )
}
