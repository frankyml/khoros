# Experimental modules

Status of the parts of `.harness/` and `bin/` that the Claude Code runtime does **not** depend on.
They are kept because tests exercise them and some may become useful, but none has benchmark evidence
that it improves outcomes. Nothing here is enforced on an agent at work.

Claims below were checked with `grep` against base commit `447045b` (the v4 branch point). Other v4
work-in-progress may change callers, notably `bin/khoros` telemetry; re-run the greps before relying on a row.

"Called by" means a non-test caller outside the module's own package. "Tests only" means the only importers
are under `tests/`.

| Module | What it does today | Called by | Evidence needed to promote |
|---|---|---|---|
| `.harness/kernel/graph.py` (`ExecutionGraph`) | State-node graph with transition guards, recording epochs in the event store. | Re-exported by `kernel/__init__.py`; tests only (`tests/unit/test_microkernel.py`). Never instantiated by `bin/` or `.harness/`. | A runtime path that drives a real task through it, plus a bench arm showing it beats the blackboard DAG on multi-session work (H3). |
| `.harness/kernel/event_store.py` (`KernelEventStore`) | SQLite event ledger (`kernel_events.db`). | `kaizen/attribution.py`, `kaizen/distillation.py`, `kernel/graph.py`, `kernel/jigs.py` (all themselves experimental); tests. | Something outside the experimental set that reads it to change an agent decision. |
| `.harness/kernel/worktree.py` (`WorktreeManager`) | Creates and removes git worktrees. | Re-exported by `kernel/__init__.py`; no instantiation anywhere in `bin/` or `.harness/`; tests only. | A measured parallel-worker run using it, with isolation and cost compared against one agent. The "<20 ms" APFS figure in older docs was never measured. |
| `.harness/kernel/jigs.py` (`InStationJigRunner`) | `ast.parse` plus a few regexes (secrets, hex colours) on a string, emitting an event on failure. | `validate_content` has no caller outside tests. It is **not** hooked to any write. The real per-edit check is `verify` (v4: `khoros-gate post-edit`). | Replace by gate checks; promote only if it catches defects the gate misses. |
| `.harness/jigs/jig_hardcoded_hex_d979f7.py` | The only synthesized jig: flags string constants containing the literal `#hardcoded_hex`. | Nothing imports it. | Not promotable as is; it shows the synthesis output was a placeholder. |
| `.harness/kernel/sandbox.py` | Runs a snippet in a subprocess with `RLIMIT` limits. Not a bwrap sandbox and does no network isolation. | `kaizen/distillation.py` (`run_sandboxed_test`); tests. | A threat model plus a test that network and filesystem escapes are blocked. |
| `.harness/kernel/canary.py`, `classifier.py` | `CleanTrunkCanary` runs a checker over repo files to count false positives; `CapabilityRiskClassifier` tiers code by AST. | `kaizen/distillation.py` only; tests. | Only meaningful if kaizen is fed real failures (see below). |
| `.harness/kernel/gc.py` (`GenerationalGC`) | Archives and restores "capabilities", cleans worktree dirs. | `bin/khoros gc` and `bin/khoros restore` (manual CLI). `run_micro_gc` has no caller outside tests. | A reason for agents to accumulate capabilities in the first place. |
| `.harness/capsules/loader.py`, `compactor.py` | Parses capsule YAML (rule budget K<=12); masks, folds and prunes long output. | Tests only. No `capsule.yaml` exists in the repo, so "domain rules live in `.harness/capsules/`" was never true. | A real capsule plus a bench arm in which it changes outcomes. Claude Code already compacts context itself. |
| `.harness/kaizen/attribution.py` | `assign_credit_attribution` returns fixed weight vectors from a short if/else on the failure type. Not a causal DAG. | Tests only. | Attribution validated against labelled failures. |
| `.harness/kaizen/distillation.py` | Counts recurring failure signatures and, at N>=2, synthesizes a jig. | `bin/khoros kaizen list/inspect/approve/reject` read proposals. `record_failure_and_evaluate`, which creates them, is called only from `tests/unit/test_phase2_khoros.py`, so real runs never produce proposals. | Wire to real gate failures; then show proposals are non-trivial and reduce repeat failures. |
| `.harness/skills/lifecycle.py` (`SkillLifecycleEngine`) | `khoros skill mine` writes a SKILL.md from recorded events. | `bin/khoros skill ...` (manual); tests. | Mined skills must beat no skill on a held-out task set. |
| `.harness/governor.py` token budget (RPM/TPM, reserve, "Andon" breaker on cache-hit ratio) | Throttles dispatch based on a rolling window of recorded usage. | `bin/khoros` and `.harness/dispatcher.py`. At `447045b` the only `record_usage` calls pass hardcoded token counts (e.g. `input_tokens=36000, cached_tokens=32768`), so every figure it reports is synthetic. v4 removes those calls. | Real usage fed from Claude Code transcripts or hook data; until then treat any governor output as not measured. |
| `bin/bwrap-exec` | Bubblewrap wrapper with Linux paths. | Referenced by nothing in `bin/`, `.harness/`, `plugin/` or `.agents/`. `.harness/kernel/host.py` only reports whether `bwrap` exists. Not usable on macOS. | A hook that routes commands through it, tested on Linux. |
| `bin/crash-sentinel`, `bin/frame-pacing-assert` | Android `adb logcat` / `dumpsys gfxinfo` checks, with package names from another project hardcoded. | Mentioned only in prose (`plugin/`, `.harness/roles/`). No code calls them. | Move to the project that needs them. |
| `src/` (3 Kotlin files, `src/apps/mobile/engine_adapter.py`) | Sample mobile code. | Linted by `verify` when present; no other use. | None; it is a sample. |

## What is not experimental

Wired into the v4 runtime and covered by the gate: `bin/khoros verify`, `bin/khoros-gate` (Stop and
post-edit hooks), the blackboard task commands used by the opt-in long-task skill, and the reviewer agent.
See the [v4 RFC](../docs/rfc/khoros-v4.md).
