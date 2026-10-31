// Turns the stored conversation (messages), the traces (runs and steps) and the human decisions (approvals)
// into the printed lines of the listing. Pure on purpose: it is the one place the product's story is decided,
// and it is unit-tested.

import type { Translate } from '../i18n/en'
import type { Approval, Message, Run, Step } from './types'
import { parseServerTime } from './time'

export type LineKind = 'user' | 'agent' | 'model' | 'tool' | 'approval' | 'sign' | 'total'
export type StampKind = 'approved' | 'rejected' | 'void' | 'failed' | 'awaiting'

export type Line = {
  key: string
  kind: LineKind
  time: string
  actor: string
  content: string
  detail?: string
  stamp?: StampKind
  struck?: boolean
  step?: Step
  run?: Run
  /** The longest step of the same run, so duration bars are drawn to one scale per run. */
  scaleMs?: number
  durationMs?: number
  tokens?: number
  cost?: string
  /** The user's text, offered again when the run that answered it failed. */
  retryText?: string
}

export type LineInput = {
  messages: Message[]
  runs: Run[]
  approvals: Approval[]
  /** Employee id -> display name, to name who signed. */
  people: Record<string, string>
  /** What the user lines are called: "You" for the owner, the employee's first name for someone else. */
  userLabel: string
  t: Translate
}

const TRUNCATE = 140

export function truncate(text: string, max = TRUNCATE): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

