import { ApiError } from './api'
import type { StringKey } from '../i18n/en'

const BY_CODE: Record<string, StringKey> = {
  rate_limited: 'limit.rate_limited',
  budget_exhausted_session: 'limit.budget_exhausted_session',
  budget_exhausted_ip: 'limit.budget_exhausted_ip',
  budget_exhausted_day: 'limit.budget_exhausted_day',
}

/** The interface's own sentence for a limit the server reported, if it is one we know. */
export function limitText(error: unknown, t: (key: StringKey) => string): string | undefined {
  const key = error instanceof ApiError && error.code ? BY_CODE[error.code] : undefined
  return key ? t(key) : undefined
}

export function errorText(error: unknown, t: (key: StringKey) => string): string {
  if (error instanceof ApiError) {
    const generic: Partial<Record<number, StringKey>> = {
      401: 'err.401',
      403: 'err.403',
      404: 'err.404',
      409: 'err.409',
      422: 'err.422',
      429: 'err.429',
      503: 'err.503',
    }
    // Limits are phrased in the UI language; otherwise the server's own sentence is usually the most
    // useful one (it names the rule that was hit).
    return limitText(error, t) ?? (error.detail || t(generic[error.status] ?? 'err.generic'))
  }
  return t('common.network')
}
