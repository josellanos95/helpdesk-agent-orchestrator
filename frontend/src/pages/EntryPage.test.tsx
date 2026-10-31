import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n'
import { setAuthToken } from '../lib/api'
import { SessionProvider } from '../lib/session'
import { ThemeProvider } from '../lib/theme'
import { EntryPage } from './EntryPage'

const MARCO = { id: 'e1', full_name: 'Marco Silva', job_title: 'Sales Representative', is_support_agent: false }
const ALICE = { id: 's1', full_name: 'Alice Nguyen', job_title: 'IT Support Analyst', is_support_agent: true }
const COMPANY = { id: 't1', name: 'Acme Corp', slug: 'acme', articles: 3, people: [MARCO, ALICE] }

let sessionRequests: unknown[] = []
let sessionStatus = 200

function route(url: string, init?: RequestInit) {
  if (url.endsWith('/demo/directory')) return json(200, [COMPANY])
  if (url.endsWith('/demo/session')) {
    const body = JSON.parse(String(init?.body))
    sessionRequests.push(body)
    if (sessionStatus !== 200) {
      return json(429, { detail: { code: 'rate_limited', message: 'Too many requests.' } })
    }
    const person = body.employee_id === ALICE.id ? ALICE : MARCO
    return json(200, {
      token: 'signed.token',
      expires_at: '2999-01-01T00:00:00Z',
      tenant: { ...COMPANY, people: [] },
      person,
      role: person.is_support_agent ? 'support' : 'employee',
    })
  }
  return json(200, [])
}

function json(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

function open() {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => route(url, init)))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <ThemeProvider>
          <SessionProvider>
            <MemoryRouter initialEntries={['/']}>
              <Routes>
                <Route path="/" element={<EntryPage />} />
                <Route path="/chat" element={<p>chat screen</p>} />
                <Route path="/queue" element={<p>queue screen</p>} />
              </Routes>
            </MemoryRouter>
          </SessionProvider>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  sessionRequests = []
  sessionStatus = 200
  setAuthToken(null)
})

describe('EntryPage', () => {
  it('lists the companies with their counts and says plainly that identity is claimed', async () => {
    open()
    expect(await screen.findByRole('button', { name: /choose acme corp/i })).toBeInTheDocument()
    expect(await screen.findByText('2 people · 3 articles')).toBeInTheDocument()
    expect(screen.getByText(/nothing is authenticated/i)).toBeInTheDocument()
  })

  it('asks the server for a signed session as an employee and lands on the chat', async () => {
    open()
    await userEvent.click(await screen.findByRole('button', { name: /choose acme corp/i }))
    expect(screen.queryByText('Alice Nguyen')).not.toBeInTheDocument()
    await userEvent.click(await screen.findByText('Marco Silva'))
    expect(await screen.findByText('chat screen')).toBeInTheDocument()
    expect(sessionRequests).toEqual([{ tenant_id: 't1', employee_id: 'e1' }])
    expect(JSON.parse(localStorage.getItem('triagent.session')!)).toMatchObject({
      token: 'signed.token',
      personId: 'e1',
      role: 'employee',
    })
  })

  it('switches to the support persona and lands on the queue', async () => {
    open()
    await userEvent.click(await screen.findByRole('button', { name: /choose acme corp/i }))
    await userEvent.click(await screen.findByRole('radio', { name: 'Support agent' }))
    const list = screen.getByRole('radiogroup', { name: /enter as/i }).parentElement!
    await userEvent.click(await within(list).findByText('Alice Nguyen'))
    expect(await screen.findByText('queue screen')).toBeInTheDocument()
  })

  it('stays on the entry screen and says why when the server refuses to start a session', async () => {
    sessionStatus = 429
    open()
    await userEvent.click(await screen.findByRole('button', { name: /choose acme corp/i }))
    await userEvent.click(await screen.findByText('Marco Silva'))
    expect(await screen.findByRole('alert')).toHaveTextContent(/too many requests/i)
    expect(screen.queryByText('chat screen')).not.toBeInTheDocument()
    expect(localStorage.getItem('triagent.session')).toBeNull()
  })

  it('tells someone whose stored session expired to choose a person again', async () => {
    localStorage.setItem(
      'triagent.session',
      JSON.stringify({
        token: 'old',
        expiresAt: '2000-01-01T00:00:00Z',
        tenantId: 't1',
        tenantName: 'Acme Corp',
        personId: 'e1',
        personName: 'Marco Silva',
        role: 'employee',
      }),
    )
    open()
    expect(await screen.findByRole('button', { name: /choose acme corp/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /continue as/i })).not.toBeInTheDocument()
  })
})
