import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import {
  DEFAULT_ARCHITECT,
  DEFAULT_GATE,
  DEFAULT_TURN,
  afterCall,
  applyStep,
  consultTimeline,
  describeInput,
  endConsult,
  estimate,
  estimateLine,
  isStopping,
  normalizeStops,
  pressStop,
  stopApplies,
  stoppedStep,
  STOP_TEXT,
  fitLegend,
  gateSummary,
  lanes,
  limitLabel,
  logRows,
  momentOf,
  normalizeCard,
  normalizeGate,
  normalizeLog,
  titleLines,
  parseConfig,
  prettyModel,
  promptLine,
  handbackOf,
  adviceLine,
  receiptOf,
  recordCheck,
  redact,
  settleCheck,
  trimRecent,
  startConsult,
} from '../hooks/core'
import type { Check } from '../types'

// ---------------------------------------------------------------- pure behaviour


// The upstream defaults. The local plugin.json shows only the gate and agents and hides
// the header, the desktop time axis and card details; the upstream tests below pin
// the full pane, so they ask for upstream's settings explicitly.
const UPSTREAM = { panels: 'main,architect,gate,agents,loops,receipt,log', header: true, timeline: true, details: true }

test('redaction masks credentials before anything is stored', () => {
  expect(redact('curl -H "Authorization: Bearer abc.def.ghi123" x')).not.toContain('abc.def')
  expect(redact('export OPENAI_API_KEY=placeholder-not-a-key')).not.toContain('placeholder-not-a-key')
  expect(redact('gh auth --token ghp_abcdefghijklmnop')).not.toContain('abcdefghijklmnop')
  expect(redact('psql postgres://bob:hunter2@db/x')).not.toContain('hunter2') // pragma: allowlist secret
  expect(redact('password=hunter2 ls')).not.toContain('hunter2')
  expect(redact('ls -la src/')).toBe('ls -la src/')
  expect(describeInput('Read', { file_path: 'C:\\Users\\me\\proj\\src\\main.ts' })).toBe('Read → src/main.ts')
})

const check = (id: string, verdict: Check['verdict'], bucket: Check['bucket'] = 'shell'): Check => ({
  id,
  tool: 'Bash',
  bucket,
  verdict,
  inSubagent: false,
  detail: 'Bash → ls',
  at: 1,
})

test('an ask is settled by the call that follows: cleared if it ran, deny if refused', () => {
  let g = recordCheck(DEFAULT_GATE, check('a', 'ask'))
  g = recordCheck(g, check('b', 'ask'))
  g = recordCheck(g, check('c', 'rule', 'file'))
  g = settleCheck(g, 'a', true)
  g = settleCheck(g, 'b', false)
  g = settleCheck(g, 'zzz', true) // not an ask: unchanged
  const s = gateSummary(g)
  expect([s.rule, s.ask, s.cleared, s.deny, s.total]).toEqual([1, 0, 1, 1, 3])
  expect(g.recent.map(c => c.verdict)).toEqual(['cleared', 'deny', 'rule'])
})

test('the gate tallies a mixed run of verdicts per family', () => {
  let g = DEFAULT_GATE
  g = recordCheck(g, check('r1', 'rule', 'file'))
  g = recordCheck(g, check('a1', 'ask', 'shell'))
  g = recordCheck(g, check('a2', 'ask', 'shell'))
  g = recordCheck(g, check('d1', 'deny', 'other'))
  g = settleCheck(g, 'a1', true)
  g = settleCheck(g, 'a2', false)
  expect(g.totals.file).toEqual({ rule: 1, ask: 0, cleared: 0, deny: 0 })
  expect(g.totals.shell).toEqual({ rule: 0, ask: 0, cleared: 1, deny: 1 })
  expect(g.totals.other.deny).toBe(1)
  expect(gateSummary(g)).toEqual({ rule: 1, ask: 0, cleared: 1, deny: 2, total: 4 })
  expect(gateSummary(DEFAULT_GATE).total).toBe(0)
})

test('a v1-shaped gate reads as empty, then records normally', () => {
  const g = normalizeGate({ file: { allow: 3, ask: 1, deny: 0, cleared: 2 }, shell: null })
  expect(gateSummary(g).total).toBe(0)
  const next = recordCheck(g, check('n1', 'rule', 'file'))
  expect(next.totals.file.rule).toBe(1)
  expect(next.recent.length).toBe(1)
})

test('a pending ask is never trimmed out before it settles', () => {
  let g = recordCheck(DEFAULT_GATE, check('old-ask', 'ask'))
  for (let i = 0; i < 120; i += 1) g = recordCheck(g, check(`r${i}`, 'rule', 'file'))
  expect(g.recent.length).toBe(80)
  expect(g.recent.some(c => c.id === 'old-ask')).toBe(true)
  g = settleCheck(g, 'old-ask', true)
  expect(gateSummary(g).ask).toBe(0)
  expect(trimRecent([check('a', 'rule'), check('b', 'rule')], 5).length).toBe(2)
})

