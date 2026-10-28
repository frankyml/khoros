# Khoros A/B benchmark

Measures whether Khoros makes Claude Code **better, cheaper or faster** at real coding tasks, by running the
same tasks with and without it and grading the results with hidden tests.

```bash
python3 bench/validate_tasks.py                    # oracle check of the corpus, no LLM (~5 s)
python3 bench/overhead.py                          # Khoros CLI latency + context tax, no LLM
python3 bench/run_ab.py --dry-run                  # provision workspaces, print commands, no LLM
python3 bench/run_ab.py --reps 3 --model sonnet    # the A/B run, both suites (90 agent runs)
python3 bench/run_ab.py --suite hard --reps 5      # only the hard suite
python3 bench/report.py bench/results/<timestamp>  # stats -> report.md + summary.csv
python3 bench/report.py --power --tasks 50 --trials 5 --rate 0.5   # size a design before paying for it
```

What we are testing, and how a result counts, is pre-registered in [HYPOTHESES.md](HYPOTHESES.md).

## What gets compared

| arm | `CLAUDE.md` | `.harness/` + `bin/khoros` on PATH | plugin (`pdh-*` agents, skill) |
|---|---|---|---|
| `vanilla` | – | – | – |
| `khoros` | ✓ | ✓ | ✓ |
| `khoros-noplugin` | ✓ | ✓ | – |
| `khoros-cli-only` | – | ✓ | – |
| `khoros-factory` | ✓ | ✓ | ✓, and the prompt asks for the full Khoros workflow |
| `khoros-lean` | trimmed (875 B) | ✓ | ✓ |
| `placebo` | neutral text as long as Khoros's always-loaded context | – | – |

The default is `--arms vanilla,khoros`. `khoros-noplugin` and `khoros-cli-only` are ablations that show which
Khoros surface is responsible for an effect. `khoros-factory` tests the orchestration itself: left to decide,
agents only ever used `khoros verify`, so without it the benchmark measures Khoros's instructions, not its tools.

Prompts carry a neutral suffix (prompt version 2: "Nobody is available to answer questions"). Version 1 told
agents not to ask questions and to finish end to end, which may have discouraged planning; results from the two
versions are not comparable, and each record stores its `prompt_version`. `--expect-claude-version` pins the CLI.

