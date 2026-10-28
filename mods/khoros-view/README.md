# khoros-view

A Claude Code mod that shows what the Khoros harness is doing in your session. It only shows: the
verification gate stays in the shell hooks (`bin/khoros-gate`), and the mod never blocks or rewrites anything.

## What it shows

- **Status line** under the prompt, in a repo with `.harness/config.yaml`:
  `gate ✗ · 1 block · 182.4k tok · 91% cache · $0.42 est`.
- **`/khoros` pane** with four tabs (keys 1–4):
  - **Gate**: the last verification (new failures, pre-existing failures it ignored, failing checks and test
    commands) and earlier results this session. Buttons: run verify (`v`), re-run the failing check (`r`), and
    turn the gate off or on for this session (`t`).
  - **Cost**: model requests, input, output and cache tokens, cache hit rate, and Claude Code's own `/cost`
    figure, which is an estimate at API list price, not a bill. Subagents included.
  - **Tasks**: the long-task board, from `bin/khoros status --json`.
  - **History**: one row per past Khoros session (verifications, passes, blocks, tokens, cost).
- **A tool for Claude**, `mcp__khoros-view__status`, loaded on every turn: recent gate results, token use and
  open tasks as JSON. The `khoros-view` bench arm measures what it costs.

## Where the data comes from

| Data | Source |
|---|---|
| Gate results | `<git-dir>/khoros/runs-<session>.json`, written by `bin/khoros-gate stop` |
| Gate on/off for this session | `<git-dir>/khoros/off-<session>.json` (`{"off": true}`), read by the gate |
| Tokens | each model request's usage (`turn.step`) |
| Cost and context fill | Claude Code's session measure (`/cost`) |
| Tasks | `bin/khoros status --json` |
| History | the mod's own store (`~/.claude/plugins/store/`), one key per session, the newest 100 kept |

History lives in the mod's store, so it records only sessions where the mod ran. `claude -p` runs and the
benchmark draw nothing and keep no history.

## Use it

```bash
claude --plugin-dir /path/to/khoros/plugin --plugin-dir /path/to/khoros/mods/khoros-view
```

The gate's hooks come from `plugin/`; without them the pane says the gate is not loaded and shows only cost
and tasks. The mod finds `bin/khoros` next to itself (`../../bin/khoros`), else in the project, else on `PATH`.

## Develop

```bash
claude plugin validate mods/khoros-view   # what it hooks and calls
claude plugin test mods/khoros-view       # tests/register.test.tsx
```