test('edits count from every loop; errors only from the main loop', () => {
  const t = { ...DEFAULT_TURN, errorStreak: 1 }
  expect(afterCall(t, { inSubagent: true, hasFailed: false, isEdit: true }).edits).toBe(1)
  expect(afterCall(t, { inSubagent: true, hasFailed: true, isEdit: false }).errorStreak).toBe(1)
  expect(afterCall(t, { inSubagent: false, hasFailed: true, isEdit: false })).toEqual({ ...t, errorStreak: 2, errors: 1 })
  expect(momentOf(afterCall(DEFAULT_TURN, { inSubagent: true, hasFailed: false, isEdit: true }))).toBe('before done')
  expect(momentOf({ edits: 0, errorStreak: 2 })).toBe('error repeats')
})

test("a card's context is its latest step's whole input; output adds up", () => {
  let c = normalizeCard({ id: 'x' })
  c = applyStep(c, { model: 'claude-sonnet-5-5', usage: { input_tokens: 10, cache_read_input_tokens: 30_000, cache_creation_input_tokens: 2_000, output_tokens: 500 }, stopReason: 'tool_use' })
  c = applyStep(c, { model: 'claude-sonnet-5-5', usage: { input_tokens: 5, cache_read_input_tokens: 40_000, output_tokens: 700 }, stopReason: 'max_tokens' })
  expect([c.ctx, c.out, c.steps, c.lastStop, c.model]).toEqual([40_005, 1200, 2, 'max_tokens', 'claude-sonnet-5-5'])
})

test('consults open, close by id, and draw on a shared timeline', () => {
  let a = startConsult(DEFAULT_ARCHITECT, { id: 's1', at: 0, moment: 'before a plan', via: 'advisor tool' })
  a = startConsult(a, { id: 's1', at: 5, moment: 'before a plan', via: 'again' }) // same id: ignored
  a = endConsult(a, 10, null, 's1')
  a = startConsult(a, { id: 's2', at: 90, moment: 'before done', via: 'advisor tool' })
  expect(a.consults.length).toBe(2)
  expect(a.consults[0]?.endAt).toBe(10)
  const tl = consultTimeline(a, 100, 11)
  expect(tl.length).toBe(11)
  expect(tl.startsWith('◆━')).toBe(true)
  expect(tl.split('◆').length - 1).toBe(2)
})

test('config is read leniently: bad values fall back to defaults', () => {
  const d = parseConfig({})
  expect([d.maxCards, d.layout, d.motion, d.moments, d.panels.length]).toEqual([3, 'auto', true, true, 7])
  expect(d.architect.test('fable-advisor:fable-advisor')).toBe(true)
  const c = parseConfig({ architectPattern: '([', maxCards: 99, layout: 'diagonal', panels: 'log, gate ,nope,gate', motion: 'off' })
  expect(c.architect.test('advisor')).toBe(true) // invalid regex → default
  expect([c.maxCards, c.layout, c.motion]).toEqual([6, 'auto', false])
  expect(c.panels).toEqual(['log', 'gate'])
})

test('state saved under an older shape still reads', () => {
  expect(normalizeLog([{ at: '08:00:00', who: 'jev', text: 'x' }])[0]).toEqual({ at: 0, who: 'jev', text: 'x', agentId: null, kind: 'info' })
  const g = normalizeGate({ file: { allow: 1 } }) // v1 gate shape
  expect(g.recent).toEqual([])
  expect(g.totals.shell.rule).toBe(0)
  expect(normalizeCard({ id: 'a', status: 'done' }).tools).toEqual([])
})

test('layout math: lanes share one axis, the log gets 4-8 rows, the legend never wraps', () => {
  const cards = [
    { ...normalizeCard({}), id: 'a', spawnedAt: 1000, endedAt: 1050 },
    { ...normalizeCard({}), id: 'b', spawnedAt: 1050, endedAt: null },
  ]
  const [a, b] = lanes(cards, 1100, 20)
  expect(a).toEqual({ id: 'a', before: 0, bar: 10, after: 10 })
  expect(b?.before).toBe(10)
  expect((b?.before ?? 0) + (b?.bar ?? 0) + (b?.after ?? 0)).toBe(20)
  expect([logRows(10, 40), logRows(50, 40), logRows(200, 40)]).toEqual([4, 7, 8])
  expect(fitLegend([{ label: 'main' }, { label: 'agents' }, { label: 'architect' }], 20).map(x => x.label)).toEqual(['main', 'agents'])
  expect(limitLabel('five_hour')).toBe('5h')
  expect(prettyModel('claude-opus-5-5[1m]')).toBe('Opus 5.5 1M')
  expect(prettyModel('us.anthropic.claude-sonnet-4-5-20250929-v1:0')).toBe('Sonnet 4.5')
  expect(prettyModel('claude-3-5-haiku-20241022')).toBe('Haiku 3.5')
  expect(prettyModel('claude-opus-4-20250514')).toBe('Opus 4')
  expect(prettyModel('claude-3-opus-20240229')).toBe('Opus 3')
  expect(prettyModel('z-ai/glm-5.3-flash-with-a-long-name')).toBe('z-ai/glm-5.3-flash-wi…')
  expect(prettyModel('')).toBe('—')
  expect(promptLine('fix the parser')).toEqual({ who: 'you', text: 'fix the parser' })
  const hb = '<agent-message from="a1940a83d593229d5">\n[Subagent hand-back] The text below is the final report. The report follows:\n  Add gate tests: redaction edge cases.\n  - more\n</agent-message>'
  expect(handbackOf(hb)).toEqual({ from: 'a1940a83d593229d5', body: 'Add gate tests: redaction edge cases.' })
  expect(handbackOf('<agent-message from="x">\nPlain report line\n</agent-message>')).toEqual({ from: 'x', body: 'Plain report line' })
  expect(handbackOf('fix the parser')).toBe(null)
  expect(adviceLine('## Ship it after one more gate test.\n- details')).toBe('Ship it after one more gate test.')
  expect(adviceLine('[Subagent hand-back] header\n\n**Fix card overflow first**')).toBe('Fix card overflow first')
  expect(adviceLine('')).toBe('')
  expect(promptLine('<agent-message from="a1492260715f3be7b"> [Subagent hand-back]')).toEqual({ who: 'engine', text: 'agent message from a1492260' })
  expect(receiptOf({ ...DEFAULT_TURN, costAtStart: 5 }, { durationMs: 1, agentsSince: 0, costNow: 5, reason: 'answer' }).costDelta).toBe(null)
  expect(titleLines('Write tinyqueue test suite', 13, 16)).toEqual(['Write', 'tinyqueue test…'])
  expect(titleLines('Short', 13, 16)).toEqual(['Short', ''])
  expect(receiptOf({ ...DEFAULT_TURN, costAtStart: 1, edits: 2 }, { durationMs: 1000, agentsSince: 3, costNow: 1.5, reason: 'answer' }).costDelta).toBe(0.5)
})

