# Khoros rules (Antigravity)

In a workspace with `.harness/`:

- Do small tasks directly with `write_to_file`, `replace_file_content` and `run_command`; no triage or specs needed.
- Run `khoros verify` before finishing code changes (`--fast` for static checks only). Fix the root cause when it fails; never bypass it, and never claim done without a passing verify.
- For long or multi-session work, register tasks with `khoros task create <id> "<title>" --files ... --criteria ... --depends-on ...`, then `claim`, `submit`, `approve`. One task at a time, a commit per task.
- Get an independent review of large diffs: delegate with `invoke_subagent` and give the reviewer only the diff and the request, not your reasoning.
- If `.harness/design-tokens.json` exists, do not hardcode colors or spacing in UI code outside theme/token files; `khoros lint` checks this.
