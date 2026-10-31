import { beforeEach, describe, expect, it } from 'vitest'
import { translate } from '../i18n/translate'
import { buildLines, summarizeTool, tokensSoFar, truncate } from './lines'
import { approval, message, resetSeq, run, step } from '../test/fixtures'

const t = (key: Parameters<typeof translate>[1], vars?: Record<string, string | number>) =>
  translate('en', key, vars)
const base = { people: { s1: 'Alice Nguyen' }, userLabel: 'You', t }

beforeEach(resetSeq)

describe('buildLines', () => {
  it('prints the user line, the model decision, the tool, the reply and a totals line, each linked to its step', () => {
    const steps = [
      step({ step_index: 0, kind: 'llm', name: 'gpt-5-mini', latency_ms: 2000, prompt_tokens: 400, completion_tokens: 20 }),
      step({
        step_index: 1,
        kind: 'tool',
        name: 'search_knowledge_base',
        latency_ms: 500,
        input: { query: 'vpn drops' },
        output: { results: [{ article: 'VPN troubleshooting' }, { article: 'VPN troubleshooting' }] },
      }),
      step({ step_index: 2, kind: 'llm', name: 'gpt-5-mini', latency_ms: 3500, prompt_tokens: 600, completion_tokens: 180 }),
    ]
    const messages = [
      message({ role: 'user', content: 'my vpn drops' }),
      message({
        role: 'assistant',
        step_index: 0,
        tool_calls: [{ id: 'x', name: 'search_knowledge_base', arguments: '{}' }],
      }),
      message({ role: 'tool', tool_name: 'search_knowledge_base', step_index: 1, content: '{}' }),
      message({ role: 'assistant', step_index: 2, content: 'Try reconnecting. (VPN troubleshooting)' }),
    ]
    const lines = buildLines({ ...base, messages, runs: [run({ steps })], approvals: [] })

    expect(lines.map((l) => l.kind)).toEqual(['user', 'model', 'tool', 'agent', 'total'])
    expect(lines[1].content).toBe('Decides to call search_knowledge_base')
    expect(lines[2].content).toBe('“vpn drops”')
    expect(lines[2].detail).toBe('2 passages from: VPN troubleshooting')
    expect(lines[3].durationMs).toBe(3500)
    expect(lines[3].tokens).toBe(780)
    expect(lines[3].scaleMs).toBe(3500) // bars share one scale per run
    expect(lines[4].durationMs).toBe(6000)
    expect(lines[4].cost).toBe('0.0021')
  })

  it('shows an unsigned approval as awaiting, then keeps it and adds the signature line once decided', () => {
    const steps = [
      step({ step_index: 0, kind: 'tool', name: 'reset_password', output: { approval_id: 'a1', status: 'pending_approval' } }),
    ]
    const messages = [
      message({ role: 'user', content: 'reset me' }),
      message({ role: 'tool', tool_name: 'reset_password', step_index: 0, content: '{}' }),
    ]
    const pending = buildLines({ ...base, messages, runs: [run({ steps })], approvals: [approval()] })
    const waiting = pending.find((l) => l.kind === 'approval')!
    expect(waiting.stamp).toBe('awaiting')
    expect(waiting.detail).toMatch(/support agent has to sign/)
    expect(pending.some((l) => l.kind === 'sign')).toBe(false)

    const signed = approval({
      status: 'approved',
      decided_by: 's1',
      decision_note: 'ok',
      decided_at: '2026-11-01T10:05:00.000000',
    })
    const lines = buildLines({ ...base, messages, runs: [run({ steps })], approvals: [signed] })
    expect(lines.find((l) => l.kind === 'approval')!.stamp).toBe('approved')
    const sign = lines.find((l) => l.kind === 'sign')!
    expect(sign.actor).toBe('Alice Nguyen')
    expect(sign.content).toContain('approved and carried out')
    expect(sign.content).toContain('“ok”')
  })

  it('keeps a rejected request on the page struck through and stamped, never removed', () => {
    const steps = [step({ step_index: 0, kind: 'tool', name: 'reset_password', output: { approval_id: 'a1' } })]
    const messages = [message({ role: 'tool', tool_name: 'reset_password', step_index: 0, content: '{}' })]
    const rejected = approval({ status: 'rejected', decided_by: 's1', decided_at: '2026-11-01T10:05:00.000000' })
    const lines = buildLines({ ...base, messages, runs: [run({ steps })], approvals: [rejected] })
    const line = lines.find((l) => l.kind === 'approval')!
    expect(line.struck).toBe(true)
    expect(line.stamp).toBe('rejected')
  })

  it('stamps a failed model call FAILED and offers the user text again', () => {
    const failing = step({ step_index: 0, kind: 'llm', name: 'gpt-5-mini', error: 'RuntimeError: provider down' })
    const messages = [
      message({ role: 'user', content: 'help' }),
      message({ role: 'assistant', step_index: 0, content: 'Sorry, something went wrong.' }),
    ]
    const lines = buildLines({ ...base, messages, runs: [run({ status: 'failed', steps: [failing] })], approvals: [] })
    const reply = lines.find((l) => l.kind === 'agent')!
    expect(reply.stamp).toBe('failed')
    expect(reply.retryText).toBe('help')
    expect(lines.at(-1)!.stamp).toBe('failed')
  })

  it('leaves out the totals line while a run is still going (the live line covers it)', () => {
    const messages = [message({ role: 'user', content: 'hello' })]
    const lines = buildLines({
      ...base,
      messages,
      runs: [run({ status: 'running', finished_at: null, steps: [] })],
      approvals: [],
    })
    expect(lines.map((l) => l.kind)).toEqual(['user'])
  })

  it('still prints messages that no run wrote (an approval follow-up)', () => {
    const lines = buildLines({
      ...base,
      messages: [message({ role: 'assistant', run_id: null, content: 'Your reset was approved.' })],
      runs: [],
      approvals: [],
    })
    expect(lines).toHaveLength(1)
    expect(lines[0].content).toBe('Your reset was approved.')
  })
})