// ---------------------------------------------------------------- drawing

const engine = (on: On, now?: number) => {
  const clock = mock.clock(on, now === undefined ? undefined : { now })
  on('ui.status', () => ({ value: undefined }))
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  return clock
}

const pane = (bodyColumns: number) => ({
  plugin: 'flightdeck',
  component: 'Pane' as const,
  requestId: 'flightdeck',
  props: {
    title: 'Flightdeck',
    isFocused: true,
    bodyColumns,
    placement: 'dock' as const,
    scroll: { offset: 0, bodyRows: 70 },
    view: {},
  },
})

let spawnN = 0
const spawn = (subagentType: string, description: string) => ({
  prompt: description,
  description,
  subagentType,
  tool_use_id: `tu${++spawnN}`,
  provider: { plugin: 'engine', tier: 'core' as const },
  parentModel: 'claude-opus-5-5',
  background: true,
  fork: false,
})

test('a fresh session draws on every surface and width, empty panels hidden', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    for (const cols of [40, 60, 86, 120]) {
      const ui = await $.ui.mount({ ...pane(cols), surface })
      expect(await ui.find({ text: /· main$/ })).toBeDefined()
      expect(await ui.find({ text: /session log/ })).toBeDefined()
      expect(await ui.find({ text: /agents ·/ })).toBeUndefined() // no subagents: no agents panel
      expect(await ui.find({ text: /permissions/ })).toBeUndefined() // no checks yet: no gate panel
      await ui.unmount()
    }
  }
})

test('inline above the prompt, the pane is a summary of at most 8 rows', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `m${++n}` }))
  on('tool.check', () => ({ decision: 'allow' }))
  await $.turn.start({ text: 'go', turnId: 'M1' })
  for (const d of ['one', 'two', 'three', 'four', 'five']) await $.agent.spawn(spawn('general-purpose', `task ${d}`))
  await $.tool.check({ tool: 'Read', input: { file_path: '/a' }, tool_use_id: 'm-k1' })
  for (const surface of ['terminal', 'vscode'] as const) {
    const ui = await $.ui.mount({ ...pane(80), props: { ...pane(80).props, placement: 'inline' as const }, surface })
    const root = (await ui.drawn()) as { children?: unknown[] }
    expect((root.children ?? []).filter(Boolean).length <= 8).toBe(true)
    expect(await ui.find({ text: /\+2 more agents/ })).toBeDefined()
    expect(await ui.find({ text: /1 allowed/ })).toBeDefined()
    expect(await ui.find({ text: /session log/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('/clear starts the pane fresh', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'c1' }))
  await $.turn.start({ text: 'go', turnId: 'C1' })
  await $.agent.spawn(spawn('Explore', 'look around'))
  await $.session.end({ reason: 'clear', sessionId: 's' } as never)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await ui.find({ text: /look around/ })).toBeUndefined()
  await ui.unmount()
})

test('colours come from the theme by default, raw hex only when asked', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  const title = await ui.find({ text: /· main$/ })
  expect(title?.props.color).toBe('claude')
  await ui.unmount()
})

test('pastel keeps the fixed dark-terminal colours', { options: { ...UPSTREAM, palette: 'pastel' } }, async ($, on) => {
  engine(on)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect((await ui.find({ text: /· main$/ }))?.props.color).toBe('#7dd3fc')
  await ui.unmount()
})

