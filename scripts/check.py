"""Run the project's checks. One command, one verdict.

    python scripts/check.py            every offline suite -- seconds, no services
    python scripts/check.py --smoke    + a two-scenario live smoke (A, B)
    python scripts/check.py --live     + the full live suite (A-H, 20-25 min)

The default needs nothing running: no Qdrant, no docling, no Groq key. Use it
after any edit. `--smoke` is the fast confidence check that the agent still
answers end to end; `--live` is the one to run before calling a phase done.

Each suite runs in its own process, so one blowing up cannot take the rest
with it, and the exit code is non-zero if any suite failed.
"""

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent

OFFLINE = [
    ("workflow", "check_workflow.py", []),
    ("database", "check_db.py", []),
    ("search", "check_search.py", []),
    ("observability", "check_observability.py", []),
]
SMOKE = [("live smoke", "check_workflow_live.py", ["--only", "A,B"])]
LIVE = [("live A-H", "check_workflow_live.py", [])]


def run(label: str, script: str, args: list[str]) -> bool:
    """Run one suite, streaming its output. True if it passed."""
    print(f"\n{'=' * 78}\n{label}  ({script})\n{'=' * 78}")
    # stderr is captured and filtered, not discarded: the reranker prints a
    # progress bar there that drowns the results, but Python also writes
    # TRACEBACKS there -- a suite that crashes must say why, or the summary
    # shows a bare FAIL with nothing to act on.
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    kept = [
        line
        for line in completed.stderr.splitlines()  # also splits the bar's \r
        if line.strip() and "Loading weights" not in line
    ]
    if kept:
        print("\n".join(kept))
    return completed.returncode == 0


def main() -> int:
    args = sys.argv[1:]
    suites = list(OFFLINE)
    # --live subsumes --smoke: the full suite already contains A and B, so
    # combining the flags must not run them twice.
    if "--live" in args:
        suites += LIVE
    elif "--smoke" in args:
        suites += SMOKE

    unknown = [a for a in args if a not in ("--smoke", "--live")]
    if unknown:
        print(f"Unknown option(s): {' '.join(unknown)}\n")
        print(__doc__)
        return 2

    results = [(label, run(label, script, extra)) for label, script, extra in suites]

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    for label, passed in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")

    failed = [label for label, passed in results if not passed]
    if failed:
        print(f"\n{len(failed)} suite(s) failed: {', '.join(failed)}")
        return 1
    print(f"\nAll {len(results)} suite(s) passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
