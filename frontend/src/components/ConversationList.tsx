import { Link } from 'react-router'
import { useI18n } from '../i18n'
import type { ConversationItem } from '../lib/types'
import { plainText } from '../lib/richtext'
import { ago } from '../lib/time'
import { Stamp } from './Stamp'

type Props = {
  items: ConversationItem[]
  activeId?: string
  basePath: '/chat' | '/chats'
  /** Support agents see whose conversation it is; an employee only sees their own. */
  showOwner: boolean
  onNavigate?: () => void
}

export function ConversationList({ items, activeId, basePath, showOwner, onNavigate }: Props) {
  const { t, locale } = useI18n()
  if (items.length === 0) {
    return <p className="muted small p-4">{t(showOwner ? 'chats.empty' : 'chat.historyEmpty')}</p>
  }
  return (
    <ul className="ruled">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            to={`${basePath}/${item.id}`}
            className="item conv-item"
            aria-current={item.id === activeId ? 'page' : undefined}
            onClick={onNavigate}
          >
            <span className="spread">
              <span className="item-title conv-title">{showOwner ? item.employee_name : item.title || t('chat.untitled')}</span>
              <span className="item-meta num shrink-0">{ago(item.last_message_at, locale)}</span>
            </span>
            <span className="conv-preview text-ink-2">
              {showOwner ? item.title || t('chat.untitled') : plainText(item.preview)}
            </span>
            {item.pending_approvals > 0 && (
              <span className="mt-1.5 block">
                <Stamp kind="awaiting" />
              </span>
            )}
          </Link>
        </li>
      ))}
    </ul>
  )
}
