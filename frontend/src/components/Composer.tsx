import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { SendHorizontal } from 'lucide-react'
import { useI18n } from '../i18n'

type Props = { busy: boolean; onSend: (text: string) => void }

/** Enter sends, Shift+Enter breaks the line. 16px text so a phone does not zoom the page on focus. */
export function Composer({ busy, onSend }: Props) {
  const { t } = useI18n()
  const [text, setText] = useState('')
  const area = useRef<HTMLTextAreaElement>(null)

  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight + 2, 144)}px`
  }, [text])

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    const value = text.trim()
    if (!value || busy) return
    onSend(value)
    setText('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <label htmlFor="composer-input" className="sr-only">
        {t('composer.label')}
      </label>
      <div className="composer-row">
        <textarea
          id="composer-input"
          ref={area}
          className="field"
          rows={1}
          maxLength={4000}
          placeholder={t('composer.placeholder')}
          enterKeyHint="send"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>
          <SendHorizontal size={18} aria-hidden />
          <span>{busy ? t('composer.busy') : t('composer.send')}</span>
        </button>
      </div>
    </form>
  )
}
