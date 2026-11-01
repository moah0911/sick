#!/usr/bin/env python3
"""Graded end-to-end evals for Sick (real LLM, real acceptance checks).

Runs four tasks in temp workspaces via the sick CLI and reports
completion, iterations (LLM/tool counts from the audit log), and wall
time per task. This is how "can it do bigger tasks?" gets a measured
answer per model instead of an opinion.

Usage (with a provider key configured):
    uv run python scripts/eval_suite.py [--timeout 600]

Tasks:
  hello      — write hello.py that prints hello, run it
  pomodoro   — pomodoro timer module + tests, tests must pass
  crud       — tiny in-memory CRUD module from a spec, with tests
  refactor   — rename a function across a 3-file fixture, tests green
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TASKS = [
    (
        "hello",
        "Write hello.py that prints hello, then run it to verify.",
        lambda ws: (ws / "hello.py").is_file() and "hello" in (ws / "hello.py").read_text(),
    ),
    (
        "pomodoro",
        "Write pomodoro.py implementing a PomodoroTimer class with start(), pause(), "
        "reset(), and tick(seconds) that counts down 25 minutes, plus test_pomodoro.py "
        "with pytest tests. Run the tests and make them pass.",
        lambda ws: (ws / "pomodoro.py").is_file() and (ws / "test_pomodoro.py").is_file(),
    ),
    (
        "crud",
        "Write store.py with an in-memory Store class (create/read/update/delete/list) "
        "plus test_store.py with pytest tests covering all five operations. Run tests.",
        lambda ws: (ws / "store.py").is_file() and (ws / "test_store.py").is_file(),
    ),
]


def _refactor_fixture(ws: Path) -> None:
    (ws / "calc.py").write_text("def compute_total(items):\n    return sum(items)\n")
    (ws / "report.py").write_text("from calc import compute_total\n\ndef show(items):\n    return compute_total(items)\n")
    (ws / "test_calc.py").write_text(
        "from calc import compute_total\nfrom report import show\n\n"
        "def test_total():\n    assert compute_total([1, 2]) == 3\n    assert show([3]) == 3\n"
    )


def run_task(name: str, prompt: str, check, timeout: int, setup=None) -> dict:
    ws = Path(tempfile.mkdtemp(prefix=f"sick-eval-{name}-"))
    if setup:
        setup(ws)
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "sick.cli", prompt, "--workspace", str(ws)],
        capture_output=True, text=True, timeout=timeout,
    )
    elapsed = time.monotonic() - started
    tools = 0
    audit = ws / ".sick" / "audit.jsonl"
    if audit.is_file():
        tools = sum(1 for _ in audit.read_text().splitlines())
    passed = False
    try:
        passed = bool(check(ws))
    except Exception:
        passed = False
    # for code tasks, acceptance includes their own tests passing when present
    tests = list(ws.glob("test_*.py"))
    if passed and tests:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *map(str, tests)],
            capture_output=True, text=True, cwd=ws, timeout=120,
        )
        passed = r.returncode == 0
    return {
        "task": name, "passed": passed, "seconds": round(elapsed, 1),
        "tool_calls": tools, "cli_exit": proc.returncode, "workspace": str(ws),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    results = [run_task(n, p, c, args.timeout) for n, p, c in TASKS]
    results.append(run_task(
        "refactor",
        "Rename compute_total to calculate_total everywhere (definition, imports, tests). Run the tests.",
        lambda ws: "calculate_total" in (ws / "calc.py").read_text() and "compute_total" not in (ws / "report.py").read_text(),
        args.timeout, setup=_refactor_fixture,
    ))
    print(f"{'task':<10} {'pass':<6} {'secs':>7} {'tools':>6}")
    for r in results:
        print(f"{r['task']:<10} {str(r['passed']):<6} {r['seconds']:>7} {r['tool_calls']:>6}  {r['workspace']}")
    done = sum(1 for r in results if r["passed"])
    print(f"\n{done}/{len(results)} tasks passed")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
