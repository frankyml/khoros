# Khoros benchmark hypotheses

Written before the Phase 1 and Phase 2 experiments, so the analysis cannot be fitted to the results.
Change this file only with a dated entry under **Amendments**, never silently.

Each hypothesis has one **primary metric**. Everything else the report prints is exploratory: useful for
understanding, not for claiming an effect.

## Arms

| arm | what differs from vanilla |
|---|---|
| `vanilla` | nothing: plain Claude Code |
| `khoros` | Khoros installed (CLAUDE.md, `.harness/` + `bin/khoros`, plugin); the agent decides how to use it |
| `khoros-factory` | as `khoros`, plus a prompt preamble asking for the full workflow (triage, spec, blackboard tasks, verify) |
| `khoros-noplugin`, `khoros-cli-only` | ablations, used to attribute an effect once one is found |

All arms get the same task prompt and the same neutral suffix (prompt version 2). Every comparison is
paired by task against `vanilla`, with the same model, CLI version and Khoros commit.

## Hypotheses

| id | hypothesis | primary metric | suite | success threshold |
|---|---|---|---|---|
| H1 | Khoros raises task success on T2/T3 work | Δ hidden-test pass share vs vanilla (pp); Δ solve rate secondary | Phase 1 capability suite (vanilla 20–80%) and Phase 2 feature scenarios | 95% CI lower bound > 0 |
| H2 | Khoros lowers escaped defects | Δ share of planted defects that ship (pp) | Phase 2 defect-escape scenario | 95% CI upper bound < 0 |
| H3 | Khoros keeps long, multi-session work on track | Δ features completed per run | Phase 2 multi-session scenario | 95% CI lower bound > 0 |
| H4 | Khoros's cost overhead is under 15% | cost ratio vs vanilla | every suite | 95% CI upper bound < 1.15 |

H1–H3 are tested separately for `khoros` and `khoros-factory`. With two arms per hypothesis, an effect
counts only if it holds for the arm it is claimed for; we do not pick the better arm after the fact.

## Analysis rules

- **Unit of analysis:** the task. Intervals come from a two-stage clustered bootstrap (tasks, then trials).
- **Power first:** before a run, `report.py`'s power simulation must show at least 80% power for a
  15-point effect at the expected baseline. Smaller designs are pilots, and their nulls are reported as
  *inconclusive*, never as *no effect*.
- **Calibration without bias:** tasks are selected for difficulty using a configuration that is not one of
  the compared arms (vanilla Haiku), on runs that are then discarded.
- **Pre-registered subgroups only:** suite, tier (T2 vs T3) and model. Any other split is exploratory and
  needs a fresh replication before it is reported as a finding.
- **Timeouts:** a run that hit the time limit but left a passing solution counts as solved.
- **Exclusions:** only runs that never started (provisioning or runner errors) are dropped; every agent
  failure counts.
- **Adoption:** every report shows which Khoros features each arm used. An effect in an arm that did not
  use a feature is not attributed to that feature.

## Current suites

`core` (9 tasks) and `hard` (6 tasks) are **regression suites**: Sonnet and Haiku solve 94–100% of them in
every arm, so they detect harm (and measure cost) but cannot detect help. They run on every Khoros change.

## Amendments