test('subagents become cards, then swimlanes past the card limit; a card expands on its hotkey', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `ag${++n}` }))
  await $.turn.start({ text: 'fan out', turnId: 'T1' })
  await $.agent.spawn(spawn('general-purpose', 'Write the parser tests'))
  await $.agent.spawn(spawn('Explore', 'Map the call sites'))

  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await ui.find({ text: /Write the parser/ })).toBeDefined()
  expect(await ui.find({ text: /Sonnet 5\.5/ })).toBeDefined() // differs from main: shown
  await ui.press({ key: 'card-ag1' })
  expect(await ui.find({ text: /^Write the parser tests$/ })).toBeDefined() // the expanded panel, full title
  await ui.unmount()

  await $.agent.spawn(spawn('general-purpose', 'Implement the parser'))
  await $.agent.spawn(spawn('general-purpose', 'Review the parser'))
  for (const surface of ['terminal', 'desktop'] as const) {
    const lanesUi = await $.ui.mount({ ...pane(64), surface })
    expect(await lanesUi.find({ text: /4 total/ })).toBeDefined()
    expect(await lanesUi.find({ text: /━/ })).toBeDefined()
    await lanesUi.unmount()
  }
})

test('the server-side advisor is read from assistant rows: consulting, then on call', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  await $.turn.start({ text: 'plan it', turnId: 'T2' })
  const row = (content: unknown[]) =>
    $.session
      .append({
        message: { type: 'assistant', role: 'assistant', content: content as never },
        door: 'response',
        origin: { kind: 'model', model: 'claude-opus-5-5' } as never,
        uuid: `u${++spawnN}`,
      })
      .catch(() => undefined) // the test has no transcript to store rows in
  await row([{ type: 'server_tool_use', id: 'srv1', name: 'advisor', input: {} }])
  const mid = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await mid.find({ text: /ARCHITECT · advising/ })).toBeDefined()
  expect(await mid.find({ text: /◆ before a plan/ })).toBeDefined()
  await mid.unmount()

  await row([{ type: 'advisor_tool_result', tool_use_id: 'srv1', content: { type: 'advisor_redacted_result' } }])
  const after = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await after.find({ text: /ARCHITECT · on call/ })).toBeDefined()
  expect(await after.find({ text: /^1$/ })).toBeDefined()
  await after.unmount()
})

test('the gate strip fills from checks and a row opens its redacted drill-down', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  on('tool.check', (_$, e) => ({ decision: e.tool === 'Read' ? 'allow' : 'ask' }))
  await $.tool.check({ tool: 'Read', input: { file_path: '/a/b.ts' }, tool_use_id: 'k1' })
  await $.tool.check({ tool: 'Bash', input: { command: 'curl -H "Authorization: Bearer abcdefgh12345" api' }, tool_use_id: 'k2' })
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await ui.find({ text: /2 checks/ })).toBeDefined()
  expect(await ui.find({ text: /1 pending/ })).toBeDefined()
  await ui.press({ key: 'gate-shell' })
  expect(await ui.find({ text: /Authorization: Bearer •••/ })).toBeDefined()
  expect(await ui.find({ text: /abcdefgh12345/ })).toBeUndefined()
  await ui.unmount()
})

test('config changes labels, hides panels and turns the moments off', { options: { ...UPSTREAM, architectLabel: 'REVIEWER', panels: 'main,architect,agents,log', moments: false } }, async ($, on) => {
  engine(on)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-fable-5-1', agentId: `r${++n}` }))
  await $.turn.start({ text: 'review it', turnId: 'T3' })
  await $.agent.spawn(spawn('fable-advisor:fable-advisor', 'final review'))
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await ui.find({ text: /REVIEWER · advising/ })).toBeDefined()
  expect(await ui.find({ text: /permissions/ })).toBeUndefined()
  expect(await ui.find({ text: /before a plan/ })).toBeUndefined()
  await ui.unmount()
})

test('a consult whose start and result share one row closes, and its review flag with it', { options: UPSTREAM }, async ($, on) => {
  engine(on)
  on('tool.call', () => ({ result: {}, text: 'ok' }))
  await $.turn.start({ text: 'go', turnId: 'T4' })
  // An edit first, so the consult is inferred as "before done" and sets the review flag.
  await $.tool.call({ tool: 'Edit', file_path: '/x.ts', old_string: 'a', new_string: 'b' } as never)
  await $.session
    .append({
      message: {
        type: 'assistant',
        role: 'assistant',
        content: [
          { type: 'server_tool_use', id: 'srv9', name: 'advisor', input: {} },
          { type: 'advisor_tool_result', tool_use_id: 'srv9', content: { type: 'advisor_redacted_result' } },
        ] as never,
      },
      door: 'response',
      origin: { kind: 'model', model: 'claude-opus-5-5' } as never,
      uuid: 'one-row',
    })
    .catch(() => undefined)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await ui.find({ text: /ARCHITECT · on call/ })).toBeDefined()
  expect(await ui.find({ text: /◆ before done/ })).toBeDefined()
  expect(await ui.find({ text: /reviewing before done/ })).toBeUndefined()
  await ui.unmount()
})

test('with no architect anywhere, the panel, legend entry and status field stay hidden', async ($, on) => {
  engine(on)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await ui.find({ text: /ARCHITECT/ })).toBeUndefined()
  expect(await ui.find({ text: /^ architect$/ })).toBeUndefined()
  await ui.unmount()
})