describe('summarizeTool', () => {
  it('reports a tool error as a failed, struck line', () => {
    const view = summarizeTool('create_ticket', {}, null, 'boom', t)
    expect(view).toMatchObject({ stamp: 'failed', struck: true, content: 'boom' })
  })

  it('says plainly when the knowledge base had nothing relevant', () => {
    const view = summarizeTool('search_knowledge_base', { query: 'free pizza' }, { results: [] }, null, t)
    expect(view.detail).toBe('No relevant article found')
  })

  it('falls back to the arguments and the tool message', () => {
    const view = summarizeTool('check_system_status', { system_name: 'VPN' }, { message: 'VPN is operational' }, null, t)
    expect(view.content).toBe('VPN is operational')
    expect(view.detail).toBe('system_name: VPN')
  })

  it('leads with the result and unwraps the stored {arguments: json} input', () => {
    const view = summarizeTool(
      'check_system_status',
      { arguments: '{"system_name":"Email"}' },
      { status: 'operational', system: 'Email', last_updated: '2026-10-31T05:14:21' },
      null,
      t,
    )
    expect(view.content).toBe('Email: operational')
    expect(view.detail).toBe('system_name: Email')
  })

  it('does not print empty arguments or raw empty lists', () => {
    const view = summarizeTool('list_my_requests', { arguments: '{}' }, { requests: [] }, null, t)
    expect(view.content).toBe('requests: none')
    expect(view.detail).toBeUndefined()
  })
})

describe('helpers', () => {
  it('truncates on one line', () => {
    expect(truncate('a  b\nc', 10)).toBe('a b c')
    expect(truncate('x'.repeat(20), 10)).toHaveLength(10)
  })

  it('adds up tokens spent so far by a run in progress', () => {
    const r = run({
      status: 'running',
      steps: [
        step({ step_index: 0, kind: 'llm', name: 'm', prompt_tokens: 100, completion_tokens: 10 }),
        step({ step_index: 1, kind: 'tool', name: 't' }),
      ],
    })
    expect(tokensSoFar(r)).toBe(110)
    expect(tokensSoFar(undefined)).toBe(0)
  })
})