Every run is headless `claude -p` in a fresh git workspace with the **same prompt**. Your user settings, user
plugins, hooks and MCP servers are excluded (`--setting-sources project --strict-mcp-config`). Claude Code's
built-in plugins (`cc-plugin-sec-default`, `cc-plugin-agents-md`, `cc-plugin-telemetry`, `cc-plugin-plugin-authoring`)
still load, identically in every arm; each run's `init.plugins` records exactly what loaded. A probe on 2026-10-20
(phrases found only in Khoros's `plugin/rules/AGENTS.md`, tools disabled, with a positive control from `CLAUDE.md`)
showed `cc-plugin-agents-md` does **not** load the Khoros plugin's `rules/AGENTS.md` in the Khoros arms. Runs are
shuffled across arms to spread rate-limit and time-of-day noise evenly.
`--khoros-root <checkout>` benchmarks a different Khoros version, for example to compare two commits.

## Task corpus (`tasks/`)

A small Python shop package (`fixture/`). The **core suite** has 9 tasks spanning the tiers Khoros triages:

| task | tier | kind | what it probes |
|---|---|---|---|
| `t0-line-rounding` | T0 | bugfix | float-rounding bug, one line |
| `t0-remove-quantity` | T0 | bugfix | wrong edge-case handling |
| `t1-eur-format` | T1 | feature | precise output spec |
| `t1-percent-coupon` | T1 | feature | validation + integration with the existing cart |
| `t1-sale-badge` | T1 | feature | UI convention: colours must come from `theme.css` tokens, not hex (Khoros's design-token home turf) |
| `t2-checkout-mismatch` | T2 | bugfix | symptom-only report; root cause in another module |
| `t2-stock-reservation` | T2 | feature | cross-module behaviour change (inventory, cart, checkout) |
| `t2-tax-policy` | T2 | refactor | new abstraction with strict backwards compatibility |
| `t3-order-history` | T3 | feature | new module + persistence + CLI subcommand |

### Hard suite (`--suite hard`)

The core tasks turned out too easy: Sonnet solved all of them in both setups (27/27 vs 27/27), so they can only
measure cost. The hard suite targets the failure modes where a harness's process (reading the project's rules,
verifying, testing edge cases) should matter:

| task | tier | kind | what it probes |
|---|---|---|---|
| `h-promotions` | T3 | feature | long spec: unit claiming across promotions, largest-remainder cent allocation, tax integration |
| `h-returns` | T3 | feature | partial refunds that must sum exactly to the order total, repeat-safe return ids, all-or-nothing validation |
| `h-bug-hunt` | T2 | bugfix | three unrelated bugs behind one vague support ticket; the visible tests pass before the fix |
| `h-report-perf` | T2 | refactor | 100x speed-up that must keep byte-identical output, quirks included |
| `h-conventions` | T2 | feature | new operations that must follow rules written only in `CONTRIBUTING.md` (audit events, error classes) |
| `h-catalog-import` | T2 | feature | CSV import with BOM, decimal commas, currency symbols, duplicates and physical line numbers |

`run_ab.py` and `validate_tasks.py` take `--suite core|hard` (default: both). When results contain both suites,
the report adds a per-suite table and a per-suite paired comparison.

Each task has `prompt.md`, an optional `setup/` overlay that seeds a bug, a `solution/` reference and `hidden/` tests.
**Solved** means all hidden tests pass *and* a pristine copy of the visible suite still passes, so agents
can't game the result by editing tests. `validate_tasks.py` (also run by `tests/unit/test_bench_suite.py`)
proves every task fails before and passes with its reference solution.

## External and repository tasks

- **Phase 1, external tasks (`bench/harbor/`).** `run_harbor.py` runs Claude Code with and without Khoros on Harbor
  datasets in containers, and converts the results so `report.py` works unchanged. `select_pool.py` keeps only
  harness-relevant Terminal-Bench categories, drops tasks whose reference solution fails on this machine, and
  records the tier Khoros's triage assigns each task. `prepare_dataset.py` makes a local copy that builds natively
  on Apple Silicon and trusts a TLS-inspecting proxy's CA; `--npm-install` runs x86-only images (SWE-rebench) with
  Claude Code from npm in every arm. Containers need Claude credentials in `bench/harbor/certs/claude.env`.
- **Phase 2, repository tasks (`bench/scenarios/`).** `mine_repo_features.py` turns real feature commits of an
  open-source repository (clone it into `bench/scenarios/cache/<repo>`) into tasks: the workspace is the parent's
  tree without history, the grader runs the commit's fail-to-pass and pass-to-pass test methods, and partial credit
  is the share of the feature's assertions that pass. Run them with `run_ab.py --suite repo-features`.

## What is measured

- **Quality:** solve rate (Wilson 95% CI), hidden-test pass fraction, regressions, runs that added tests.
- **Cost / speed:** USD, wall time, turns, tool calls, output and prompt tokens (subagents included), cache-hit ratio.
- **Process footprint:** Khoros CLI calls by subcommand, subagent spawns, skill calls, non-code files written (specs, state).
- **Reliability:** pass^k, the share of tasks where every trial succeeded.
- **Khoros feature adoption:** share of runs using triage, spec, task, claim, submit, approve, brief, verify, `pdh-*` subagents and the skill.
- **Comparison:** two-stage clustered bootstrap vs `vanilla` (resample tasks, then trials): Δ solve rate, Δ pass^k,
  Δ hidden tests, and cost and latency ratios with 95% CIs. A non-significant result is reported as *inconclusive*,
  with the smallest gain the design could have detected, never as "no difference".
- **Fixed overhead** (`overhead.py`): per-command CLI latency and the static context Khoros adds to every turn.

Per-run transcripts (`transcripts/*.jsonl`) and diffs (`patches/*.diff`) are kept next to `results.jsonl`.

## Budgeting

A smoke run (`t0-line-rounding`, 1 rep, Haiku) cost about $0.01 for both arms. Sonnet on the full corpus costs far more:
start with `--tasks t0-line-rounding,t2-checkout-mismatch --reps 2` to calibrate, and use `--max-budget-usd` (per run,
default $3) as the hard cap. `--resume --out <dir>` continues an interrupted run. With 3 reps × 9 tasks the CIs
are still wide; use 5+ reps to detect solve-rate differences below ~20 points.

## Caveats

- Agents run with `--dangerously-skip-permissions` inside temp workspaces. The runner warns if the Khoros
  checkout changes during a run.
- `--setting-sources project` keeps your user settings, user plugins, hooks and global `~/.claude/CLAUDE.md` out of
  every arm (checked with a probe run); built-in plugins still load in every arm. Costs are Claude Code's
  list-price estimates from token usage.
- Each run's manifest records the Khoros commit **and** a hash of any uncommitted changes to Khoros's runtime files
  (`bin/`, `.harness/`, `plugin/`, `CLAUDE.md`), so results with the same commit but different working trees can be
  told apart. Results from before 2026-10-20 lack the hash: the first three experiments (core Sonnet, hard Sonnet,
  hard Haiku) ran before the `verify --with-tests` discovery fix, everything later ran after it.
- The corpus is Python-only and small by design. Add tasks by copying a task directory, then run `validate_tasks.py`.