- 2026-10-19: initial version.
- 2026-10-19 (risk review, before any Phase 1 or Phase 2 agent runs):
  1. **Phase 1 contrast is `vanilla` vs `khoros-factory`.** Left to decide, the `khoros` arm only ever ran
     `khoros verify` (63 of 63 runs), so its effect is the instruction overhead the regression suites already
     measure. `khoros` stays in the regression suites; Phase 1 spends its budget on the factory.
  2. **Calibration uses discarded runs of vanilla Sonnet**, 3 trials per task, keeping tasks with 1 or 2 of 3
     successes. Selecting on independent runs that are then discarded does not bias the fresh comparison, and
     it matches difficulty to the model under test better than Haiku would.
  3. **H1's primary metric becomes partial credit**: the share of a task's hidden tests that pass (from the
     verifier's CTRF report, or our hidden tests locally). It is far more sensitive than pass/fail at the task
     counts we can reach. The solve rate stays as the main secondary metric and is always reported next to it;
     a claim of help rests on the primary metric alone.
  4. **New pre-registered stratum: factory engaged.** Each task is labelled by the tier `khoros triage` assigns
     it before the run (T0/T1 vs T2/T3). Effects are reported for both strata, because the factory only does
     anything on T2/T3 work.
  5. **Sequential design.** Phase 1 runs in batches. After half the planned trials, it stops for futility if the
     95% interval for the solve-rate gain already lies below +10 points.
  6. **Phase 2 entry gate:** a scenario task is admitted only if `khoros triage` rates it T2 or T3.
- 2026-10-19 (harness focus, before any Phase 1 or Phase 2 agent runs): the system under test is the harness;
  the model is held fixed and treated as a moderator, never as the target.
  1. **Harness-relevant tasks only.** External tasks are kept only in categories where process can plausibly
     change the outcome (software engineering, debugging, system administration, file operations, data
     processing, data querying, personal assistant). Categories bound by model knowledge or compute (ML and
     model training, scientific computing, mathematics, security and cryptanalysis, data science, games, video,
     optimisation) are excluded before any agent run. Rule implemented in `bench/harbor/select_pool.py`.
  2. **Placebo control.** A `placebo` arm installs a CLAUDE.md as long as Khoros's always-loaded context
     (6.7 KB) with no instructions. It runs in the regression suites and in Phase 2, so effects of prompt length
     are separated from effects of Khoros's content. A Khoros effect counts only if it also beats `placebo`.
  3. **Harness behaviour is a reported outcome**, measured identically in every arm: ran tests, ended on
     verified code (a test run after the last edit), test runs, edits, tool errors, to-do planning. These are
     secondary metrics: they explain an effect, they do not establish one.
  4. **Failure modes.** Phase 3 adds a failure-mode classification of failed transcripts (for example stopped
     early, never verified, lost track across sessions, wrong file), compared between arms.
  5. **Model as moderator.** Phase 1 and 2 hold the model fixed (Sonnet). Phase 4 repeats the confirmed
     effects on Haiku and Opus to see whether the harness matters more for weaker models.
- 2026-10-19 (task construction, before any Phase 1 or Phase 2 results; pilot runs are excluded from analysis):
  1. **Phase 2 entry gate, operationalised:** `khoros triage "<request>" --files "<files the real change touches>"`
     must return T2 or T3, i.e. the tier Khoros assigns once the scope is known, as its own workflow does. The
     tier from the request text alone is recorded as an exploratory stratum: it is keyword-driven and rates 13
     of the 20 sqlglot features T0/T1 although each touches 4–10 files.
  2. **Scenario 1 tasks** are mined from sqlglot `feat` commits since 2025-06-01 (`bench/scenarios/mine_repo_features.py`):
     only source and test files changed, ≥2 source files, ≥4 files in total, 30–400 added source lines, all of
     the commit's test methods passing at the commit and at least one failing at the parent. The workspace is
     the parent's tree with no git history. Prompts alternate terse / full ticket in commit order.
  3. **Partial credit for repository tasks** (the H1 primary metric) is the share of assertions the feature has
     to flip: (passing now − passing before) / (total − passing before) over the fail-to-pass methods, with
     totals from the real commit; methods with nothing to flip fall back to method-level pass/fail.
  4. **Project instructions are kept.** When a repository ships its own CLAUDE.md, every arm keeps it; the Khoros
     and placebo arms append their text after it, as installing into an existing project would.
  5. **Phase 1 pool rules:** Terminal-Bench tasks with no oracle verdict after two attempts are excluded. The
     SWE-rebench top-up is a seeded random sample (seed 2026) of 30 standard (non-`_interface`) tasks from the
     downloaded set. On x86-only images every arm installs Claude Code from npm, vanilla included.
- 2026-10-27 (Khoros v4, before any v4 agent run): v4 replaces prose-only process with enforcement and cuts the
  always-loaded context (design: `docs/rfc/khoros-v4.md`). The plugin now carries a Stop/SubagentStop hook that runs
  `khoros verify` (project tests included) on changed code and blocks completion on failure (at most 3 blocks per
  session), a per-edit static check and a loop nudge; CLAUDE.md shrinks to ≤ 40 lines; the factory workflow moves to
  an opt-in `long-task` skill; the five `pdh-*` personas become one `khoros-reviewer`.
  1. **New hypothesis H5:** the v4 gate raises hidden-test pass share (H1's primary metric) on the hard suite and on
     Phase 2 scenario 1, compared with `vanilla` **and** with `placebo`. Success threshold as H1.
  2. **Gate attribution:** `khoros` (v4: CLAUDE.md + CLI + plugin with hooks) vs `khoros-noplugin` (same CLAUDE.md
     and CLI, no hooks) isolates the gate. An effect is attributed to the gate only if `khoros` beats
     `khoros-noplugin`.
  3. **H4 is re-tested for v4** with the same threshold (cost ratio upper bound < 1.15). Gate activity (blocks per
     run, runs whose stop was blocked at least once, runs where the gate gave up) is a reported secondary metric.
  4. v3.1 results (commit `7770846` and earlier) are not pooled with v4 results; v3.1 vs v4 is compared only
     through each version's paired contrast against `vanilla` in the same run.
  5. `.harness/state/` (gate counters) is git-excluded in workspaces so it never reaches graded patches.
