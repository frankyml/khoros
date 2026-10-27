# Khoros

Khoros is a harness on top of Claude Code: a verification gate, a durable task board, and a fresh-context reviewer.

## Verification
- A Stop hook runs `bin/khoros verify` on changed code and sends you back to work if tests fail.
  Run `bin/khoros verify` yourself before finishing; `--fast` runs static checks only.
- When the gate fails, fix the root cause. Do not skip, weaken or bypass the check.
- Tests: `python3 -m unittest discover tests/unit`

## Long or multi-session work
Use the `long-task` skill (task board, one task at a time, commit per task). Small tasks need no ceremony.

## Invariants
- Code over prompt: what must hold is enforced by a check or hook, not by prose.
- Never claim done without a passing `bin/khoros verify`.
- Domain rules stay out of the core engine; they live in `.harness/capsules/`.

## CLI
`bin/khoros verify | status`; `task create`, `claim`, `submit`, `approve` are described in the `long-task` skill.
