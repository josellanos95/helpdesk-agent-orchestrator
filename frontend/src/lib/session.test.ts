import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseSession } from './session'
import { readStored, writeStored } from './storage'

const valid = { tenantId: 't', tenantName: 'Acme', personId: 'p', personName: 'Marco', role: 'employee' }

afterEach(() => vi.restoreAllMocks())

describe('parseSession', () => {
  it('accepts a complete session', () => {
    expect(parseSession(JSON.stringify(valid))).toEqual(valid)
  })

  it('falls back to no session for anything damaged', () => {
    expect(parseSession(null)).toBeNull()
    expect(parseSession('not json')).toBeNull()
    expect(parseSession(JSON.stringify({ ...valid, role: 'admin' }))).toBeNull()
    expect(parseSession(JSON.stringify({ tenantId: 't' }))).toBeNull()
  })
})

describe('storage', () => {
  it('never throws when the browser blocks storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readStored('k')).toBeNull()
    expect(() => writeStored('k', 'v')).not.toThrow()
  })
})
