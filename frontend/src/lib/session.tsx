import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Role } from './types'
import { readStored, writeStored } from './storage'

// The "session" is a claimed identity chosen on the entry screen, not authentication (backlog: M8).
export type Session = {
  tenantId: string
  tenantName: string
  personId: string
  personName: string
  role: Role
}

const KEY = 'triagent.session'

export function parseSession(raw: string | null): Session | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<Session>
    const ok =
      typeof value.tenantId === 'string' &&
      typeof value.tenantName === 'string' &&
      typeof value.personId === 'string' &&
      typeof value.personName === 'string' &&
      (value.role === 'employee' || value.role === 'support')
    return ok ? (value as Session) : null
  } catch {
    return null
  }
}

type SessionContext = {
  session: Session | null
  signIn: (session: Session) => void
  signOut: () => void
}

const Context = createContext<SessionContext | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => parseSession(readStored(KEY)))

  const signIn = useCallback((next: Session) => {
    setSession(next)
    writeStored(KEY, JSON.stringify(next))
  }, [])
  const signOut = useCallback(() => {
    setSession(null)
    writeStored(KEY, null)
  }, [])

  const value = useMemo(() => ({ session, signIn, signOut }), [session, signIn, signOut])
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
