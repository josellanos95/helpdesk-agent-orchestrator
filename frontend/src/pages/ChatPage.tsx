import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { History, SquarePen } from 'lucide-react'
import { Composer } from '../components/Composer'
import { ConversationList } from '../components/ConversationList'
import { Listing, type Live, type Pending } from '../components/Listing'
import { RunInspector } from '../components/RunInspector'
import { Sheet } from '../components/Sheet'
import { ErrorBox, Loading } from '../components/StateViews'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { useNow } from '../hooks/useNow'
import { useSend } from '../hooks/useSend'
import { useI18n } from '../i18n'
import type { StringKey } from '../i18n/en'
import { ApiError, request } from '../lib/api'
import { limitText } from '../lib/errors'
import { buildLines, tokensSoFar, truncate, type Line } from '../lib/lines'
import {
  tenantKey,
  useApprovals,
  useConversations,
  useEmployees,
  useMessages,
  useRuns,
} from '../lib/queries'
import { useRequiredSession } from '../lib/session'
import { parseServerTime } from '../lib/time'

const SUGGESTIONS: StringKey[] = ['sug.vpn', 'sug.password', 'sug.access', 'sug.email']
const REFERENCE_TURN_MS = 30_000

/**
 * The listing of one conversation. `review` is the support agent's read-only view of an employee's chat;
 * otherwise it is the signed-in employee's own conversation with the composer docked at the bottom.
 */
