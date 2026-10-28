import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ActionView, GateRun, GateView, SessionRecord, Tab, Task, TasksView, UsageView } from '../types'

// Khoros view: draws what the Khoros harness does in this session. The gate itself stays in the
// shell hooks (bin/khoros-gate); this mod reads the state they write and never blocks anything.

const PANE = 'khoros'
const TOOL = 'mcp__khoros-view__status'
const HISTORY_KEPT = 100
const ACTION_TIMEOUT_MS = 300_000

const gate = atom({ plugin: 'khoros-view', key: 'gate' } as const,
  { isKhoros: false, isActive: false, isOff: false, runs: [] } as GateView, { shape: 'gate-1' })
const usage = atom({ plugin: 'khoros-view', key: 'usage' } as const,
  { requests: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } as UsageView, { shape: 'usage-1' })
const tasks = atom({ plugin: 'khoros-view', key: 'tasks' } as const, { tasks: [] } as TasksView, { shape: 'tasks-1' })
const action = atom({ plugin: 'khoros-view', key: 'action' } as const, {} as ActionView, { shape: 'action-1' })
const tab = atom({ plugin: 'khoros-view', key: 'tab' } as const, 'gate' as Tab, { shape: 'tab-1' })
const history = atom({ plugin: 'khoros-view', key: 'history' } as const, [] as SessionRecord[], { shape: 'history-1' })

// Where this session's repo and gate state live; recomputed at every (re)load.
type Ctx = { root: string; stateDir: string; session: string; sessionId: string; bin: string; startedAt: number }
let ctx: Ctx | undefined
let runsMtime = -1

// ------------------------------------------------------------------ helpers

const safeName = (s: string) => s.replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 80) // as bin/khoros-gate names files

