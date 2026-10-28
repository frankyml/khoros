import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const PANE = {
  plugin: 'khoros-view',
  component: 'Pane',
  requestId: 'khoros',
  surface: 'terminal',
  props: {
    title: 'Khoros',
    isFocused: false,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

const BLOCK = {
  at: 1_700_000_000, outcome: 'block', attempt: 1, max: 3, files: 2, seconds: 1.5, violations: [],
  tests: [{ command: 'python3 -m unittest', status: 'failed' }], new: ['unittest: test_x.T.test_bad'], preexisting: [],
}

const STATE = '/repo/.git/khoros'

// A repo with Khoros set up and the gate loaded for session sid-1. Every hook here stands for the engine.
function repo(on: On, opts: { isKhoros?: boolean; runs?: object[] } = {}) {
  const files: Record<string, string> = { [`${STATE}/session-sid-1.json`]: '{}' }
  if (opts.isKhoros !== false) files['/repo/.harness/config.yaml'] = 'verify: {}\n'
  if (opts.runs) files[`${STATE}/runs-sid-1.json`] = JSON.stringify({ runs: opts.runs })
  const statuses: (string | undefined)[] = []
  const tools: string[] = []

  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 200_000 }, rateLimits: [] } }))
  on('process.run', (_, e) => {
    const cmd = e.argv.join(' ')
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '' } })
    if (cmd === 'git rev-parse --show-toplevel') return ok('/repo\n')
    if (cmd === 'git rev-parse --absolute-git-dir') return ok('/repo/.git\n')
    if (cmd === '/repo/bin/khoros status --json') {
      return ok(JSON.stringify({ tasks: [{ id: 't1', title: 'Do it', status: 'CLAIMED', owner: '@lead', deps: [] }] }))
    }
    return { value: { exitCode: 1, stdout: '', stderr: 'unexpected: ' + cmd } }
  })
  on('fs.exists', (_, e) => ({ value: e.path in files || e.path === '/repo/bin/khoros' }))
  on('fs.stat', (_, e) => {
    if (!(e.path in files)) throw new Error('ENOENT: ' + e.path)
    return { value: { kind: 'file', size: files[e.path]!.length, mtimeMs: 1, isLink: false } }
  })
  on('fs.read', (_, e) => {
    if (!(e.path in files)) throw new Error('ENOENT: ' + e.path)
    return { value: files[e.path]! }
  })
  on('fs.write', (_, e) => {
    files[e.path] = e.text
    return { value: undefined }
  })
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  on('ui.toast', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('command.register', () => ({ value: { command: 'khoros' } }))
  on('tool.register', (_, e) => {
    tools.push(e.name)
    return { value: { tool: 'mcp__khoros-view__' + e.name } }
  })
  mock.clock(on)
  mock.store(on)
  return { files, statuses, tools }
}

test('the status line and the Gate tab show a block read from the gate run log', async ($, on) => {
  const { statuses } = repo(on, { runs: [BLOCK] })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })

  expect(statuses.at(-1)).toBe('gate ✗ · 1 block')
  const ui = await $.ui.mount(PANE)
  expect((await ui.find({ type: 'Text', text: /blocked, attempt 1\/3/ }))).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /New failures: unittest: test_x/ }))).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /tests failed: python3 -m unittest/ }))).toBeDefined()
  await ui.unmount()
})

test('model usage adds up to tokens, cache hit rate and the cost estimate', async ($, on) => {
  const { statuses } = repo(on)
  on('turn.step', async function* (_, e) {
    return {
      turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn',
      usage: { model: 'm', input_tokens: 100, output_tokens: 100, cache_read_input_tokens: 800, cache_creation_input_tokens: 100 },
    }
  })
  on('session.measure', (_, e) => ({ changed: e.changed }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const step = $.turn.step({ turnId: 't', index: 0, model: 'm', messageCount: 1 })
  for await (const _ of step) {
    // drain the stream so the step finishes
  }
  await step.result
  await $.session.measure({ context: { window: 200_000, percent: 40 }, rateLimits: [], cost: { usd: 0.42 }, changed: ['cost'] })

  expect(statuses.at(-1)).toBe('gate idle · 1.1k tok · 80% cache · $0.42 est')
  const ui = await $.ui.mount(PANE)
  await $.ui.press({ plugin: 'khoros-view', requestId: 'khoros', key: 'tab-cost' })
  expect((await ui.find({ type: 'Text', text: /Cache hit rate: 80%/ }))).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /Cost: \$0\.42/ }))).toBeDefined()
  await ui.unmount()
})

test('the Claude tool reports recent gate runs and open tasks', async ($, on) => {
  const { tools } = repo(on, { runs: [BLOCK] })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })

  expect(tools).toEqual(['status'])
  const answer = await $.tool.call({ tool: 'mcp__khoros-view__status' })
  const state = JSON.parse(String(answer.result))
  expect(state.gate.recent[0].outcome).toBe('block')
  expect(state.gate.recent[0].new).toEqual(['unittest: test_x.T.test_bad'])
  expect(state.tasks[0].id).toBe('t1')
})

test('turning the gate off writes the per-session flag the gate reads', async ($, on) => {
  const { files, statuses } = repo(on, { runs: [BLOCK] })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount(PANE)
  await $.ui.press({ plugin: 'khoros-view', requestId: 'khoros', key: 'toggle' })

  expect(files[`${STATE}/off-sid-1.json`]).toBe('{"off":true}')
  expect(statuses.at(-1)).toBe('gate off · 1 block')
  expect((await ui.find({ type: 'Text', text: /Gate off for this session/ }))).toBeDefined()
  await ui.unmount()
})

test('outside a Khoros repo the mod adds no tool and no status line', async ($, on) => {
  const { statuses, tools } = repo(on, { isKhoros: false })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })

  expect(tools).toEqual([])
  expect(statuses.filter(s => s !== undefined)).toEqual([])
})
