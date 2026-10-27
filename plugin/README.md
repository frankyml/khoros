# Khoros plugin (Claude Code)

- `.claude-plugin/plugin.json`: plugin manifest (name `khoros`, v4.0.0).
- `hooks/hooks.json`: SessionStart, Stop and post-edit hooks that run `bin/khoros-gate` (verification gate).
  The hook command is `${CLAUDE_PLUGIN_ROOT}/../bin/khoros-gate`, so the plugin must be loaded in place from a
  Khoros checkout (`claude --plugin-dir <checkout>/plugin`). A marketplace install copies only this directory;
  the hook would fail to start and the gate would be silently inert.
- The gate runs the repo's test and lint commands from the hook without a Claude Code permission prompt. Enable
  the plugin only in repos you trust (or set `verify.gate: off` / `KHOROS_GATE=off`).
- `skills/long-task/`: opt-in workflow for multi-session work using the task board.
- `agents/khoros-reviewer.md`: read-only reviewer that checks a diff in fresh context.
- `rules/AGENTS.md`: short always-on rules for hosts that read it.

Antigravity uses `.agents/rules/harness-lead.md` and `.agents/hooks.json` instead.
