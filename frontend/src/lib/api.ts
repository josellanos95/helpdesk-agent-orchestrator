export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
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
    throw new ApiError(response.status, detailOf(payload, response.statusText || 'Request failed'))
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
