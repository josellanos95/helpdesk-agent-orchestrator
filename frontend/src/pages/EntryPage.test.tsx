import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n'
import { SessionProvider } from '../lib/session'
import { ThemeProvider } from '../lib/theme'
import { EntryPage } from './EntryPage'

const TENANT = { id: 't1', name: 'Acme Corp', slug: 'acme' }
const PEOPLE = [
  { id: 'e1', full_name: 'Marco Silva', email: 'm@acme.test', job_title: 'Sales Representative', is_support_agent: false },
  { id: 's1', full_name: 'Alice Nguyen', email: 'a@acme.test', job_title: 'IT Support Analyst', is_support_agent: true },
]

function route(url: string) {
  const body = url.endsWith('/tenants') ? [TENANT] : url.endsWith('/employees') ? PEOPLE : url.endsWith('/articles') ? [{}, {}, {}] : []
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))
}

function open() {
  vi.stubGlobal('fetch', vi.fn((url: string) => route(url)))
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

afterEach(() => vi.unstubAllGlobals())

describe('EntryPage', () => {
  it('lists the companies with their counts and says plainly that identity is claimed', async () => {
    open()
    expect(await screen.findByRole('button', { name: /choose acme corp/i })).toBeInTheDocument()
    expect(await screen.findByText('2 people · 3 articles')).toBeInTheDocument()
    expect(screen.getByText(/nothing is authenticated/i)).toBeInTheDocument()
  })

  it('enters as an employee and lands on the chat', async () => {
    open()
    await userEvent.click(await screen.findByRole('button', { name: /choose acme corp/i }))
    const panel = await screen.findByText('Marco Silva')
    expect(screen.queryByText('Alice Nguyen')).not.toBeInTheDocument()
    await userEvent.click(panel)
    expect(await screen.findByText('chat screen')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('triagent.session')!)).toMatchObject({ personId: 'e1', role: 'employee' })
  })

  it('switches to the support persona and lands on the queue', async () => {
    open()
    await userEvent.click(await screen.findByRole('button', { name: /choose acme corp/i }))
    await userEvent.click(await screen.findByRole('radio', { name: 'Support agent' }))
    const list = screen.getByRole('radiogroup', { name: /enter as/i }).parentElement!
    await userEvent.click(await within(list).findByText('Alice Nguyen'))
    expect(await screen.findByText('queue screen')).toBeInTheDocument()
  })
})
