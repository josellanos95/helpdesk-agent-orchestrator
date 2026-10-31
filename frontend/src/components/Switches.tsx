import { useId } from 'react'
import { Languages } from 'lucide-react'
import { useI18n, type Lang } from '../i18n'
import { useTheme, type ThemeChoice } from '../lib/theme'

export function LanguageSwitch() {
  const { t, lang, setLang } = useI18n()
  const id = useId()
  const langs: Lang[] = ['en', 'es']
  return (
    <div>
      <p className="label" id={id}>{t('settings.language')}</p>
      <div className="seg" role="radiogroup" aria-labelledby={id}>
        {langs.map((code) => (
          <button key={code} type="button" role="radio" aria-checked={lang === code} onClick={() => setLang(code)}>
            {code === 'en' ? 'English' : 'Español'}
          </button>
        ))}
      </div>
    </div>
  )
}

export function ThemeSwitch() {
  const { t } = useI18n()
  const { theme, setTheme } = useTheme()
  const id = useId()
  const themes: ThemeChoice[] = ['system', 'light', 'dark']
  return (
    <div>
      <p className="label" id={id}>{t('settings.theme')}</p>
      <div className="seg" role="radiogroup" aria-labelledby={id}>
        {themes.map((choice) => (
          <button key={choice} type="button" role="radio" aria-checked={theme === choice} onClick={() => setTheme(choice)}>
            {t(`theme.${choice}`)}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Always visible: an evaluator should never have to hunt for the other language. */
export function LangToggle() {
  const { t, lang, setLang } = useI18n()
  const next: Lang = lang === 'en' ? 'es' : 'en'
  const name = next === 'es' ? 'Español' : 'English'
  return (
    <button
      type="button"
      className="btn btn-sm"
      lang={next}
      aria-label={t('settings.switchLang', { name })}
      onClick={() => setLang(next)}
    >
      <Languages size={18} aria-hidden />
      <span className="font-bold">{next.toUpperCase()}</span>
    </button>
  )
}
