import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError, isBusy, isTransient, request } from '../lib/api'
import { tenantKey } from '../lib/queries'
import type { SendResult } from '../lib/types'

export type Outbox = {
  conversationId: string
  text: string
  /** One key per user intent: resending after a lost answer must not run the agent twice. */
  key: string
  startedAt: number
  /** Highest message seq seen before sending, to know when the server's own copy of the line has arrived. */
  baseSeq: number
  state: 'sending' | 'waiting' | 'not_sent'
  attempt: number
  error?: 'network' | 'rejected'
  detail?: string
}

const MAX_BUSY_ATTEMPTS = 8

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(timer)
      resolve()
    })
  })
}

function newKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/**
 * Sends a message and keeps the outcome visible. A 409 means the conversation (or this very request) is
 * still being processed, so it waits and tries again with the same key; a lost answer becomes a NOT SENT
 * line that can be resent safely.
 */
export function useSend(tenantId: string) {
  const queryClient = useQueryClient()
  const [outbox, setOutbox] = useState<Outbox | null>(null)
  const control = useRef<AbortController | null>(null)

  useEffect(() => () => control.current?.abort(), [])

  const run = useCallback(
    async (box: Outbox) => {
      control.current?.abort()
      const controller = new AbortController()
      control.current = controller
      setOutbox({ ...box, state: 'sending', error: undefined, detail: undefined })

      for (let attempt = 1; ; attempt++) {
        try {
          await request<SendResult>(`/conversations/${box.conversationId}/messages`, {
            method: 'POST',
            tenantId,
            body: { content: box.text },
            headers: { 'Idempotency-Key': box.key },
            signal: controller.signal,
          })
          // Refresh first, then clear: the finished lines are already on screen when the live line goes.
          await queryClient.invalidateQueries({ queryKey: tenantKey(tenantId) })
          if (!controller.signal.aborted) setOutbox(null)
          return
        } catch (error) {
          if (controller.signal.aborted) return
          if (isBusy(error) && attempt <= MAX_BUSY_ATTEMPTS) {
            setOutbox((current) => (current ? { ...current, state: 'waiting', attempt } : current))
            await sleep(Math.min(1000 * attempt, 4000), controller.signal)
            continue
          }
          setOutbox({
            ...box,
            state: 'not_sent',
            error: isTransient(error) || isBusy(error) ? 'network' : 'rejected',
            detail: error instanceof ApiError ? error.detail : undefined,
          })
          await queryClient.invalidateQueries({ queryKey: tenantKey(tenantId) })
          return
        }
      }
    },
    [queryClient, tenantId],
  )

  const send = useCallback(
    (conversationId: string, text: string, baseSeq: number) =>
      run({
        conversationId,
        text,
        key: newKey(),
        startedAt: performance.now(),
        baseSeq,
        state: 'sending',
        attempt: 0,
      }),
    [run],
  )

  const retry = useCallback(() => {
    if (outbox) void run({ ...outbox, startedAt: performance.now() })
  }, [outbox, run])

  const dismiss = useCallback(() => {
    control.current?.abort()
    setOutbox(null)
  }, [])

  return { outbox, send, retry, dismiss }
}
