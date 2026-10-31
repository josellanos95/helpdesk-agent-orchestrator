import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSend } from './useSend'

const OK = { reply: 'done', run: { run_id: 'r', status: 'completed', prompt_tokens: 1, completion_tokens: 1, cost_usd: '0.001' } }

function answer(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useSend', () => {
  it('sends with one Idempotency-Key and clears the outbox when the answer arrives', async () => {
    const fetchMock = vi.fn(() => answer(200, OK))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useSend('t1'), { wrapper })

    await act(async () => {
      await result.current.send('c1', 'hello', 0)
    })

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/conversations/c1/messages')
    expect((init.headers as Record<string, string>)['Idempotency-Key']).toBeTruthy()
    expect(result.current.outbox).toBeNull()
  })

  it('waits and retries with the SAME key while the conversation is busy (409)', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => answer(409, { detail: 'busy' }))
      .mockImplementationOnce(() => answer(200, OK))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useSend('t1'), { wrapper })

    let pending!: Promise<void>
    act(() => {
      pending = result.current.send('c1', 'hello', 0)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.outbox).toMatchObject({ state: 'waiting', attempt: 1 })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
      await pending
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const keys = fetchMock.mock.calls.map((call) => ((call as unknown as [string, RequestInit])[1].headers as Record<string, string>)['Idempotency-Key'])
    expect(keys[0]).toBe(keys[1])
    expect(result.current.outbox).toBeNull()
  })

  it('keeps the message as NOT SENT when the network drops, and resends it with the same key', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
      .mockImplementationOnce(() => answer(200, OK))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useSend('t1'), { wrapper })

    await act(async () => {
      await result.current.send('c1', 'hello', 0)
    })
    expect(result.current.outbox).toMatchObject({ state: 'not_sent', error: 'network', text: 'hello' })
    const firstKey = result.current.outbox!.key

    await act(async () => {
      result.current.retry()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.outbox).toBeNull()
    const secondInit = (fetchMock.mock.calls[1] as unknown as [string, RequestInit])[1]
    expect((secondInit.headers as Record<string, string>)['Idempotency-Key']).toBe(firstKey)
  })

  it('does not call a rejected message a network problem', async () => {
    vi.stubGlobal('fetch', vi.fn(() => answer(422, { detail: 'content too long' })))
    const { result } = renderHook(() => useSend('t1'), { wrapper })
    await act(async () => {
      await result.current.send('c1', 'x', 0)
    })
    expect(result.current.outbox).toMatchObject({ state: 'not_sent', error: 'rejected', detail: 'content too long' })
  })
})
