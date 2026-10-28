# Khoros

You are `@lead`. Size the work first, then follow the matching path.

- **Small (≤3 files, one domain):** make the change directly. Before finishing, run `bin/khoros verify --with-tests`.
- **Larger (multi-file feature, refactor, broad research):**
  1. `bin/khoros triage "<request>" --files "a,b"` to confirm the tier.
  2. `bin/khoros spec <prd|rfc|rca|brief> <slug> "<title>" --problem "<statement>"` for the plan.
  3. `bin/khoros task create <id> "<title>" --files "..." --criteria "..." [--depends-on "..."]` per unit of work.
  4. `bin/khoros claim <id> --worker @lead`, implement and test, then `bin/khoros submit <id> --summary "..."` and `bin/khoros approve <id>`.

Rules: never declare work done without `bin/khoros verify --with-tests` passing; prefer a test or linter over a written rule; keep domain rules in `.harness/capsules/`, not in the core.
