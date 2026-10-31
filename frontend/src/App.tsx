import { Link, Navigate, Route, Routes, useLocation } from 'react-router'
import { Shell } from './components/Shell'
import { useI18n } from './i18n'
import { useSession } from './lib/session'
import { ChatPage } from './pages/ChatPage'
import { EntryPage } from './pages/EntryPage'
import { ArticlePage, KnowledgeListPage } from './pages/KnowledgePage'
import { QueuePage } from './pages/QueuePage'
import { RequestsPage } from './pages/RequestsPage'
import type { Role } from './lib/types'

/** Pages are for one role; a link to another role's page lands on that role's home instead. */
function Guard({ role, children }: { role?: Role; children: React.ReactNode }) {
  const { session } = useSession()
  const location = useLocation()
  if (!session) return <Navigate to="/" replace state={{ from: location.pathname }} />
  if (role && session.role !== role) return <Navigate to={session.role === 'support' ? '/queue' : '/chat'} replace />
  return <>{children}</>
}

function NotFound() {
  const { t } = useI18n()
  return (
    <div className="page">
      <h1 className="page-title">{t('notfound.title')}</h1>
      <Link to="/" className="btn mt-4">{t('notfound.home')}</Link>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<EntryPage />} />
      <Route element={<Guard><Shell /></Guard>}>
        <Route path="chat/:id?" element={<Guard role="employee"><ChatPage review={false} /></Guard>} />
        <Route path="requests" element={<Guard role="employee"><RequestsPage /></Guard>} />
        <Route path="queue" element={<Guard role="support"><QueuePage /></Guard>} />
        <Route path="chats/:id?" element={<Guard role="support"><ChatPage review /></Guard>} />
        <Route path="knowledge" element={<KnowledgeListPage />} />
        <Route path="knowledge/new" element={<ArticlePage create />} />
        <Route path="knowledge/:id" element={<ArticlePage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
