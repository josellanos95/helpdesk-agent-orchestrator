import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, isBusy, isTransient, request } from './api'

function reply(status: number, body?: unknown) {
  return Promise.resolve(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('request', () => {
  it('sends the tenant and the idempotency key as headers and the body as JSON', async () => {
    const fetchMock = vi.fn(() => reply(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    await request('/conversations', {
      method: 'POST',
      tenantId: 't1',
      body: { a: 1 },
      headers: { 'Idempotency-Key': 'k' },
    })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/conversations')
    expect(init.headers).toMatchObject({
      'X-Tenant-Id': 't1',
      'Idempotency-Key': 'k',
      'Content-Type': 'application/json',
    })
    expect(init.body).toBe('{"a":1}')
  })

  it('turns an error body into an ApiError carrying the server sentence', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply(409, { detail: 'The conversation is being processed.' })))
    const error = await request('/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, detail: 'The conversation is being processed.' })
    expect(isBusy(error)).toBe(true)
  })

  it('joins FastAPI validation messages', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply(422, { detail: [{ msg: 'too short' }, { msg: 'required' }] })))
    await expect(request('/x')).rejects.toMatchObject({ detail: 'too short; required' })
  })

  it('returns undefined for 204 and survives a non-JSON error page', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))))
    expect(await request('/x', { method: 'DELETE' })).toBeUndefined()
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }))),
    )
    await expect(request('/x')).rejects.toMatchObject({ status: 502, detail: 'Bad Gateway' })
  })

  it('treats a dead network and 5xx as worth retrying, a 4xx as not', () => {
    expect(isTransient(new TypeError('Failed to fetch'))).toBe(true)
    expect(isTransient(new ApiError(503, 'x'))).toBe(true)
    expect(isTransient(new ApiError(422, 'x'))).toBe(false)
  })
})
