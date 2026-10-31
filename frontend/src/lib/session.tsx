import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setAuthToken, setUnauthorizedHandler } from './api'
import type { Role } from './types'
import { readStored, writeStored } from './storage'

// The session is a signed demo token plus what it says about the person (POST /api/demo/session). The server
// enforces it; the token only proves this browser chose to be this person, not who they really are.
export type Session = {
  token: string
  expiresAt: string
  tenantId: string
  tenantName: string
  personId: string
  personName: string
  role: Role
}

const KEY = 'triagent.session'

export function parseSession(raw: string | null, now = Date.now()): Session | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<Session>
    const ok =
      typeof value.token === 'string' &&
      typeof value.expiresAt === 'string' &&
      typeof value.tenantId === 'string' &&
      typeof value.tenantName === 'string' &&
      typeof value.personId === 'string' &&
      typeof value.personName === 'string' &&
      (value.role === 'employee' || value.role === 'support')
    if (!ok) return null
    return Date.parse(value.expiresAt as string) > now ? (value as Session) : null
  } catch {
    return null
  }
}

type SessionContext = {
  session: Session | null
  /** True when the server turned a request down because the session was gone: the entry screen says so. */
  expired: boolean
  signIn: (session: Session) => void
  signOut: () => void
}

const Context = createContext<SessionContext | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => {
    const stored = parseSession(readStored(KEY))
    setAuthToken(stored?.token ?? null) // before the first request of the first render
    return stored
  })
  const [expired, setExpired] = useState(false)

  const signIn = useCallback((next: Session) => {
    setAuthToken(next.token)
    setSession(next)
    setExpired(false)
    writeStored(KEY, JSON.stringify(next))
  }, [])
  const signOut = useCallback(() => {
    setAuthToken(null)
    setSession(null)
    writeStored(KEY, null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setExpired(true)
      signOut()
    })
    return () => setUnauthorizedHandler(null)
  }, [signOut])

  const value = useMemo(() => ({ session, expired, signIn, signOut }), [session, expired, signIn, signOut])
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useSession(): SessionContext {
  const value = useContext(Context)
  if (!value) throw new Error('useSession needs a SessionProvider')
  return value
}

/** For screens that only render when someone has chosen an identity. */
export function useRequiredSession(): Session {
  const { session } = useSession()
  if (!session) throw new Error('No session')
  return session
}