test('cards that cannot fit the pane fall back to lanes', async ($, on) => {
  engine(on)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-opus-5-5', agentId: `w${++n}` }))
  await $.turn.start({ text: 'go', turnId: 'W1' })
  for (const d of ['alpha', 'beta', 'gamma']) await $.agent.spawn(spawn('Explore', `task ${d}`))
  const narrow = await $.ui.mount({ ...pane(40), surface: 'terminal' })
  expect(await narrow.find({ text: /━/ })).toBeDefined() // lanes
  await narrow.unmount()
  const wide = await $.ui.mount({ ...pane(70), surface: 'terminal' })
  expect(await wide.find({ text: /━/ })).toBeUndefined() // three cards fit in 70
  expect(await wide.find({ text: /task gamma/ })).toBeDefined()
  await wide.unmount()
})

test("a background architect's advice is read from its hand-back", { options: UPSTREAM }, async ($, on) => {
  engine(on)
  on('agent.spawn', () => ({ model: 'claude-fable-5-1', agentId: 'fab1' }))
  await $.turn.start({ text: 'review it', turnId: 'H1' })
  await $.agent.spawn(spawn('fable-advisor:fable-advisor', 'final review'))
  await $.turn.complete({ answer: '', durationMs: 10, isAborted: false, turnId: 'H1', agentId: 'fab1', reason: 'answer' })
  await $.turn.start({
    text: '<agent-message from="fab1">\n[Subagent hand-back] The report follows:\n  Ship it after one more gate test.\n</agent-message>',
    turnId: 'H2',
  })
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  expect(await ui.find({ text: /» Ship it after one more gate test\./ })).toBeDefined()
  await ui.unmount()
})

const must = (ok: boolean, what: string) => {
  if (!ok) throw new Error(`expected: ${what}`)
}

test("The local defaults show only the gate and the agents, with card details on a click", async ($, on) => {
  engine(on)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `f${++n}` }))
  await $.turn.start({ text: 'fan out', turnId: 'T9' })
  await $.agent.spawn(spawn('general-purpose', 'Write the parser tests'))
  await $.agent.spawn(spawn('Explore', 'Map the call sites'))

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...pane(64), surface })
    must(await ui.find({ text: /Write the parser/ }) !== undefined, `agents shown on ${surface}`)
    must(await ui.find({ text: 'FLIGHTDECK' }) === undefined, `no header on ${surface}`)
    must(await ui.find({ text: /· main$/ }) === undefined, `no main panel on ${surface}`)
    must(await ui.find({ text: /session log/ }) === undefined, `no log on ${surface}`)
    must(await ui.find({ type: 'Svg' }) === undefined, `no desktop time axis on ${surface}`)
    await ui.press({ key: 'card-f1' })
    must(await ui.find({ text: / steps$/ }) !== undefined, `detail panel opens on ${surface}`)
    await ui.press({ key: 'card-f1' })
    must(await ui.find({ text: / steps$/ }) === undefined, `detail panel closes on ${surface}`)
    await ui.unmount()
  }
})

test('with details off, a card hotkey opens nothing', { options: { details: false } }, async ($, on) => {
  engine(on)
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'd1' }))
  await $.turn.start({ text: 'one', turnId: 'T10' })
  await $.agent.spawn(spawn('general-purpose', 'Write the parser tests'))
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  await ui.press({ key: 'card-d1' })
  must(await ui.find({ text: / steps$/ }) === undefined, 'no detail panel')
  must(await ui.find({ text: /expand$/ }) === undefined, 'no expand hint')
  await ui.unmount()
})

test('every agent gets a lane, and one past the ninth still opens its details', { options: { details: true } }, async ($, on) => {
  engine(on)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `l${++n}` }))
  await $.turn.start({ text: 'many', turnId: 'T11' })
  for (let i = 1; i <= 14; i++) await $.agent.spawn(spawn('general-purpose', `Task number ${i}`))
  const ui = await $.ui.mount({ ...pane(80), surface: 'terminal' })
  must(await ui.find({ text: /earlier/ }) === undefined, 'no agents hidden as earlier')
  for (const i of [1, 6, 7, 14]) must(await ui.find({ text: new RegExp(`Task number ${i}$`) }) !== undefined, `lane ${i} shown`)
  await ui.press({ key: 'card-l12' })
  must(await ui.find({ text: / steps$/ }) !== undefined, 'lane 12 opens its details')
  await ui.unmount()
})

// ---------------------------------------------------------------- estimate and soft stop

type Card = ReturnType<typeof normalizeCard>
const card = (id: string, o: Partial<Card> = {}): Card => ({
  ...normalizeCard({}),
  id,
  type: 'Explore',
  model: 'claude-sonnet-5-5',
  spawnedAt: 1_000_000,
  ...o,
})
const doneIn = (id: string, ms: number, o: Partial<Card> = {}) => card(id, { status: 'done', spawnedAt: 1_000_000, endedAt: 1_000_000 + ms, ...o })

