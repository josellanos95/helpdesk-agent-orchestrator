import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Translate } from './en'
import { initialLang, translate, type Lang } from './translate'
import { readStored, writeStored } from '../lib/storage'

const KEY = 'triagent.lang'
type I18n = { lang: Lang; locale: string; setLang: (lang: Lang) => void; t: Translate }
const Context = createContext<I18n | null>(null)

export type { Lang }

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() =>
    initialLang(readStored(KEY), typeof navigator === 'undefined' ? undefined : navigator.language),
  )

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    writeStored(KEY, next)
  }, [])
  const t = useCallback<Translate>((key, vars) => translate(lang, key, vars), [lang])
  const value = useMemo(
    () => ({ lang, locale: lang === 'es' ? 'es' : 'en-GB', setLang, t }),
    [lang, setLang, t],
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useI18n(): I18n {
  const value = useContext(Context)
  if (!value) throw new Error('useI18n needs an I18nProvider')
  return value
}
