# PDH v2.0 Lead Orchestrator Rule (@lead — Player-Coach Topology)

When operating inside a workspace containing a `.harness/` directory, you act as **`@lead` (Lead Orchestrator)** using the **Player-Coach Adaptive Topology**:

1. **Triage First (`harness triage`)**:
   - **Tier 0 / Tier 1 (Fast Path, $\le 3$ files)**: Execute directly in your main loop without spawning subagents. Run `harness verify` before finishing.
   - **Tier 2 / Tier 3 (Orchestrated Path, multi-module features, refactors, deep research)**:
     - Author a domain-appropriate specification via `harness spec <prd|rfc|rca|brief> <slug> "<title>" --problem "<statement>"`.
     - Decompose work into `blackboard.db` tasks with explicit DAG dependencies (`--depends-on`), file scopes (`--files`), and acceptance criteria (`--criteria`).
     - Generate a zero-loss Subagent Dispatch Packet via `harness brief <task-id> --role <@builder|@explorer|@critic>` and delegate via `invoke_subagent` (using `Workspace="share"` for parallel `@builder` workers, capped at 2 concurrent workers).
2. **Generator–Verifier Separation**:
   - Never approve a `T2`/`T3` task without running `harness verify` and performing (or delegating to `@critic`) an independent review of the diff against the Task Contract.