export function humanizeTool(name: string): string {
  return name.replace(/_/g, ' ')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/** Step inputs arrive as {arguments: "<json>"}; the useful part is the parsed object. */
function argsOf(input: unknown): Record<string, unknown> {
  if (!isRecord(input)) return {}
  if (typeof input.arguments === 'string') {
    const parsed = parseJson(input.arguments)
    return isRecord(parsed) ? parsed : {}
  }
  return input
}

function argsSummary(input: unknown): string {
  const args = argsOf(input)
  return truncate(
    Object.entries(args)
      .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
      .join(' · '),
  )
}

function toolNamesOf(message: Message): string[] {
  return (message.tool_calls ?? [])
    .map((call) => {
      // The backend stores {id, name, arguments}; the OpenAI wire shape nests it under `function`.
      const fn = isRecord(call) && isRecord(call.function) ? call.function : call
      return isRecord(fn) && typeof fn.name === 'string' ? fn.name : null
    })
    .filter((name): name is string => name !== null)
}

/** One short line for a tool result that has no message of its own: lists become counts, scalars stay. */
function resultPhrase(out: Record<string, unknown>): string | undefined {
  for (const key of ['message', 'error']) {
    if (typeof out[key] === 'string') return truncate(out[key] as string)
  }
  if (typeof out.status === 'string') {
    return typeof out.system === 'string' ? `${out.system}: ${out.status}` : out.status.replace(/_/g, ' ')
  }
  return outputSummary(out)
}

function outputSummary(out: Record<string, unknown>): string | undefined {
  const parts = Object.entries(out).map(([key, value]) => {
    if (Array.isArray(value)) return `${key}: ${value.length === 0 ? 'none' : value.length}`
    return `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`
  })
  return parts.length ? truncate(parts.join(' · ')) : undefined
}

function stepTokens(step: Step | undefined): number | undefined {
  if (!step || step.prompt_tokens == null) return undefined
  return step.prompt_tokens + (step.completion_tokens ?? 0)
}

type ToolView = { content: string; detail?: string; stamp?: StampKind; struck?: boolean }

export function summarizeTool(name: string, input: unknown, output: unknown, error: string | null, t: Translate): ToolView {
  if (error) return { content: truncate(error), stamp: 'failed', struck: true }

  const out = isRecord(output) ? output : {}
  if (name === 'search_knowledge_base') {
    const query = typeof argsOf(input).query === 'string' ? (argsOf(input).query as string) : ''
    const results = Array.isArray(out.results) ? out.results : []
    const titles = [
      ...new Set(
        results.map((r) => (isRecord(r) && typeof r.article === 'string' ? r.article : '')).filter(Boolean),
      ),
    ]
    return {
      content: query ? `“${truncate(query, 90)}”` : t('line.kbSearch'),
      detail: results.length
        ? t(results.length === 1 ? 'line.kbHit' : 'line.kbHits', { n: results.length, sources: titles.join(' · ') })
        : t('line.kbNone'),
    }
  }

  // Lead with the result in plain words; the arguments are the supporting line, the raw JSON is in the inspector.
  const args = argsSummary(input)
  const result = resultPhrase(out)
  return {
    content: result ?? humanizeTool(name),
    detail: args || undefined,
    stamp: typeof out.error === 'string' ? 'failed' : undefined,
  }
}

function stampOf(approval: Approval): { stamp: StampKind; struck: boolean } {
  switch (approval.status) {
    case 'pending':
      return { stamp: 'awaiting', struck: false }
    case 'approved':
      return { stamp: 'approved', struck: false }
    case 'rejected':
      return { stamp: 'rejected', struck: true }
    case 'expired':
      return { stamp: 'void', struck: true }
  }
}

export function buildLines({ messages, runs, approvals, people, userLabel, t }: LineInput): Line[] {
  const runById = new Map(runs.map((run) => [run.id, run]))
  const approvalById = new Map(approvals.map((a) => [a.id, a]))
  const ordered = [...messages].sort((a, b) => a.seq - b.seq)
  const lines: Line[] = []
  const approvalLineAt = new Map<string, number>()

  const scaleOf = (run: Run | undefined) =>
    run ? Math.max(1, ...run.steps.map((s) => s.latency_ms)) : undefined

  const closeRun = (run: Run | undefined, at: number) => {
    // A finished run ends with a totals line. A running one is shown by the live line instead.
    if (!run || run.status === 'running' || run.steps.length === 0) return
    const finished = run.finished_at ?? run.started_at
    const failed = run.status === 'failed' || run.status === 'max_steps'
    lines.splice(at, 0, {
      key: `total-${run.id}`,
      kind: 'total',
      time: finished,
      actor: t('line.run'),
      content: t('line.runSummary', { n: run.steps.length, model: run.model }),
      stamp: failed ? 'failed' : undefined,
      durationMs: Math.max(0, parseServerTime(finished).getTime() - parseServerTime(run.started_at).getTime()),
      tokens: run.prompt_tokens + run.completion_tokens,
      cost: run.cost_usd,
      run,
    })
  }

  let current: Run | undefined
  let lastUserText = ''
  for (const message of ordered) {
    const run = message.run_id ? runById.get(message.run_id) : undefined
    if (run !== current) {
      closeRun(current, lines.length)
      current = run
    }
    const step = run?.steps.find((s) => s.step_index === message.step_index)
    const base = { time: message.created_at, step, run, scaleMs: scaleOf(run) }

    if (message.role === 'user') {
      lastUserText = message.content
      lines.push({ ...base, key: message.id, kind: 'user', actor: userLabel, content: message.content })
    } else if (message.role === 'assistant') {
      const names = toolNamesOf(message)
      if (!message.content.trim() && names.length) {
        lines.push({
          ...base,
          key: message.id,
          kind: 'model',
          actor: t('line.model'),
          content: t('line.calls', { tools: names.join(', ') }),
          durationMs: step?.latency_ms,
          tokens: stepTokens(step),
        })
      } else {
        const failed = Boolean(step?.error)
        lines.push({
          ...base,
          key: message.id,
          kind: 'agent',
          actor: t('line.agent'),
          content: message.content,
          stamp: failed ? 'failed' : undefined,
          durationMs: step?.latency_ms,
          tokens: stepTokens(step),
          retryText: failed ? lastUserText : undefined,
        })
      }
    } else {
      const output = step?.output ?? parseJson(message.content)
      const approvalId = isRecord(output) && typeof output.approval_id === 'string' ? output.approval_id : null
      const approval = approvalId ? approvalById.get(approvalId) : undefined
      const name = message.tool_name ?? step?.name ?? 'tool'
      if (approval) {
        const { stamp, struck } = stampOf(approval)
        approvalLineAt.set(approval.id, lines.length)
        lines.push({
          ...base,
          key: message.id,
          kind: 'approval',
          actor: name,
          content: argsSummary(approval.arguments) || t('line.noArguments'),
          detail: approval.status === 'pending' ? t('line.needsSignature') : undefined,
          stamp,
          struck,
          durationMs: step?.latency_ms,
        })
      } else {
        const view = summarizeTool(name, step?.input, output, step?.error ?? null, t)
        lines.push({ ...base, key: message.id, kind: 'tool', actor: name, durationMs: step?.latency_ms, ...view })
      }
    }
  }
  closeRun(current, lines.length)

  // Decisions are printed where they happened in time, as signed lines of their own.
  for (const approval of approvals) {
    const at = approvalLineAt.get(approval.id)
    if (at === undefined || approval.status === 'pending') continue
    const when = approval.decided_at ?? approval.expires_at
    const signer = approval.decided_by ? (people[approval.decided_by] ?? t('line.support')) : t('line.system')
    const { stamp } = stampOf(approval)
    const note = approval.decision_note ? ` · “${approval.decision_note}”` : ''
    const sign: Line = {
      key: `sign-${approval.id}`,
      kind: 'sign',
      time: when,
      actor: signer,
      content: t(
        approval.status === 'approved'
          ? 'line.signedApproved'
          : approval.status === 'rejected'
            ? 'line.signedRejected'
            : 'line.expired',
        { tool: approval.tool_name },
      ) + note,
      stamp,
    }
    const whenMs = parseServerTime(when).getTime()
    let index = lines.findIndex((l, i) => i > at && parseServerTime(l.time).getTime() > whenMs)
    if (index === -1) index = lines.length
    lines.splice(index, 0, sign)
  }
  return lines
}

/** Tokens spent so far by a run that is still going (its cost is only known when it ends). */
export function tokensSoFar(run: Run | undefined): number {
  return (run?.steps ?? []).reduce((sum, s) => sum + (stepTokens(s) ?? 0), 0)
}
