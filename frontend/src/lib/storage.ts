// localStorage can throw (private windows, blocked site data) or come back empty. Every read and write here is
// guarded, and the app renders correctly without it.

export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // ignore: the choice just will not survive a reload
  }
}
