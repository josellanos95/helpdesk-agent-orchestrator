import { useI18n } from '../i18n'
import type { StringKey } from '../i18n/en'
import type { StampKind } from '../lib/lines'

const LABEL: Record<StampKind | 'notSent', StringKey> = {
  approved: 'stamp.approved',
  rejected: 'stamp.rejected',
  void: 'stamp.void',
  failed: 'stamp.failed',
  awaiting: 'stamp.awaiting',
  notSent: 'stamp.notSent',
}

/** A rubber stamp. The word is always present: colour never carries the state alone. */
export function Stamp({ kind, className = '' }: { kind: StampKind | 'notSent'; className?: string }) {
  const { t } = useI18n()
  const tone = kind === 'notSent' ? 'void' : kind
  return <span className={`stamp stamp-${tone} ${className}`}>{t(LABEL[kind])}</span>
}

/** Neutral status label for things that are not a decision (ticket and escalation states). */
export function StatusTag({ label }: { label: string }) {
  return <span className="stamp stamp-plain">{label}</span>
}
