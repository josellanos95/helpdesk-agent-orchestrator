import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n'
import type { Line } from '../lib/lines'
import { Composer } from './Composer'
import { Listing } from './Listing'
import { Stamp } from './Stamp'

function wrap(ui: ReactNode) {
  return render(
    <I18nProvider>
      <MemoryRouter>{ui}</MemoryRouter>
    </I18nProvider>,
  )
}

const line = (over: Partial<Line> & Pick<Line, 'key' | 'kind'>): Line => ({
  time: '2026-11-01T10:00:00.000000',
  actor: 'Agent',
  content: 'hello',
  ...over,
})

describe('Composer', () => {
  it('sends on Enter, keeps Shift+Enter for a new line, and ignores empty text', async () => {
    const onSend = vi.fn()
    wrap(<Composer busy={false} onSend={onSend} />)
    const box = screen.getByLabelText('Message to the agent')
    const send = screen.getByRole('button', { name: /send/i })
    expect(send).toBeDisabled()

    await userEvent.type(box, '   {Enter}')
    expect(onSend).not.toHaveBeenCalled()

    await userEvent.type(box, 'first{Shift>}{Enter}{/Shift}second')
    expect(onSend).not.toHaveBeenCalled()
    await userEvent.type(box, '{Enter}')
    expect(onSend).toHaveBeenCalledWith('first\nsecond')
    expect(box).toHaveValue('')
  })

  it('cannot send while a message is in flight', () => {
    wrap(<Composer busy onSend={vi.fn()} />)
    expect(screen.getByRole('button', { name: /working/i })).toBeDisabled()
  })
})

describe('Listing', () => {
  it('prints each line with its actor and stamp, and keeps a struck line on the page', () => {
    wrap(
      <Listing
        label="Conversation listing"
        userLabel="You"
        lines={[
          line({ key: '1', kind: 'user', actor: 'You', content: 'reset my password' }),
          line({ key: '2', kind: 'approval', actor: 'reset_password', content: 'reason: forgot', stamp: 'rejected', struck: true }),
        ]}
      />,
    )
    const log = screen.getByRole('log', { name: 'Conversation listing' })
    expect(log).toHaveTextContent('reset my password')
    expect(log).toHaveTextContent('Rejected')
    expect(screen.getByText('reason: forgot')).toBeInTheDocument()
    expect(log.querySelector('.struck')).not.toBeNull()
  })

  it('makes lines with a step inspectable by keyboard', async () => {
    const onSelect = vi.fn()
    wrap(
      <Listing
        label="L"
        userLabel="You"
        onSelect={onSelect}
        lines={[
          line({
            key: 'tool',
            kind: 'tool',
            actor: 'search_knowledge_base',
            content: 'query',
            step: { step_index: 0, kind: 'tool', name: 'x', input: null, output: null, latency_ms: 10, prompt_tokens: null, completion_tokens: null, error: null },
          }),
        ]}
      />,
    )
    const button = screen.getByRole('button', { name: /inspect this line/i })
    button.focus()
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('shows the live line with its hint while the agent works, and a NOT SENT line that can be resent', async () => {
    const onResend = vi.fn()
    wrap(
      <Listing
        label="L"
        userLabel="You"
        lines={[]}
        live={{ elapsedMs: 4200, hint: 'Reading the result', tokens: 1800, progress: 0.14 }}
        pending={{ text: 'help me', state: 'not_sent', note: 'No answer from the server.', onResend, onDismiss: vi.fn() }}
      />,
    )
    expect(screen.getByText('Reading the result')).toBeInTheDocument()
    expect(screen.getByText('4.2 s')).toBeInTheDocument()
    expect(screen.getByText('Not sent')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /send again/i }))
    expect(onResend).toHaveBeenCalled()
  })
})

describe('Stamp', () => {
  it('always carries the state as a word, not only a colour', () => {
    wrap(<Stamp kind="awaiting" />)
    expect(screen.getByText('Awaiting')).toBeInTheDocument()
  })
})
