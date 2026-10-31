import { useEffect, useState } from 'react'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

function App() {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'ok' | 'error'>('checking')

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/health`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then(() => setBackendStatus('ok'))
      .catch(() => setBackendStatus('error'))
  }, [])

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-white text-slate-900">
      <h1 className="text-3xl font-semibold">Triagent</h1>
      <p className="text-slate-500">Multi-tenant AI agent for IT helpdesk support — work in progress.</p>
      <div className="flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm">
        <span
          className={`h-2 w-2 rounded-full ${
            backendStatus === 'ok'
              ? 'bg-emerald-500'
              : backendStatus === 'error'
                ? 'bg-red-500'
                : 'bg-amber-400'
          }`}
        />
        backend: {backendStatus}
      </div>
    </div>
  )
}

export default App
