// Shapes returned by the backend (backend/app/api/routes). Datetimes are ISO strings WITHOUT a timezone
// (naive UTC) and decimals arrive as strings: parse them with lib/time.ts.

export type Tenant = { id: string; name: string; slug: string }

export type Employee = {
  id: string
  full_name: string
  email: string
  job_title: string
  is_support_agent: boolean
}

export type Role = 'employee' | 'support'

export type ConversationItem = {
  id: string
  employee_id: string
  employee_name: string
  started_at: string
  last_message_at: string
  title: string
  preview: string
  pending_approvals: number
}

export type MessageRole = 'user' | 'assistant' | 'tool'

export type Message = {
  id: string
  seq: number
  role: MessageRole
  content: string
  tool_name: string | null
  tool_call_id: string | null
  tool_calls: unknown[] | null
  run_id: string | null
  step_index: number | null
  created_at: string
}

export type Step = {
  step_index: number
  kind: 'llm' | 'tool' | string
  name: string
  input: unknown
  output: unknown
  latency_ms: number
  prompt_tokens: number | null
  completion_tokens: number | null
  error: string | null
}

export type RunStatus = 'running' | 'completed' | 'failed' | 'max_steps'

export type Run = {
  id: string
  conversation_id: string
  status: RunStatus
  model: string
  prompt_tokens: number
  completion_tokens: number
  cost_usd: string
  error: string | null
  started_at: string
  finished_at: string | null
  steps: Step[]
}

export type SendResult = {
  reply: string
  run: { run_id: string; status: RunStatus; prompt_tokens: number; completion_tokens: number; cost_usd: string }
}

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired'

export type Approval = {
  id: string
  conversation_id: string
  requested_by: string
  requested_by_name: string
  tool_name: string
  arguments: Record<string, unknown>
  status: ApprovalStatus
  decided_by: string | null
  decision_note: string | null
  result: Record<string, unknown> | null
  created_at: string
  expires_at: string
  decided_at: string | null
}

export type Escalation = {
  id: string
  ticket_id: string
  ticket_subject: string
  reason: string
  urgency: string
  status: 'pending' | 'acknowledged' | 'resolved'
  created_at: string
  resolved_at: string | null
}

export type Ticket = {
  id: string
  conversation_id: string | null
  employee_id: string
  employee_name: string
  category: string
  subject: string
  priority: string
  status: 'open' | 'in_progress' | 'escalated' | 'resolved' | 'closed'
  created_at: string
  updated_at: string
}

export type Article = {
  id: string
  title: string
  passages: number
  updated_at: string
  body: string | null
}

export type Hit = {
  article_id: string
  article: string
  passage: string
  similarity: number | null
  keyword_match: boolean
  score: number
}