export function ChatPage({ review }: { review: boolean }) {
  const { id } = useParams()
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const session = useRequiredSession()
  const { tenantId, personId } = session
  const base = review ? '/chats' : '/chat'

  const { outbox, send, retry, dismiss } = useSend(tenantId)
  const mine = outbox && outbox.conversationId === id ? outbox : null
  const sending = mine !== null && mine.state !== 'not_sent'

  const conversations = useConversations(tenantId, review ? undefined : personId)
  const employees = useEmployees(tenantId)
  const messages = useMessages(tenantId, id, sending)
  const runs = useRuns(tenantId, id, sending)
  const approvals = useApprovals(tenantId, { conversationId: id, status: 'all' }, sending)

  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [history, setHistory] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)
  const wide = useMediaQuery('(min-width: 1360px)')

  const people = useMemo(
    () => Object.fromEntries((employees.data ?? []).map((e) => [e.id, e.full_name])),
    [employees.data],
  )
  const active = conversations.data?.find((c) => c.id === id)
  const userLabel = review ? (active?.employee_name.split(' ')[0] ?? t('line.you')) : t('line.you')

  const lines = useMemo(
    () =>
      buildLines({
        messages: messages.data ?? [],
        runs: runs.data ?? [],
        approvals: approvals.data ?? [],
        people,
        userLabel,
        t,
      }),
    [messages.data, runs.data, approvals.data, people, userLabel, t],
  )

  const running = runs.data?.findLast((run) => run.status === 'running')
  const showLive = sending || Boolean(running)
  const now = useNow(showLive)
  const live: Live | null = showLive
    ? (() => {
        const steps = running?.steps ?? []
        const last = steps.at(-1)
        const elapsedMs = mine && mine.state !== 'not_sent'
          ? now - mine.startedAt
          : running
            ? Math.max(0, Date.now() - parseServerTime(running.started_at).getTime())
            : 0
        const hint =
          mine?.state === 'waiting'
            ? t('live.waiting', { n: mine.attempt })
            : !last
              ? t('live.start')
              : t(last.kind === 'llm' ? 'live.afterModel' : 'live.afterTool')
        return {
          elapsedMs,
          hint,
          tokens: tokensSoFar(running),
          progress: Math.min(0.97, elapsedMs / REFERENCE_TURN_MS),
        }
      })()
    : null

  const maxSeq = Math.max(0, ...(messages.data ?? []).map((m) => m.seq))
  const echoed = mine ? (messages.data ?? []).some((m) => m.role === 'user' && m.seq > mine.baseSeq) : false
  const pending: Pending | null =
    mine && !echoed
      ? {
          text: mine.text,
          state: mine.state,
          note:
            mine.state === 'not_sent'
              ? mine.error === 'network'
                ? t('out.network')
                : (limitText(new ApiError(429, '', mine.code), t) ?? mine.detail ?? t('out.rejected'))
              : undefined,
          onResend: retry,
          onDismiss: dismiss,
        }
      : null

  const handleSend = async (text: string) => {
    setCreateError(null)
    let conversationId = id
    if (!conversationId) {
      try {
        const created = await request<{ id: string }>('/conversations', {
          method: 'POST',
          tenantId,
          body: { employee_id: personId },
        })
        conversationId = created.id
        void queryClient.invalidateQueries({ queryKey: tenantKey(tenantId) })
        navigate(`${base}/${conversationId}`, { replace: true })
      } catch (error) {
        setCreateError(error)
        return
      }
    }
    void send(conversationId, text, maxSeq)
  }

  const selected: Line | null = lines.find((l) => l.key === selectedKey) ?? null
  const latestRun = runs.data?.at(-1)
  const inspector = <RunInspector line={selected} latest={latestRun} />

  const firstAsked = lines.find((l) => l.kind === 'user')?.content
  const title = review
    ? (active?.employee_name ?? t('chats.title'))
    : firstAsked
      ? truncate(firstAsked, 70)
      : t('chat.untitled')
  const empty = !id || (messages.isSuccess && lines.length === 0 && !pending)
  const list = (onNavigate?: () => void) => (
    <ConversationList
      items={conversations.data ?? []}
      activeId={id}
      basePath={base}
      showOwner={review}
      onNavigate={onNavigate}
    />
  )

  return (
    <div className="chat-grid with-inspector">
      <aside className="convlist" aria-label={t(review ? 'chats.title' : 'chat.history')}>
        {conversations.isError ? <ErrorBox error={conversations.error} /> : list()}
      </aside>

      <section className="chat-main" aria-label={t('chat.listing')}>
        <div className="chat-head">
          <h1>{title}</h1>
          <button
            type="button"
            className="btn btn-sm only-narrow"
            aria-label={t(review ? 'chats.title' : 'chat.history')}
            onClick={() => setHistory(true)}
          >
            <History size={18} aria-hidden />
            <span className="hide-narrow">{t(review ? 'chats.title' : 'chat.history')}</span>
          </button>
          {!review && (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                dismiss()
                setSelectedKey(null)
                navigate('/chat')
              }}
            >
              <SquarePen size={18} aria-hidden /> {t('chat.new')}
            </button>
          )}
        </div>

        <div className="chat-body">
          {id && messages.isPending && <div className="px-4"><Loading /></div>}
          {id && messages.isError && (
            <div className="p-4">
              <ErrorBox error={messages.error} onRetry={() => messages.refetch()} />
            </div>
          )}
          {createError !== null && (
            <div className="p-4">
              <ErrorBox error={createError} />
            </div>
          )}

          {review && !id && (
            <div>
              <p className="muted p-4 only-wide">{t('chats.select')}</p>
              <div className="only-narrow">{list()}</div>
            </div>
          )}

          {empty && !review && (
            <div className="px-4 pt-8 pb-2 max-w-2xl">
              <h2 className="text-[1.375rem] font-bold tracking-tight">{t('chat.emptyTitle')}</h2>
              <p className="page-lead">{t('chat.emptyHint')}</p>
              <p className="label mt-6">{t('chat.try')}</p>
              <ul className="ruled suggest-list" style={{ marginTop: '0.25rem' }}>
                {SUGGESTIONS.map((key) => (
                  <li key={key}>
                    <button type="button" className="item" disabled={sending} onClick={() => handleSend(t(key))}>
                      {t(key)}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {id && (messages.isSuccess || pending) && (!empty || pending || live) && (
            <Listing
              key={id}
              lines={lines}
              label={t('chat.listing')}
              selectedKey={selectedKey}
              onSelect={(line) => setSelectedKey(line.key === selectedKey ? null : line.key)}
              onRetryText={review ? undefined : (text) => handleSend(text)}
              live={live}
              pending={pending}
              userLabel={userLabel}
            />
          )}
        </div>

        {review ? (
          id && active && (
            <p className="notice" style={{ margin: '1rem' }}>{t('chat.readOnly', { name: active.employee_name })}</p>
          )
        ) : (
          <Composer busy={sending} onSend={handleSend} />
        )}
      </section>

      <aside className="inspector" aria-label={t('insp.title')}>
        <h2 className="sr-only">{t('insp.title')}</h2>
        {inspector}
      </aside>

      <Sheet open={history} onClose={() => setHistory(false)} title={t(review ? 'chats.title' : 'chat.history')}>
        <div className="-m-4">{list(() => setHistory(false))}</div>
      </Sheet>
      <Sheet
        open={!wide && selected !== null}
        onClose={() => setSelectedKey(null)}
        title={t('insp.title')}
      >
        {inspector}
      </Sheet>
    </div>
  )
}
