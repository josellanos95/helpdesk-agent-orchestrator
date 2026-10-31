import { describe, expect, it } from 'vitest'
import { duration, money, parseServerTime, tokens } from './time'

describe('time helpers', () => {
  it('reads the backend naive datetimes as UTC, not local time', () => {
    expect(parseServerTime('2026-11-01T10:00:00.123456').toISOString()).toBe('2026-11-01T10:00:00.123Z')
    expect(parseServerTime('2026-11-01T10:00:00Z').toISOString()).toBe('2026-11-01T10:00:00.000Z')
    expect(parseServerTime('2026-11-01T10:00:00+02:00').toISOString()).toBe('2026-11-01T08:00:00.000Z')
  })

  it('formats durations, tokens and sub-cent costs', () => {
    expect(duration(840)).toBe('840 ms')
    expect(duration(6120)).toBe('6.1 s')
    expect(duration(75_000)).toBe('1 m 15 s')
    expect(tokens(842)).toBe('842')
    expect(tokens(1842)).toBe('1.8k')
    expect(money('0.0021')).toBe('$0.0021')
    expect(money('0.1234')).toBe('$0.123')
    expect(money('0')).toBe('$0')
    expect(money('abc')).toBe('-')
  })
})
