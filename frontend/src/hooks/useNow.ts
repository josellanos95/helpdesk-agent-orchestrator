import { useEffect, useState } from 'react'

/** A clock that ticks only while `active`, so idle screens do not re-render. */
export function useNow(active: boolean, intervalMs = 100): number {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(performance.now()), intervalMs)
    return () => clearInterval(timer)
  }, [active, intervalMs])
  return now
}
