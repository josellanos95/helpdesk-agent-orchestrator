import type { Approval, Message, Run, Step } from '../lib/types'

export const RUN_ID = 'run-1'

export function step(over: Partial<Step> & Pick<Step, 'step_index' | 'kind' | 'name'>): Step {
  return {
    input: null,
    output: null,
    latency_ms: 100,
    prompt_tokens: null,
    completion_tokens: null,
    error: null,
    ...over,
  }
}

export function run(over: Partial<Run> = {}): Run {
  return {
    id: RUN_ID,
    conversation_id: 'c1',
    status: 'completed',
    model: 'gpt-5-mini',
    prompt_tokens: 1000,
    completion_tokens: 200,
    cost_usd: '0.0021',
    error: null,
    started_at: '2026-11-01T10:00:00.000000',
    finished_at: '2026-11-01T10:00:06.000000',
    steps: [],
    ...over,
  }
}

let seq = 0
export function message(over: Partial<Message> & Pick<Message, 'role'>): Message {
  seq += 1
  return {
    id: `m${seq}`,
    seq,
    content: '',
    tool_name: null,
    tool_call_id: null,
    tool_calls: null,
    run_id: RUN_ID,
    step_index: null,
    created_at: `2026-11-01T10:00:0${Math.min(seq, 9)}.000000`,
    ...over,
  }
}

export function approval(over: Partial<Approval> = {}): Approval {
  return {
    id: 'a1',
    conversation_id: 'c1',
    requested_by: 'e1',
    requested_by_name: 'Marco Silva',
    tool_name: 'reset_password',
    arguments: { reason: 'I forgot my password' },
    status: 'pending',
    decided_by: null,
    decision_note: null,
    result: null,
    created_at: '2026-11-01T10:00:04.000000',
    expires_at: '2026-11-02T10:00:04.000000',
    decided_at: null,
    ...over,
  }
}

export function resetSeq() {
  seq = 0
}
