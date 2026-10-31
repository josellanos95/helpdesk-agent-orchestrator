import { describe, expect, it } from 'vitest'
import { en } from './en'
import { es } from './es'
import { initialLang, translate } from './translate'

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

describe('translations', () => {
  it('Spanish defines exactly the English keys', () => {
    expect(Object.keys(es).sort()).toEqual(Object.keys(en).sort())
  })

  it('has no empty strings and the same placeholders in both languages', () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(en[key].trim(), key).not.toBe('')
      expect(es[key].trim(), key).not.toBe('')
      expect(placeholders(es[key]), key).toEqual(placeholders(en[key]))
    }
  })

  it('fills placeholders and leaves unknown ones visible', () => {
    expect(translate('en', 'common.people', { n: 3 })).toBe('3 people')
    expect(translate('es', 'common.people', { n: 3 })).toBe('3 personas')
    expect(translate('en', 'common.people')).toBe('{n} people')
  })

  it('picks the stored language, else the browser one, else English', () => {
    expect(initialLang('es', 'en-US')).toBe('es')
    expect(initialLang(null, 'es-CO')).toBe('es')
    expect(initialLang(null, 'fr-FR')).toBe('en')
    expect(initialLang('xx', undefined)).toBe('en')
  })
})