function parseJson(text: string): any {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

function k(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k'
  return String(n)
}

function clock(atSeconds: number): string {
  const d = new Date(atSeconds * 1000)
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
}

function day(ms: number): string {
  const d = new Date(ms)
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
}

const totalTokens = (u: UsageView) => u.input + u.output + u.cacheRead + u.cacheWrite

function cacheHit(u: UsageView): number | undefined {
  const prompt = u.input + u.cacheRead + u.cacheWrite
  return prompt > 0 ? Math.round((100 * u.cacheRead) / prompt) : undefined
}

function describe(run: GateRun): { glyph: string; color: string; text: string } {
  const of = run.attempt !== undefined && run.max !== undefined ? ` ${run.attempt}/${run.max}` : ''
  switch (run.outcome) {
    case 'pass':
      return { glyph: '✓', color: 'success', text: run.preexisting?.length ? 'passed (pre-existing failures ignored)' : 'passed' }
    case 'block':
      return { glyph: '✗', color: 'error', text: `blocked, attempt${of}` }
    case 'gave_up':
      return { glyph: '⚠', color: 'warning', text: `gave up after${of}, stop allowed` }
    case 'given_up':
      return { glyph: '⚠', color: 'warning', text: 'still failing, already gave up' }
    case 'stall':
      return { glyph: '⚠', color: 'warning', text: 'released: no changes since the block' }
  }
}

async function run($: EngineInterface, argv: string[], cwd: string, timeoutMs = 30_000) {
  try {
    return await $.process.run(argv, { cwd, timeoutMs })
  } catch (err) {
    return { exitCode: -1, stdout: '', stderr: String((err as Error)?.message ?? err) }
  }
}

async function git($: EngineInterface, cwd: string, args: string[]): Promise<string | undefined> {
  const r = await run($, ['git', ...args], cwd)
  return r.exitCode === 0 ? r.stdout.trim() : undefined
}

async function setup($: EngineInterface): Promise<Ctx | undefined> {
  const cwd = await $.session.cwd()
  const root = await git($, cwd, ['rev-parse', '--show-toplevel'])
  const gitDir = root && (await git($, root, ['rev-parse', '--absolute-git-dir']))
  if (!root || !gitDir) return undefined
  // The mod ships in <khoros>/mods/khoros-view; a project using Khoros may carry its own bin/khoros.
  const candidates = [`${$.plugin.root}/../../bin/khoros`, `${root}/bin/khoros`]
  let bin = 'khoros'
  for (const c of candidates) {
    if (await $.fs.exists(c)) {
      bin = c
      break
    }
  }
  const sessionId = await $.session.id()
  const startedAt = (await $.session.usage()).startedAt
  return { root, stateDir: `${gitDir}/khoros`, session: safeName(sessionId), sessionId, bin, startedAt }
}

async function readJson($: EngineInterface, path: string): Promise<any> {
  try {
    return parseJson(await $.fs.read(path))
  } catch {
    return undefined
  }
}

// ------------------------------------------------------------------ data

async function refreshGate($: EngineInterface): Promise<GateView> {
  const c = ctx
  if (!c) return read($, gate)
  const runsPath = `${c.stateDir}/runs-${c.session}.json`
  let runs: GateRun[] | undefined
  try {
    const st = await $.fs.stat(runsPath)
    if (st.mtimeMs !== runsMtime) {
      runsMtime = st.mtimeMs
      runs = (await readJson($, runsPath))?.runs
    }
  } catch {
    // no run recorded yet this session
  }
  const isKhoros = await $.fs.exists(`${c.root}/.harness/config.yaml`)
  const isActive = await $.fs.exists(`${c.stateDir}/session-${c.session}.json`)
  const isOff = (await readJson($, `${c.stateDir}/off-${c.session}.json`))?.off === true
  const next = await update($, gate, g => ({ isKhoros, isActive, isOff, runs: Array.isArray(runs) ? runs : g.runs }))
  await paintStatus($)
  return next
}

async function refreshTasks($: EngineInterface): Promise<void> {
  const c = ctx
  if (!c) return
  const r = await run($, [c.bin, 'status', '--json'], c.root)
  const parsed = r.exitCode === 0 ? parseJson(r.stdout) : undefined
  const at = Date.now()
  if (!parsed || !Array.isArray(parsed.tasks)) {
    await update($, tasks, t => ({ ...t, at, error: (r.stderr || r.stdout || 'khoros status failed').trim().split('\n').pop() }))
    return
  }
  const list: Task[] = parsed.tasks.map((t: any) => ({
    id: String(t.id), title: String(t.title ?? ''), status: String(t.status ?? ''), owner: t.owner ?? null,
    deps: Array.isArray(t.deps) ? t.deps.map(String) : [],
  }))
  await update($, tasks, () => ({ tasks: list, at }))
}

async function paintStatus($: EngineInterface): Promise<void> {
  const g = await read($, gate)
  if (!g.isKhoros) return $.ui.status(undefined)
  const u = await read($, usage)
  const last = g.runs.at(-1)
  const blocks = g.runs.filter(r => r.outcome === 'block').length
  const gatePart = g.isOff ? 'gate off' : !g.isActive ? 'gate not loaded' : last ? `gate ${describe(last).glyph}` : 'gate idle'
  const parts = [gatePart]
  if (blocks) parts.push(`${blocks} block${blocks > 1 ? 's' : ''}`)
  if (u.requests) {
    const hit = cacheHit(u)
    parts.push(`${k(totalTokens(u))} tok` + (hit !== undefined ? ` · ${hit}% cache` : ''))
  }
  if (u.usd !== undefined) parts.push(`$${u.usd.toFixed(2)} est`)
  $.ui.status(parts.join(' · '))
}

async function saveRecord($: EngineInterface): Promise<void> {
  const c = ctx
  if (!c) return
  const g = await read($, gate)
  if (!g.isKhoros) return
  const u = await read($, usage)
  const record: SessionRecord = {
    id: c.sessionId, repo: c.root.split('/').pop() ?? c.root, startedAt: c.startedAt, updatedAt: Date.now(),
    requests: u.requests, tokens: totalTokens(u), cacheRead: u.cacheRead, usd: u.usd, runs: g.runs.length,
    passes: g.runs.filter(r => r.outcome === 'pass').length,
    blocks: g.runs.filter(r => r.outcome === 'block').length,
    gaveUp: g.runs.filter(r => r.outcome === 'gave_up').length,
  }
  // one key per session, so concurrent sessions never overwrite each other
  await $.store.set(`session:${c.sessionId}`, record)
}

async function loadHistory($: EngineInterface): Promise<void> {
  const keys = (await $.store.keys()).filter(key => key.startsWith('session:'))
  const records = (await Promise.all(keys.map(key => $.store.get(key)))) as (SessionRecord | undefined)[]
  const sorted = records.filter((r): r is SessionRecord => !!r && typeof r.updatedAt === 'number')
    .sort((a, b) => b.updatedAt - a.updatedAt)
  for (const old of sorted.slice(HISTORY_KEPT)) await $.store.delete(`session:${old.id}`)
  await update($, history, () => sorted.slice(0, HISTORY_KEPT))
}

// ------------------------------------------------------------------ actions

async function finish($: EngineInterface, label: string, isOk: boolean, summary: string): Promise<void> {
  await update($, action, () => ({ last: { label, isOk, summary, at: Date.now() / 1000 } }))
  $.ui.toast(`${label}: ${summary}`)
}

async function runVerify($: EngineInterface): Promise<void> {
  const c = ctx
  if (!c || (await read($, action)).running) return
  await update($, action, a => ({ ...a, running: 'verify' }))
  const r = await run($, [c.bin, 'verify', '--changed', '--json'], c.root, ACTION_TIMEOUT_MS)
  const report = parseJson(r.stdout)
  if (!report) return finish($, 'verify', false, (r.stderr || 'no report').trim().split('\n').pop() ?? '')
  const first = report.violations?.[0]
  const where = first ? ` · ${first.rule} ${first.file ?? ''}${first.line ? ':' + first.line : ''}` : ''
  const summary = `${report.passed ? 'passed' : 'failed'} · ${report.violation_count ?? 0} violation(s) · tests ${report.tests?.status ?? '?'}${where}`
  await finish($, 'verify', !!report.passed, summary)
}

async function rerunFailing($: EngineInterface): Promise<void> {
  const c = ctx
  if (!c || (await read($, action)).running) return
  const failed = [...(await read($, gate)).runs].reverse().find(r => r.outcome !== 'pass' && r.outcome !== 'stall')
  const test = failed?.tests?.find(t => t.status === 'failed' && t.command)
  const files = [...new Set((failed?.violations ?? []).map(v => v.file).filter((f): f is string => !!f))]
  if (!test && !files.length) return void $.ui.toast('Nothing failing to re-run')
  await update($, action, a => ({ ...a, running: 're-run' }))
  if (test?.command) {
    const r = await run($, ['sh', '-c', test.command], c.root, ACTION_TIMEOUT_MS)
    const tail = (r.stderr + '\n' + r.stdout).trim().split('\n').filter(Boolean).pop() ?? ''
    return finish($, test.command, r.exitCode === 0, `${r.exitCode === 0 ? 'passes now' : `exit ${r.exitCode}`} · ${tail}`)
  }
  const r = await run($, [c.bin, 'verify', '--fast', '--json', ...files], c.root, ACTION_TIMEOUT_MS)
  const report = parseJson(r.stdout)
  await finish($, 'static checks', !!report?.passed,
    report ? `${report.passed ? 'pass now' : 'still failing'} · ${report.violation_count ?? 0} violation(s)` : 'no report')
}

async function toggleGate($: EngineInterface): Promise<void> {
  const c = ctx
  if (!c) return
  const isOff = !(await read($, gate)).isOff
  try {
    await $.fs.write(`${c.stateDir}/off-${c.session}.json`, JSON.stringify({ off: isOff }))
  } catch (err) {
    return void $.ui.toast(`Could not switch the gate: ${String((err as Error)?.message ?? err)}`)
  }
  await refreshGate($)
  $.ui.toast(isOff ? 'Gate off for this session' : 'Gate on for this session')
}

async function openPane($: EngineInterface): Promise<void> {
  await $.ui.open({ id: PANE, title: 'Khoros' })
  void refreshGate($)
  void refreshTasks($)
  void loadHistory($)
}

// ------------------------------------------------------------------ hooks

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    ctx = await setup($)
    runsMtime = -1
    if (ctx) {
      const g = await refreshGate($)
      if (g.isKhoros) {
        // Always loaded (not deferred) by the user's choice; its bench arm measures what that costs.
        await $.tool.register({
          name: 'status',
          description: 'Khoros state for this session: recent verification-gate results (blocks, new vs ' +
            'pre-existing failures), token use and cost, and the task board. Read-only.',
          isDeferred: false,
        })
        $.clock.every(3000, () => refreshGate($))
      }
    }
    try {
      await $.command.register({ name: 'khoros', description: 'Show the Khoros gate, cost and tasks in a pane', immediate: true })
    } catch {
      // the name is taken; the status line still works
    }
    return next(e)
  })

  on('command.run', { command: 'khoros' }, async $ => {
    await openPane($)
    return {}
  })

  on('turn.step', async function* ($, e, next) {
    const result = yield* next(e)
    const u = result.usage
    if (u) {
      await update($, usage, v => ({
        ...v, requests: v.requests + 1, input: v.input + u.input_tokens, output: v.output + u.output_tokens,
        cacheRead: v.cacheRead + u.cache_read_input_tokens, cacheWrite: v.cacheWrite + u.cache_creation_input_tokens,
      }))
      await paintStatus($)
    }
    return result
  })

  on('session.measure', async ($, e, next) => {
    await update($, usage, v => ({ ...v, usd: e.cost?.usd ?? v.usd, contextPercent: e.context.percent ?? v.contextPercent }))
    await paintStatus($)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined && ctx) {
      await refreshGate($)
      await saveRecord($)
      void refreshTasks($)
    }
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    await saveRecord($)
    return next(e)
  })

  on('tool.call', { tool: TOOL }, async $ => {
    const g = await refreshGate($)
    await refreshTasks($)
    const u = await read($, usage)
    const t = await read($, tasks)
    const recent = g.runs.slice(-5).map(r => ({
      at: new Date(r.at * 1000).toISOString(), outcome: r.outcome, attempt: r.attempt, max: r.max, new: r.new,
      preexisting: r.preexisting, failing: (r.violations ?? []).slice(0, 5), tests: r.tests,
    }))
    const state = {
      gate: { on: !g.isOff, loaded: g.isActive, recent },
      usage: { requests: u.requests, tokens: totalTokens(u), cacheHitPercent: cacheHit(u), estimatedUsd: u.usd },
      tasks: t.error ? { error: t.error } : t.tasks.filter(x => x.status !== 'COMPLETED'),
    }
    return { result: JSON.stringify(state) }
  }).catch(($, e, next) =>
    next.called ? next(e) : { result: 'khoros-view could not read the Khoros state; run `bin/khoros status` instead.' },
  )

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const current = await read($, tab)
    // the pane's own height: e.viewport.rows is the whole window in the terminal and the Desktop app
    const rows = Math.max(6, (e.props.scroll?.bodyRows ?? 24) - 3)
    const select = (t: Tab) => () => {
      void update($, tab, () => t)
      if (t === 'tasks') void refreshTasks($)
      if (t === 'history') void loadHistory($)
    }
    const tabs: [Tab, string, string][] = [['gate', 'Gate', '1'], ['cost', 'Cost', '2'], ['tasks', 'Tasks', '3'], ['history', 'History', '4']]

    let body
    if (current === 'gate') {
      const g = await read($, gate)
      const a = await read($, action)
      const last = g.runs.at(-1)
      const d = last && describe(last)
      body = (
        <Box flexDirection="column">
          {!g.isKhoros && <Text dimColor>This repo has no .harness/config.yaml: Khoros is not set up here.</Text>}
          <Box flexDirection="row" columnGap={2}>
            <Text bold color={g.isOff ? 'warning' : g.isActive ? 'success' : 'subtle'}>
              {g.isOff ? 'Gate off for this session' : g.isActive ? 'Gate on' : 'Gate hooks not loaded in this session'}
            </Text>
            <Button key="toggle" label={g.isOff ? 'Turn on' : 'Turn off'} hotkey="t" onPress={() => void toggleGate($)} />
          </Box>
          {last && d ? (
            <Box flexDirection="column" marginTop={1}>
              <Text color={d.color}>{`${d.glyph} ${clock(last.at)} ${d.text}`}
                <Text dimColor>{last.files !== undefined ? ` · ${last.files} file(s)` : ''}{last.seconds !== undefined ? ` · ${last.seconds}s` : ''}</Text>
              </Text>
              {(last.new ?? []).length > 0 && <Text wrap="truncate-end">{'  New failures: ' + last.new!.join(', ')}</Text>}
              {(last.preexisting ?? []).length > 0 && <Text dimColor wrap="truncate-end">{'  Pre-existing (ignored): ' + last.preexisting!.join(', ')}</Text>}
              {(last.violations ?? []).slice(0, 5).map((v, i) => (
                <Text key={'v' + i} wrap="truncate-end">{`  ${v.rule ?? ''} ${v.file ?? ''}${v.line ? ':' + v.line : ''} ${v.message ?? ''}`}</Text>
              ))}
              {(last.tests ?? []).map((t, i) => (
                <Text key={'t' + i} dimColor={t.status !== 'failed'} color={t.status === 'failed' ? 'error' : undefined} wrap="truncate-end">
                  {`  tests ${t.status}: ${t.command ?? ''}`}
                </Text>
              ))}
              {last.timed_out && <Text color="warning">  tests hit their time budget</Text>}
            </Box>
          ) : (
            <Text dimColor>No verification yet: the gate runs when Claude tries to stop after changing code.</Text>
          )}
          <Box flexDirection="row" columnGap={2} marginTop={1}>
            <Button key="verify" label={a.running === 'verify' ? 'Verifying…' : 'Run verify'} hotkey="v" onPress={() => void runVerify($)} />
            <Button key="rerun" label={a.running === 're-run' ? 'Running…' : 'Re-run failing check'} hotkey="r" onPress={() => void rerunFailing($)} />
          </Box>
          {a.last && (
            <Text color={a.last.isOk ? 'success' : 'error'} wrap="truncate-end">
              {`${a.last.isOk ? '✓' : '✗'} ${clock(a.last.at)} ${a.last.label}: ${a.last.summary}`}
            </Text>
          )}
          {g.runs.length > 1 && (
            <Box flexDirection="column" marginTop={1}>
              <Text bold>Earlier this session</Text>
              {g.runs.slice(0, -1).slice(-Math.max(1, rows - 14)).reverse().map((r, i) => {
                const x = describe(r)
                return <Text key={'r' + i} color={x.color}>{`${x.glyph} ${clock(r.at)} ${x.text}`}</Text>
              })}
            </Box>
          )}
        </Box>
      )
    } else if (current === 'cost') {
      const u = await read($, usage)
      const hit = cacheHit(u)
      body = (
        <Box flexDirection="column">
          <Text>{`Model requests: ${u.requests}` + (u.contextPercent !== undefined ? ` · context ${Math.round(u.contextPercent)}% full` : '')}</Text>
          <Text>{`Input ${k(u.input)} · output ${k(u.output)}`}</Text>
          <Text>{`Cache read ${k(u.cacheRead)} · cache write ${k(u.cacheWrite)}`}</Text>
          <Text>{'Cache hit rate: ' + (hit !== undefined ? `${hit}%` : 'no requests yet')}</Text>
          <Box marginTop={1}>
            <Text bold>{u.usd !== undefined ? `Cost: $${u.usd.toFixed(2)}` : 'Cost: not reported yet'}</Text>
          </Box>
          <Text dimColor>Estimate at API list price, as /cost computes it; not a bill. Includes subagents.</Text>
        </Box>
      )
    } else if (current === 'tasks') {
      const t = await read($, tasks)
      const color = (s: string) => (s === 'COMPLETED' ? 'success' : s === 'CLAIMED' ? 'warning' : s === 'REVIEW_REQUESTED' ? 'suggestion' : undefined)
      body = (
        <Box flexDirection="column">
          <Box flexDirection="row" columnGap={2}>
            <Text dimColor>{t.at ? `Task board · read ${clock(t.at / 1000)}` : 'Task board'}</Text>
            <Button key="refresh" label="Refresh" hotkey="f" onPress={() => void refreshTasks($)} />
          </Box>
          {t.error && <Text color="error" wrap="truncate-end">{t.error}</Text>}
          {!t.error && t.tasks.length === 0 && <Text dimColor>No tasks. The long-task skill creates them for multi-session work.</Text>}
          {t.tasks.slice(0, rows - 2).map(x => (
            <Text key={x.id} mono wrap="truncate-end">
              <Text color={color(x.status)}>{x.status.padEnd(16)}</Text>
              {` ${x.id}  `}
              <Text dimColor>{x.title}{x.owner ? ` · ${x.owner}` : ''}{x.deps.length ? ` · after ${x.deps.join(',')}` : ''}</Text>
            </Text>
          ))}
        </Box>
      )
    } else {
      const records = await read($, history)
      body = (
        <Box flexDirection="column">
          {records.length === 0 && <Text dimColor>No sessions recorded yet. Each Khoros session is saved as it goes.</Text>}
          {records.length > 0 && <Text dimColor mono>{'date        repo            runs  ✓   ✗   tokens   cost'}</Text>}
          {records.slice(0, rows - 1).map(r => (
            <Text key={r.id} mono wrap="truncate-end">
              {`${day(r.updatedAt)}  ${r.repo.slice(0, 14).padEnd(14)}  ${String(r.runs).padStart(4)}  ${String(r.passes).padStart(2)}  `}
              <Text color={r.blocks ? 'error' : undefined}>{String(r.blocks).padStart(2)}</Text>
              {`  ${k(r.tokens).padStart(7)}  ${r.usd !== undefined ? '$' + r.usd.toFixed(2) : '-'}`}
            </Text>
          ))}
        </Box>
      )
    }

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          {tabs.map(([id, label, key]) => (
            <Button key={'tab-' + id} label={id === current ? `▸ ${label}` : label} hotkey={key} plain onPress={select(id)} />
          ))}
        </Box>
        <Box marginTop={1}>{body}</Box>
      </Box>
    )
  })
}
