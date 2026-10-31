import { useI18n } from '../i18n'
import type { Line } from '../lib/lines'
import { duration, money, parseServerTime, shortDate, tokens as formatTokens } from '../lib/time'
import type { Run } from '../lib/types'

function pretty(value: unknown): string {
  if (value === null || value === undefined) return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function Data({ title, value }: { title: string; value: unknown }) {
  const text = pretty(value)
  if (!text) return null
  return (
    <>
      <h3 className="insp-h">{title}</h3>
      <pre className="data">{text}</pre>
    </>
  )
}

/** What really happened inside a line: the step's input, output and timings, and the run it belongs to. */
export function RunInspector({ line, latest }: { line: Line | null; latest?: Run }) {
  const { t, locale } = useI18n()
  const run = line?.run ?? latest
  const step = line?.step

  if (!run) return <p className="muted small">{t('insp.empty')}</p>

  const spent = run.finished_at
    ? parseServerTime(run.finished_at).getTime() - parseServerTime(run.started_at).getTime()
    : null
  return (
    <div>
      {step ? (
        <>
          <h2 className="font-semibold">{t('insp.step', { n: step.step_index + 1 })}</h2>
          <dl className="dl">
            <dt>{t('insp.kind')}</dt>
            <dd>{step.kind === 'llm' ? t('line.model') : step.kind}</dd>
            <dt>{step.kind === 'llm' ? t('insp.model') : 'Tool'}</dt>
            <dd className="mono">{step.name}</dd>
            <dt>{t('insp.duration')}</dt>
            <dd className="mono num">{duration(step.latency_ms)}</dd>
            {step.prompt_tokens != null && (
              <>
                <dt>{t('insp.tokens')}</dt>
                <dd className="mono num">
                  {formatTokens(step.prompt_tokens)} + {formatTokens(step.completion_tokens ?? 0)}
                </dd>
              </>
            )}
          </dl>
          {step.error && <Data title={t('insp.error')} value={step.error} />}
          <Data title={t('insp.input')} value={step.input} />
          <Data title={t('insp.output')} value={step.output} />
        </>
      ) : (
        <p className="muted small">{t('insp.empty')}</p>
      )}

      <h3 className="insp-h">{t('insp.run')}</h3>
      <dl className="dl">
        <dt>{t('insp.status')}</dt>
        <dd>{t(`run.${run.status}`)}</dd>
        <dt>{t('insp.model')}</dt>
        <dd className="mono">{run.model}</dd>
        <dt>{t('insp.started')}</dt>
        <dd>{shortDate(run.started_at, locale)}</dd>
        {spent !== null && (
          <>
            <dt>{t('insp.duration')}</dt>
            <dd className="mono num">{duration(spent)}</dd>
          </>
        )}
        <dt>{t('insp.tokens')}</dt>
        <dd className="mono num">
          {formatTokens(run.prompt_tokens)} + {formatTokens(run.completion_tokens)}
        </dd>
        <dt>{t('insp.cost')}</dt>
        <dd className="mono num">{money(run.cost_usd)}</dd>
      </dl>
      {run.error && <Data title={t('insp.error')} value={run.error} />}
    </div>
  )
}
