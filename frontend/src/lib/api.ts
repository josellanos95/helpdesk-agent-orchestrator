export class ApiError extends Error {
  status: number
  detail: string
  /** Machine-readable reason for limits (rate_limited, budget_exhausted_session, ...). */
  code?: string
  retryAfter?: number

  constructor(status: number, detail: string, code?: string, retryAfter?: number) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = code
    this.retryAfter = retryAfter
  }
}

// The signed demo session token, set by the session provider. A 401 means it is gone or expired.
let authToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

type Options = {
  tenantId?: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

function detailOf(payload: unknown, fallback: string): string {
  const detail = (payload as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg, ...}]
    const messages = detail.map((d) => (d as { msg?: string }).msg ?? '').filter(Boolean)
    return messages.join('; ') || fallback
  }
  return fallback
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = { ...options.headers }
  if (options.tenantId) headers['X-Tenant-Id'] = options.tenantId
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`/api${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })

  if (response.status === 204) return undefined as T
  const text = await response.text()
  let payload: unknown = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    // not JSON (a proxy error page, for example)
  }
  if (!response.ok) {
    const code = (payload as { detail?: { code?: unknown } } | null)?.detail?.code
    const retryAfter = Number(response.headers.get('Retry-After'))
    if (response.status === 401 && authToken) onUnauthorized?.()
    throw new ApiError(
      response.status,
      detailOf(payload, response.statusText || 'Request failed'),
      typeof code === 'string' ? code : undefined,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    )
  }
  return payload as T
}

/** True for errors worth retrying with the same Idempotency-Key: no answer at all, or a server fault. */
export function isTransient(error: unknown): boolean {
  if (error instanceof ApiError) return error.status >= 500
  return error instanceof TypeError // fetch rejects with TypeError when the network is down
}

/** 409: the conversation (or the very same request) is still being processed. Waiting fixes it. */
export function isBusy(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409
}
