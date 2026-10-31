import { describe, expect, it } from 'vitest'
import { parseBlocks, plainText } from './richtext'

describe('plainText', () => {
  it('flattens markdown for a one-line preview', () => {
    const markdown = 'According to **the article** "VPN":\n- Update `AcmeConnect`\n- Restart'
    expect(plainText(markdown)).toBe('According to the article "VPN": Update AcmeConnect Restart')
  })
})

describe('parseBlocks', () => {
  it('splits paragraphs, bullet lists and numbered lists', () => {
    const blocks = parseBlocks('Intro line\n\n- one\n- two\n\n1. first\n2. second')
    expect(blocks).toEqual([
      { type: 'p', text: 'Intro line' },
      { type: 'ul', items: ['one', 'two'] },
      { type: 'ol', items: ['first', 'second'] },
    ])
  })

  it('keeps markup-looking text as plain text, never as HTML', () => {
    expect(parseBlocks('<img src=x onerror=alert(1)>')).toEqual([
      { type: 'p', text: '<img src=x onerror=alert(1)>' },
    ])
  })
})
