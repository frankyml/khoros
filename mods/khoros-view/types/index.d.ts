// One Stop outcome as bin/khoros-gate records it in <git-dir>/khoros/runs-<session>.json.
export type GateRun = {
  at: number
  outcome: 'pass' | 'block' | 'gave_up' | 'given_up' | 'stall'
  attempt?: number
  max?: number
  files?: number
  seconds?: number
  violations?: { rule?: string; file?: string; line?: number; message?: string }[]
  tests?: { command?: string; status?: string }[]
  new?: string[]
  preexisting?: string[]
  timed_out?: boolean
}

// What the mod knows about the gate in this session.
export type GateView = {
  isKhoros: boolean // the repo has .harness/config.yaml
  isActive: boolean // the gate's SessionStart hook ran for this session
  isOff: boolean // turned off for this session from the pane
  runs: GateRun[]
}

// Token use summed over every model request of the session (subagents included).
export type UsageView = {
  requests: number
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  usd?: number // Claude Code's own /cost estimate at list price
  contextPercent?: number
}

export type Task = { id: string; title: string; status: string; owner: string | null; deps: string[] }
export type TasksView = { tasks: Task[]; error?: string; at?: number }

export type ActionView = {
  running?: string
  last?: { label: string; isOk: boolean; summary: string; at: number }
}

export type Tab = 'gate' | 'cost' | 'tasks' | 'history'

// One session's totals, kept in $.store under `session:<id>` across sessions.
export type SessionRecord = {
  id: string
  repo: string
  startedAt: number
  updatedAt: number
  requests: number
  tokens: number
  cacheRead: number
  usd?: number
  runs: number
  passes: number
  blocks: number
  gaveUp: number
}

declare module 'claude-code' {
  interface PluginState {
    'khoros-view': {
      gate: Shaped<GateView>
      usage: Shaped<UsageView>
      tasks: Shaped<TasksView>
      action: Shaped<ActionView>
      tab: Shaped<Tab>
      history: Shaped<SessionRecord[]>
    }
  }
}