test('the estimate is the median of done agents of the same type and model', () => {
  const now = 1_000_000 + 30_000
  const run = card('r')
  // odd count: 60, 90, 120 -> 90
  const odd = estimate(run, [run, doneIn('a', 60_000), doneIn('b', 120_000), doneIn('c', 90_000)], now)
  expect([odd.typical, odd.n, odd.elapsed, odd.left]).toEqual([90_000, 3, 30_000, 60_000])
  expect(estimateLine(odd, 'Explore')).toBe('0:30 elapsed · about 1:00 left (typical 1:30 from 3 earlier Explore agents)')
  // even count: 60, 90, 120, 150 -> 105
  const even = estimate(run, [run, doneIn('a', 60_000), doneIn('b', 120_000), doneIn('c', 90_000), doneIn('d', 150_000)], now)
  expect([even.typical, even.n]).toEqual([105_000, 4])
  // under three comparables: no estimate
  const few = estimate(run, [run, doneIn('a', 60_000), doneIn('b', 120_000)], now)
  expect([few.typical, few.left, few.n]).toEqual([null, null, 2])
  expect(estimateLine(few, 'Explore')).toBe('0:30 elapsed · no estimate yet')
  // overrun
  const late = estimate(run, [doneIn('a', 10_000), doneIn('b', 20_000), doneIn('c', 15_000)], now)
  expect(late.left).toBe(null)
  expect(estimateLine(late, 'Explore')).toBe('0:30 elapsed · running longer than usual (typical 0:15)')
  // mismatched type or model, failed or running cards: not comparable
  const mixed = estimate(
    run,
    [doneIn('a', 60_000, { type: 'Plan' }), doneIn('b', 60_000, { model: 'claude-opus-5-5' }), doneIn('c', 60_000, { status: 'failed' }), card('d'), doneIn('e', 60_000)],
    now,
  )
  expect(mixed.n).toBe(1)
})

test('a finished card reports what it took, never counting itself', () => {
  const self = doneIn('self', 45_000)
  expect(estimateLine(estimate(self, [self, doneIn('a', 60_000)], 9e9), 'Explore')).toBe('took 0:45')
  const withThree = estimate(self, [self, doneIn('a', 60_000), doneIn('b', 60_000), doneIn('c', 90_000)], 9e9)
  expect([withThree.n, withThree.typical]).toEqual([3, 60_000])
  expect(estimateLine(withThree, 'Explore')).toBe('took 0:45 (typical 1:00)')
  const failed = card('f', { status: 'failed', endedAt: 1_000_000 + 5_000 })
  expect(estimateLine(estimate(failed, [], 9e9), 'Explore')).toBe('took 0:05')
})

test('the soft stop never matches the main loop and answers a stopped step with end_turn', () => {
  expect(isStopping(['a1'], 'a1')).toBe(true)
  expect(isStopping(['a1'], 'a2')).toBe(false)
  expect(isStopping(['a1', ''], undefined)).toBe(false)
  expect(isStopping([''], '')).toBe(false)
  const s = stoppedStep({ turnId: 't', index: 4 })
  expect(s.chunks).toEqual([
    { kind: 'text', index: 0, text: STOP_TEXT },
    { kind: 'stop', stopReason: 'end_turn', usage: null },
  ])
  expect(s.result).toEqual({ turnId: 't', index: 4, answer: STOP_TEXT, toolUses: [], stopReason: 'end_turn', usage: null })
})

const T0 = 1_000_000

/** A step's stream read to its end: the chunks it yielded and the result it returned. */
const drain = async <C, R>(stream: AsyncGenerator<C, R>) => {
  const chunks: C[] = []
  for (;;) {
    const r = await stream.next()
    if (r.done) return { chunks, result: r.value }
    chunks.push(r.value)
  }
}

test('the detail card estimates a running agent from three earlier ones of its kind', async ($, on) => {
  const clock = engine(on, T0)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `e${++n}` }))
  await $.turn.start({ text: 'fan out', turnId: 'E1' })
  for (const ms of [60_000, 120_000, 90_000]) {
    await $.agent.spawn(spawn('Explore', `earlier ${ms}`))
    await clock.advance(ms)
    await $.turn.complete({ answer: 'ok', durationMs: ms, isAborted: false, turnId: 'E1', agentId: `e${n}`, reason: 'answer' })
  }
  await $.agent.spawn(spawn('Explore', 'the running one'))
  await clock.advance(30_000)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  await ui.press({ key: 'card-e4' })
  must(await ui.find({ text: '0:30 elapsed · about 1:00 left (typical 1:30 from 3 earlier Explore agents)' }) !== undefined, 'eta line')
  must(await ui.find({ key: 'stop-e4' }) !== undefined, 'Stop on a running card')
  await ui.press({ key: 'card-e3' })
  must(await ui.find({ text: 'took 1:30' }) !== undefined, 'a done card shows what it took (two comparables besides itself)')
  must(await ui.find({ key: 'stop-e3' }) === undefined, 'no Stop on a done card')
  await ui.unmount()
})

test('with fewer than three earlier agents there is no estimate yet', async ($, on) => {
  const clock = engine(on, T0)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `q${++n}` }))
  await $.turn.start({ text: 'go', turnId: 'Q1' })
  await $.agent.spawn(spawn('Explore', 'earlier'))
  await clock.advance(60_000)
  await $.turn.complete({ answer: 'ok', durationMs: 1, isAborted: false, turnId: 'Q1', agentId: 'q1', reason: 'answer' })
  await $.agent.spawn(spawn('Explore', 'now'))
  await clock.advance(5_000)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  await ui.press({ key: 'card-q2' })
  must(await ui.find({ text: '0:05 elapsed · no estimate yet' }) !== undefined, 'no estimate yet')
  await ui.unmount()
})

