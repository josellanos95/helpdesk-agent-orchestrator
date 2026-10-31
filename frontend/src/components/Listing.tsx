import { useEffect, useRef, type CSSProperties } from 'react'
import { ChevronRight, RotateCcw, X } from 'lucide-react'
import { useI18n } from '../i18n'
import type { Line } from '../lib/lines'
import { clock, duration, money, tokens as formatTokens } from '../lib/time'
import { RichText } from './RichText'
import { Stamp } from './Stamp'

export type Live = {
  /** performance.now() when the work began, from the sender's own clock. */
  elapsedMs: number
  hint: string
  tokens: number
  /** Share of the bar (0..1) used while a step is running; the scale is a 30 s reference turn. */
  progress: number
}

export type Pending = {
  text: string
  state: 'sending' | 'waiting' | 'not_sent'
  note?: string
  onResend: () => void
  onDismiss: () => void
}

type Props = {
  lines: Line[]
  label: string
  selectedKey?: string | null
  onSelect?: (line: Line) => void
  onRetryText?: (text: string) => void
  live?: Live | null
  pending?: Pending | null
  userLabel: string
}

function Meta({ line, inspectable }: { line: Line; inspectable: boolean }) {
  const cue = inspectable ? <ChevronRight className="lcue" size={16} aria-hidden /> : null
  if (line.kind === 'total') {
    return (
      <span className="lm">
        <span className="mono lm-text num">
          {duration(line.durationMs ?? 0)} · {formatTokens(line.tokens ?? 0)} tok · {money(line.cost ?? 0)}
        </span>
        {cue}
      </span>
    )
  }
  if (line.durationMs === undefined) return <span className="lm">{cue}</span>
  const scale = Math.max(1, line.scaleMs ?? line.durationMs)
  const share = Math.max(0.03, Math.min(1, line.durationMs / scale))
  return (
    <span className="lm">
      <span className="bar" aria-hidden style={{ '--s': share } as CSSProperties}>
        <i />
      </span>
      <span className="mono lm-text num">
        {duration(line.durationMs)}
        {line.tokens ? ` · ${formatTokens(line.tokens)} tok` : ''}
      </span>
      {cue}
    </span>
  )
}

function Content({ line }: { line: Line }) {
  return (
    <span className="lc">
      {line.kind === 'agent' ? (
        <RichText text={line.content} />
      ) : (
        <span className="lc-text">{line.content}</span>
      )}
      {line.stamp && <Stamp kind={line.stamp} className="lstamp" />}
      {line.detail && <span className="lc-sub block">{line.detail}</span>}
    </span>
  )
}

export function Listing({
  lines,
  label,
  selectedKey,
  onSelect,
  onRetryText,
  live,
  pending,
  userLabel,
}: Props) {
  const { t } = useI18n()
  const seen = useRef<Set<string> | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const fresh = new Set<string>()
  if (seen.current) for (const line of lines) if (!seen.current.has(line.key)) fresh.add(line.key)

  useEffect(() => {
    seen.current = new Set(lines.map((l) => l.key))
  })

  // Follow the print head, but only for someone who is already at the bottom: never yank a reader upward.
  const count = lines.length + (live ? 1 : 0) + (pending ? 1 : 0)
  const printedNow = fresh.size > 0
  useEffect(() => {
    const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 280
    if (nearBottom || printedNow) {
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      endRef.current?.scrollIntoView({ block: 'end', behavior: calm ? 'auto' : 'smooth' })
    }
  }, [count, printedNow])

  return (
    <>
      <ol className="listing" role="log" aria-label={label}>
        <li className="lhead" aria-hidden>
          <span className="lrow">
            <span className="lt">{t('col.time')}</span>
            <span className="la">{t('col.actor')}</span>
            <span className="lc">{t('col.entry')}</span>
            <span className="lm">{t('col.cost')}</span>
          </span>
        </li>
        {lines.map((line) => {
          const struck = line.struck ? 'struck' : ''
          const inspectable = Boolean(onSelect && (line.step || line.run))
          const cls = `lrow lrow-${line.kind} ${struck} ${fresh.has(line.key) ? 'lrow-enter' : ''}`
          const inner = (
            <>
              <time className="lt mono" dateTime={`${line.time}Z`}>
                {clock(line.time)}
              </time>
              <span className={`la mono ${line.kind === 'user' || line.kind === 'sign' ? 'la-user' : ''}`} title={line.actor}>
                {line.actor}
              </span>
              <Content line={line} />
              <Meta line={line} inspectable={inspectable} />
            </>
          )
          return (
            <li key={line.key}>
              {inspectable ? (
                <button
                  type="button"
                  className={cls}
                  aria-pressed={selectedKey === line.key}
                  aria-label={`${t('line.inspect')}: ${line.actor}`}
                  onClick={() => onSelect?.(line)}
                >
                  {inner}
                </button>
              ) : (
                <div className={cls}>{inner}</div>
              )}
              {line.retryText && onRetryText && (
                <div className="lactions">
                  <button type="button" className="btn btn-sm" onClick={() => onRetryText(line.retryText!)}>
                    <RotateCcw size={16} aria-hidden /> {t('out.retry')}
                  </button>
                </div>
              )}
            </li>
          )
        })}

        {pending && (
          <li>
            <div className="lrow lrow-user lrow-enter">
              <time className="lt mono">{clock(new Date().toISOString().slice(0, -1))}</time>
              <span className="la mono la-user">{userLabel}</span>
              <span className="lc">
                <span className="lc-text">{pending.text}</span>
                {pending.state === 'not_sent' && <Stamp kind="notSent" className="lstamp" />}
                {pending.note && <span className="lc-sub block">{pending.note}</span>}
              </span>
              <span className="lm" />
            </div>
            {pending.state === 'not_sent' && (
              <div className="lactions flex flex-wrap gap-2">
                <button type="button" className="btn btn-sm btn-primary" onClick={pending.onResend}>
                  <RotateCcw size={16} aria-hidden /> {t('out.retry')}
                </button>
                <button type="button" className="btn btn-sm" onClick={pending.onDismiss}>
                  <X size={16} aria-hidden /> {t('out.dismiss')}
                </button>
              </div>
            )}
          </li>
        )}

        {live && (
          <li aria-live="off">
            <div className="lrow lrow-agent lrow-live lrow-enter">
              <span className="lt mono">{duration(live.elapsedMs)}</span>
              <span className="la mono">{t('line.agent')}</span>
              <span className="lc">
                <span className="lc-text">
                  {t('live.working')}
                  <span className="cursor" aria-hidden />
                </span>
                <span className="lc-sub block">{live.hint}</span>
              </span>
              <span className="lm">
                <span className="bar bar-live" aria-hidden style={{ '--s': live.progress } as CSSProperties}>
                  <i />
                </span>
                <span className="mono lm-text num">
                  {live.tokens > 0 ? t('live.tokens', { n: formatTokens(live.tokens) }) : t('live.costPending')}
                </span>
              </span>
            </div>
          </li>
        )}
      </ol>
      <div ref={endRef} className="listing-end" aria-hidden />
    </>
  )
}
