import { en, type StringKey } from './en'
import { es } from './es'

export type Lang = 'en' | 'es'
const tables: Record<Lang, Record<StringKey, string>> = { en, es }

export function translate(lang: Lang, key: StringKey, vars?: Record<string, string | number>): string {
  const template = tables[lang][key] ?? en[key]
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole))
}

export function initialLang(stored: string | null, browser: string | undefined): Lang {
  if (stored === 'en' || stored === 'es') return stored
  return browser?.toLowerCase().startsWith('es') ? 'es' : 'en'
}
