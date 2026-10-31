import { ApiError } from './api'
import type { StringKey } from '../i18n/en'

export function errorText(error: unknown, t: (key: StringKey) => string): string {
  if (error instanceof ApiError) {
    const generic: Partial<Record<number, StringKey>> = {
      403: 'err.403',
      404: 'err.404',
      409: 'err.409',
      422: 'err.422',
      503: 'err.503',
    }
    // The server's own sentence is usually the most useful one (it names the rule that was hit).
    return error.detail || t(generic[error.status] ?? 'err.generic')
  }
  return t('common.network')
}
