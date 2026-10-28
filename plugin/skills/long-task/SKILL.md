---
name: long-task
description: Use for work that spans multiple sessions or many features, where progress must survive context loss (durable task board, one task at a time, a commit per task). Do not use for single-session fixes or small changes; just do those and run verify.
---

# Long-running work

State lives in the Khoros task board (`.harness/blackboard.db`) and git, not in your context.

## Start of every session
1. `bin/khoros status` — see which tasks are pending, claimed or done.
2. `git log -10 --oneline` — see what was last committed.
3. `bin/khoros verify` — confirm the tree is green before adding anything. Fix a red tree first.

## Plan once
Break the work into small tasks, each completable and verifiable in one sitting:

    bin/khoros task create <id> "<title>" --files a.py,b.py --criteria "criterion 1;criterion 2" --depends-on <other-id>

## Loop, one task at a time
1. `bin/khoros claim <id> --worker @lead`
2. Implement it; run `bin/khoros verify`.
3. Commit (one commit per task).
4. `bin/khoros submit <id> --summary "<what changed, how verified>"`
5. `bin/khoros approve <id>` once the criteria hold.

For large or risky diffs, ask the `khoros-reviewer` agent for an independent review before approving. Give it the request and the diff range, not your reasoning, and fix what it reports.

Never start a second task while one is claimed. Leave the tree green and committed at the end of the session.