test('Stop soft-stops one agent: its calls are denied, its next step ends the turn, main is untouched', { options: UPSTREAM }, async ($, on) => {
  engine(on, T0)
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'x1' }))
  on('tool.call', () => ({ result: {}, text: 'ok' }))
  let modelCalls = 0
  on('turn.step', async function* (_$, e) {
    modelCalls += 1
    yield { kind: 'text' as const, index: 0, text: 'model' }
    return { turnId: e.turnId, index: e.index, answer: 'model', toolUses: [], stopReason: 'end_turn' as const, usage: null }
  })
  await $.turn.start({ text: 'go', turnId: 'X1' })
  await $.agent.spawn(spawn('general-purpose', 'Long job'))
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  await ui.press({ key: 'card-x1' })
  must(await ui.find({ text: 'A command already running finishes before the agent stops.' }) !== undefined, 'limitation shown')
  await ui.press({ key: 'stop-x1' })
  must(await ui.find({ text: 'stop requested' }) !== undefined, 'stop logged')

  // The stopped agent's tool call is refused before it runs.
  const sub = await $.tool.call({ tool: 'Bash', command: 'ls', agentId: 'x1' } as never)
  expect(sub.deny).toBe('The user stopped this agent from flightdeck. Do not continue; end your turn now.')
  must(await ui.find({ key: 'stop-x1' }) === undefined, 'Stop gone once pressed')
  must(await ui.find({ text: 'stopping…' }) !== undefined, 'card says stopping…')

  // The main loop's tool call still runs while an agent is stopping.
  const mainCall = await $.tool.call({ tool: 'Bash', command: 'ls' } as never)
  expect(mainCall.deny).toBe(undefined)

  // The subagent's next request never reaches the model; the main loop's does.
  const { chunks, result } = await drain($.turn.step({ turnId: 'X1', index: 3, model: 'claude-sonnet-5-5', messageCount: 5, agentId: 'x1' }))
  expect(modelCalls).toBe(0)
  expect(result.answer).toBe('Stopped by the user from flightdeck.')
  expect([result.stopReason, result.usage, result.toolUses.length]).toEqual(['end_turn', null, 0])
  expect(chunks.length).toBe(2)
  const mainStep = await drain($.turn.step({ turnId: 'X1', index: 0, model: 'claude-opus-5-5', messageCount: 1 }))
  expect(mainStep.result.answer).toBe('model')
  expect(modelCalls).toBe(1)

  // Its run completes: the entry clears and the card reads stopped, with no Stop.
  await $.turn.complete({ answer: 'Stopped by the user from flightdeck.', durationMs: 1, isAborted: false, turnId: 'X1', agentId: 'x1', reason: 'answer' })
  must(await ui.find({ text: /· stopped ·/ }) !== undefined, 'detail card shows stopped')
  // The stopping entry is gone: a later step under that id reaches the model again.
  await drain($.turn.step({ turnId: 'X2', index: 0, model: 'claude-sonnet-5-5', messageCount: 1, agentId: 'x1' }))
  expect(modelCalls).toBe(2)
  must(await ui.find({ key: 'stop-x1' }) === undefined, 'no Stop on a stopped card')
  await ui.unmount()
})

// ---------------------------------------------------------------- regression: no stop without a press

