import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { request } from './api'
import type {
  Approval,
  ApprovalStatus,
  Article,
  ConversationItem,
  Employee,
  Escalation,
  Message,
  Run,
  Tenant,
  Ticket,
} from './types'

// Every tenant-scoped key starts with ['t', tenantId] so one invalidation refreshes everything of a tenant.
export const tenantKey = (tenantId: string) => ['t', tenantId] as const

export function useTenants() {
  return useQuery({ queryKey: ['tenants'], queryFn: () => request<Tenant[]>('/tenants') })
}

export function useEmployees(tenantId: string) {
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'employees'],
    queryFn: () => request<Employee[]>('/employees', { tenantId }),
    staleTime: 60_000,
  })
}

export function useArticles(tenantId: string) {
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'articles'],
    queryFn: () => request<Article[]>('/kb/articles', { tenantId }),
  })
}

export function useArticle(tenantId: string, id: string | undefined) {
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'article', id],
    queryFn: () => request<Article>(`/kb/articles/${id}`, { tenantId }),
    enabled: Boolean(id),
  })
}

export function useConversations(tenantId: string, employeeId?: string) {
  const query = employeeId ? `?employee_id=${employeeId}` : ''
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'conversations', employeeId ?? 'all'],
    queryFn: () => request<ConversationItem[]>(`/conversations${query}`, { tenantId }),
    refetchInterval: 15_000,
  })
}

const FAST_MS = 900
const CALM_MS = 5000

function runsKey(tenantId: string, conversationId: string | undefined) {
  return [...tenantKey(tenantId), 'runs', conversationId] as const
}

/** True while any run of the conversation is still going, whoever started it. */
function someRunning(client: QueryClient, tenantId: string, conversationId: string | undefined): boolean {
  const runs = client.getQueryData<Run[]>(runsKey(tenantId, conversationId))
  return Boolean(runs?.some((run) => run.status === 'running'))
}

/** `fast` is true while this screen has a message in flight, so steps and lines show up as they are committed. */
export function useMessages(tenantId: string, conversationId: string | undefined, fast: boolean) {
  const client = useQueryClient()
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'messages', conversationId],
    queryFn: () => request<Message[]>(`/conversations/${conversationId}/messages`, { tenantId }),
    enabled: Boolean(conversationId),
    refetchInterval: () => (fast || someRunning(client, tenantId, conversationId) ? FAST_MS : CALM_MS),
  })
}

export function useRuns(tenantId: string, conversationId: string | undefined, fast: boolean) {
  const client = useQueryClient()
  return useQuery({
    queryKey: runsKey(tenantId, conversationId),
    queryFn: () => request<Run[]>(`/conversations/${conversationId}/runs`, { tenantId }),
    enabled: Boolean(conversationId),
    refetchInterval: () => (fast || someRunning(client, tenantId, conversationId) ? FAST_MS : CALM_MS),
  })
}

type ApprovalFilter = { status?: ApprovalStatus | 'all'; conversationId?: string; requestedBy?: string }

export function useApprovals(tenantId: string, filter: ApprovalFilter = {}, fast = false) {
  const params = new URLSearchParams({ status: filter.status ?? 'all' })
  if (filter.conversationId) params.set('conversation_id', filter.conversationId)
  if (filter.requestedBy) params.set('requested_by', filter.requestedBy)
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'approvals', params.toString()],
    queryFn: () => request<Approval[]>(`/approvals?${params}`, { tenantId }),
    refetchInterval: fast ? 900 : 4000,
  })
}

export function useEscalations(tenantId: string, status: 'open' | 'all' = 'open') {
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'escalations', status],
    queryFn: () => request<Escalation[]>(`/escalations?status=${status}`, { tenantId }),
    refetchInterval: 5000,
  })
}

export function useTickets(tenantId: string, employeeId?: string) {
  const query = employeeId ? `?employee_id=${employeeId}` : ''
  return useQuery({
    queryKey: [...tenantKey(tenantId), 'tickets', employeeId ?? 'all'],
    queryFn: () => request<Ticket[]>(`/tickets${query}`, { tenantId }),
    refetchInterval: 8000,
  })
}
