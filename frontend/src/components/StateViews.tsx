import { AlertTriangle } from 'lucide-react'
import { useI18n } from '../i18n'
import { errorText } from '../lib/errors'

export function Loading({ rows = 4 }: { rows?: number }) {
  const { t } = useI18n()
  return (
    <div role="status" aria-label={t('common.loading')} className="space-y-3 py-4">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${92 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  )
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n()
  return (
    <div className="notice error-box" role="alert">
      <AlertTriangle size={18} aria-hidden className="mt-0.5 shrink-0" style={{ color: 'var(--red)' }} />
      <div className="flex-1">
        <p>{errorText(error, t)}</p>
        {onRetry && (
          <button type="button" className="btn btn-sm mt-2" onClick={onRetry}>
            {t('common.retry')}
          </button>
        )}
      </div>
    </div>
  )
}

export function Empty({ children }: { children: string }) {
  return <p className="muted py-6">{children}</p>
}
