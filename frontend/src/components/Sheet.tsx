import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { useI18n } from '../i18n'

type Props = { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }

/**
 * A native <dialog>: focus is trapped, Escape closes it and the page behind is inert. A bottom sheet on a
 * phone, a panel under the top bar on a desktop.
 */
export function Sheet({ open, onClose, title, children, wide }: Props) {
  const { t } = useI18n()
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className={`sheet ${wide ? 'sheet-wide' : ''}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose()
      }}
    >
      <div className="sheet-head">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="btn btn-quiet btn-icon" aria-label={t('common.close')} onClick={onClose}>
          <X size={20} aria-hidden />
        </button>
      </div>
      <div className="sheet-body">{open ? children : null}</div>
    </dialog>
  )
}
