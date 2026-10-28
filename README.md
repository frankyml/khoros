# Khoros (Χορός)

A harness on top of [Claude Code](https://code.claude.com): a verification gate that runs your tests before
the agent can stop, a few per-edit checks, an optional task board for long work, and a fresh-context reviewer.
Formerly Personal Development Harness (PDH).

v4 is built around what our own benchmark could and could not show. Read the
[v4 RFC](docs/rfc/khoros-v4.md) for the evidence and the design.

## What is enforced

These run as Claude Code hooks (see `plugin/hooks/hooks.json`) and do not depend on the agent remembering
a prompt.

- **Stop-hook gate** (`bin/khoros-gate stop`, with a `session-start` hook that snapshots the tree): verifies what
  *this session* changed (edits, commits, changed dirty files) with static checks and the project's tests, run
  with the project's interpreter from the repo root. On failure it blocks the stop with what failed and how to
  fix it, and the agent keeps working. Failures that were already there when the session started do not block
  (they are reported as a note). Safeguards: it gives up after 3 consecutive blocks (`verify.max_stop_blocks`)
  and then stays quiet until the failure changes, one time budget covers the whole gate
  (`verify.gate_budget`, default 270 s; `verify.test_timeout`, default 240 s, per command), it allows the
  stop if it cannot persist its state, it is silent on turns that changed nothing or only docs, and
  `KHOROS_GATE=off` or `verify.gate: off` disables it. State lives in the git dir, not in your work tree.
  The gate runs your repo's test and lint commands from a hook, without a permission prompt: enable the plugin
  only in repos you trust.
- **Per-edit checks** (`bin/khoros-gate post-edit`): fast static checks (syntax, secrets, config parse) on the
  file just edited.
- **Loop nudge**: one message when the same file has been edited 8 or more times in a session.

`bin/khoros verify` reports every check it skipped, with the reason, so "passed" does not hide "did not run".
It only checks what it can detect (for example JS syntax needs `node`; tests need a recognisable test
command). It is not proof of correctness.

## What is opt-in

- **`long-task` skill**: durable task state (`bin/khoros task create | claim | submit | approve`,
  `bin/khoros status`), one task at a time, a commit per task. For multi-session or many-feature work. Not loaded for small tasks.
- **Blackboard task DAG** (SQLite): the state store behind that skill.
- **`khoros-reviewer` agent**: read-only reviewer that sees a diff and the request without the author's
  reasoning. Invoke it when you want a second look.

## What is experimental

Present in the tree, covered by unit tests, **not wired into the runtime and not shown to help**:
the kernel graph, event store and worktree manager; capsules; kaizen (attribution and jig synthesis); skill
mining; the governor token budget; `bin/bwrap-exec`; the Android helper scripts. Details, current callers and
what evidence would promote each are in [`.harness/EXPERIMENTAL.md`](.harness/EXPERIMENTAL.md). Earlier
documentation described several of these (write-time AST jigs, a causal elimination DAG, a bwrap sandbox,
cache-hit telemetry) as working features; they were not.

## Benchmark status

`bench/` compares plain Claude Code (`vanilla`), a length-matched placebo `CLAUDE.md` and Khoros, with the
model fixed (Sonnet). On the v3.1 harness, no run showed Khoros raising solve rate: the regression suites
are near ceiling (vanilla 94-100%), so they can detect harm and cost but not help; Khoros cost 1.05x to 1.22x
vanilla, and the placebo did about as well as Khoros. In the phase-2 pilot (19 sqlglot tasks), solve rates were
vanilla 16%, factory workflow 17%, placebo 21% with intervals including zero, while the factory workflow cost
1.18x and took about 1.6x as long. **v4, hard suite (2026-10-27, Sonnet, 2 reps × 6 tasks per arm, `bench/results/v4-hard-sonnet`):** Khoros solved 12/12 (vanilla 11/12, placebo 12/12, Khoros without the gate plugin 12/12). Its cost ratio is 0.97x vanilla (95% CI 0.86x–1.08x), against 1.06x–1.22x for v3.1, so H4 holds on this suite. Every Khoros run tested its code and finished on a verified state (vanilla 75%). The gate never had to block, because no run tried to stop on red tests. The suite is near ceiling, so it shows that v4 no longer costs extra, not that it helps. Whether the gate raises success (H5) needs the phase-2 scenarios, which have not been run on v4. Costs are Claude Code list-price estimates, not bills.

## Quick start

```bash
bin/khoros verify            # run checks and the project's tests
bin/khoros verify --fast     # static checks only
bin/khoros status            # task board (long-task work)
python3 -m unittest discover tests/unit
```

## Documentation

- [v4 RFC](docs/rfc/khoros-v4.md): evidence, design, evaluation plan, risks
- [Wiki](wiki/Home.md): includes [09. Khoros v4](wiki/09-Khoros-v4-Evidence-Driven-Harness.md). Chapters 01-08
  describe the earlier v3 design; each marks which parts are experimental.
- [Experimental modules](.harness/EXPERIMENTAL.md)
- [Benchmark](bench/README.md)
