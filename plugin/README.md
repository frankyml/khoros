# Khoros plugin (Claude Code)

- `.claude-plugin/plugin.json`: plugin manifest (name `khoros`, v4.0.0).
- `hooks/hooks.json`: Stop and post-edit hooks that run `bin/khoros-gate` (verification gate).
- `skills/long-task/`: opt-in workflow for multi-session work using the task board.
- `agents/khoros-reviewer.md`: read-only reviewer that checks a diff in fresh context.
- `rules/AGENTS.md`: short always-on rules for hosts that read it.

Antigravity uses `.agents/rules/harness-lead.md` and `.agents/hooks.json` instead.
