# Khoros rules

Khoros is a harness on top of the agent: a verification gate, a durable task board and a fresh-context reviewer.

- In a project with `.harness/`, run `khoros verify` before finishing code changes (`--fast` for static checks only). Fix the root cause when it fails; do not bypass it.
- Never claim a task done without a passing verify.
- For long or multi-session work, use the `long-task` skill: `khoros task create`, `claim`, `submit`, `approve`, `status`, one task at a time, a commit per task.
- Small tasks need no triage, specs or task registration.
- Enforce rules with checks, not prose; keep domain rules out of the core engine.
