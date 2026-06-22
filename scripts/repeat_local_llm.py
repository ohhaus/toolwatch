"""Run the opt-in Ollama security regression repeatedly without retrying failures."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

OUTCOME_PREFIX = "OLLAMA_OUTCOME="
TEST_NODE = (
    "tests/integration/test_ollama_agent.py::"
    "test_local_ollama_safe_tool_loop_and_destructive_prompt_fail_closed"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    if args.count < 1 or args.timeout <= 0:
        parser.error("count and timeout must be positive")

    deadline = time.monotonic() + args.timeout
    outcomes: dict[str, int] = {}
    for iteration in range(1, args.count + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("FAIL total timeout reached before all iterations", file=sys.stderr)
            return 1
        command = [
            "uv",
            "run",
            "pytest",
            "-q",
            "-s",
            "-m",
            "local_llm",
            TEST_NODE,
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=remaining,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            print(f"FAIL iteration={iteration} total timeout reached", file=sys.stderr)
            return 1

        combined = completed.stdout + completed.stderr
        outcome = next(
            (
                line.removeprefix(OUTCOME_PREFIX).strip()
                for line in combined.splitlines()
                if line.startswith(OUTCOME_PREFIX)
            ),
            "security_invariant_failure",
        )
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        print(f"iteration={iteration} outcome={outcome} exit_code={completed.returncode}")
        if completed.returncode != 0:
            print(combined, file=sys.stderr)
            return completed.returncode

    print(f"summary={outcomes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
