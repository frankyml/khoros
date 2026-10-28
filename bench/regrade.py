#!/usr/bin/env python3
"""
Regrade a results directory from the saved diffs, without re-running any agent.

For every run: rebuild the task workspace (fixture or repository base commit), apply the run's saved patch
(`patches/<key>.diff`), and grade it again with the current grader. Use it after a grading fix. The previous
results are kept as `results.jsonl.<timestamp>.bak`; agent metrics (cost, tokens, transcript-derived behaviour)
are left untouched, only grading fields are replaced. Do not run it while run_ab.py is still writing the same dir.

Usage: python3 bench/regrade.py bench/results/<dir>
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchlib import ARMS, build_workspace, grade, load_tasks  # noqa: E402

GRADE_FIELDS = ("success", "hidden_passed", "hidden_expected", "hidden_pass_rate", "hidden_failed_ids", "visible_ok",
                "visible_failed_ids", "f2p_methods_passed", "agent_suite_ok", "agent_suite_tests",
                "code_files_changed", "lines_added", "lines_removed", "other_files_changed", "other_files")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir", type=Path)
    args = parser.parse_args()

    path = args.results_dir / "results.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks = {t.id: t for t in load_tasks()}
    changed = 0
    with tempfile.TemporaryDirectory(prefix="regrade-") as tmp:
        for rec in records:
            patch = (args.results_dir / "patches" / f"{rec['key']}.diff").resolve()  # git apply runs inside ws
            task = tasks.get(rec["task"])
            if task is None or not patch.exists():
                continue
            ws = Path(tmp) / rec["key"]
            build_workspace(task, ARMS["vanilla"], ws)  # arm files don't affect grading
            if patch.stat().st_size:
                res = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=ws, capture_output=True, text=True)
                if res.returncode != 0:
                    print(f"  {rec['key']}: patch does not apply ({res.stderr.strip()[:120]}); kept old grade")
                    shutil.rmtree(ws, ignore_errors=True)
                    continue
            graded = grade(task, ws)
            graded.pop("_patch", None)
            before = (rec.get("success"), rec.get("hidden_pass_rate"))
            rec.update({k: graded[k] for k in GRADE_FIELDS if k in graded})
            rec["regraded_at"] = datetime.now().isoformat(timespec="seconds")
            changed += before != (rec["success"], rec["hidden_pass_rate"])
            print(f"  {rec['key']:<44} success {before[0]} -> {rec['success']}, partial {before[1]} -> {rec['hidden_pass_rate']}")
            shutil.rmtree(ws, ignore_errors=True)

    backup = path.with_name(f"results.jsonl.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(path, backup)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    print(f"{len(records)} records, {changed} changed; previous results in {backup.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