test('agents running past the typical time are never stopped without a press', { options: UPSTREAM }, async ($, on) => {
  const clock = engine(on, T0)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `g${++n}` }))
  on('tool.call', () => ({ result: {}, text: 'ok' }))
  let modelCalls = 0
  on('turn.step', async function* (_$, e) {
    modelCalls += 1
    yield { kind: 'text' as const, index: 0, text: 'model' }
    return { turnId: e.turnId, index: e.index, answer: 'model', toolUses: [], stopReason: 'tool_use' as const, usage: null }
  })
  const step = (agentId: string, index: number) =>
    drain($.turn.step({ turnId: 'G1', index, model: 'claude-sonnet-5-5', messageCount: index + 1, agentId }))
  const bash = (agentId: string, i: number) => $.tool.call({ tool: 'Bash', command: `sleep 10 # ${i}`, agentId, tool_use_id: `${agentId}-b${i}` } as never)

  await $.turn.start({ text: 'three short ones', turnId: 'G1' })
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  // Three short agents: two Bash calls each, about 27 s, then their answer.
  for (const d of ['one', 'two', 'three']) await $.agent.spawn(spawn('general-purpose', `short ${d}`))
  for (let i = 0; i < 2; i++) {
    for (const id of ['g1', 'g2', 'g3']) {
      expect((await step(id, i)).result.answer).toBe('model')
      expect((await bash(id, i)).deny).toBe(undefined)
    }
    await clock.advance(12_000)
  }
  await clock.advance(3_000)
  for (const id of ['g1', 'g2', 'g3']) {
    await step(id, 2)
    await $.turn.complete({ answer: 'done', durationMs: 27_000, isAborted: false, turnId: 'G1', agentId: id, reason: 'answer' })
  }

  // Four long agents of the same type and model, each making 18 ten-second calls, watched in
  // the detail card as they pass the typical time. Nobody presses Stop.
  const long = ['g4', 'g5', 'g6', 'g7']
  for (const d of ['four', 'five', 'six', 'seven']) await $.agent.spawn(spawn('general-purpose', `long ${d}`))
  await ui.press({ key: 'card-g4' })
  const before = modelCalls
  for (let i = 0; i < 18; i++) {
    for (const id of long) {
      const s = await step(id, i)
      must(s.result.answer === 'model', `${id} step ${i} reached the model (got ${JSON.stringify(s.result.answer)})`)
      must(!s.chunks.some(c => (c as { text?: string }).text === STOP_TEXT), `${id} step ${i} has no stopped text`)
      const r = await bash(id, i)
      must(r.deny === undefined, `${id} call ${i} not denied (got ${JSON.stringify(r.deny)})`)
    }
    await clock.advance(10_000)
    // The detail card's estimate moves past typical (the drawing redraws on the next write).
    if (i === 4) {
      const texts: string[] = []
      const walk = (x: unknown) => {
        if (typeof x === 'string') texts.push(x)
        else if (Array.isArray(x)) x.forEach(walk)
        else if (x && typeof x === 'object') {
          const o = x as { children?: unknown; props?: { children?: unknown } }
          walk(o.children)
          walk(o.props?.children)
        }
      }
      walk(await ui.drawn())
      must(texts.some(t => /running longer than usual/.test(t)), `the overrun line is drawn: ${texts.filter(t => /elapsed|took|steps/.test(t)).join(' | ')}`)
    }
  }
  expect(modelCalls - before).toBe(18 * long.length)
  must(await ui.find({ text: 'stopping…' }) === undefined, 'no card reads stopping…')
  must(await ui.find({ text: 'stop requested' }) === undefined, 'no stop logged')
  await ui.unmount()
})

test('a stop applies only to the exact id pressed, on a card running since before the press', () => {
  const run = (id: string, o: Partial<Card> = {}) => card(id, { type: 'general-purpose', spawnedAt: T0, ...o })
  const cards = [run('a1'), run('a2'), run('a10'), run('done', { status: 'done', endedAt: T0 + 5 })]
  const stops = pressStop([], cards[0], T0 + 100)
  expect(stops).toEqual([{ id: 'a1', at: T0 + 100 }])
  expect(stopApplies(stops, cards, 'a1')).toBe(true)
  for (const other of ['a2', 'a10', 'a', '', undefined, null]) expect(stopApplies(stops, cards, other)).toBe(false)
  // A press on a card that is not running is not recorded; a recorded one stops applying once it ends.
  expect(pressStop([], cards[3], T0 + 100)).toEqual([])
  expect(pressStop([], undefined, T0 + 100)).toEqual([])
  expect(stopApplies([{ id: 'done', at: T0 + 1 }], cards, 'done')).toBe(false)
  // A press older than the card's run (an id used again by a resumed or new run) does not apply.
  expect(stopApplies([{ id: 'a2', at: T0 - 1 }], cards, 'a2')).toBe(false)
  // No card under the id: nothing to stop.
  expect(stopApplies([{ id: 'ghost', at: T0 + 1 }], cards, 'ghost')).toBe(false)
  // 0.3.2-local.2 stored bare ids with no press time: they are dropped.
  expect(normalizeStops(['a1', 'a2', { id: 'a2' }, { id: '', at: 1 }, null, { id: 'a3', at: 7 }])).toEqual([{ id: 'a3', at: 7 }])
  expect(normalizeStops('a1')).toEqual([])
})

test('Stop on one of four running agents of one type stops that one alone', { options: UPSTREAM }, async ($, on) => {
  const clock = engine(on, T0)
  let n = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `s${++n}` }))
  on('tool.call', () => ({ result: {}, text: 'ok' }))
  on('turn.step', async function* (_$, e) {
    yield { kind: 'text' as const, index: 0, text: 'model' }
    return { turnId: e.turnId, index: e.index, answer: 'model', toolUses: [], stopReason: 'tool_use' as const, usage: null }
  })
  await $.turn.start({ text: 'go', turnId: 'S1' })
  for (const d of ['one', 'two', 'three', 'four']) await $.agent.spawn(spawn('general-purpose', `long ${d}`))
  await clock.advance(20_000)
  const ui = await $.ui.mount({ ...pane(64), surface: 'terminal' })
  await ui.press({ key: 'card-s2' })
  await ui.press({ key: 'stop-s2' })
  for (const id of ['s1', 's2', 's3', 's4']) {
    const s = await drain($.turn.step({ turnId: 'S1', index: 2, model: 'claude-sonnet-5-5', messageCount: 3, agentId: id }))
    const r = await $.tool.call({ tool: 'Bash', command: 'sleep 10', agentId: id, tool_use_id: `${id}-c` } as never)
    const isStopped = id === 's2'
    must((s.result.answer === STOP_TEXT) === isStopped, `${id} step ${isStopped ? 'stopped' : 'reached the model'}`)
    must((r.deny !== undefined) === isStopped, `${id} call ${isStopped ? 'denied' : 'ran'}`)
  }
  await ui.unmount()
})
