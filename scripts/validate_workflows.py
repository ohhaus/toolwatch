"""Validate release workflow invariants without executing GitHub Actions."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def main() -> int:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        document = yaml.safe_load(text)
        if not isinstance(document, dict):
            raise RuntimeError(f"{path} is not a workflow mapping")
        if "permissions" not in document or "concurrency" not in document:
            raise RuntimeError(f"{path} lacks explicit permissions/concurrency")
        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            raise RuntimeError(f"{path} lacks jobs")
        for name, job in jobs.items():
            if not isinstance(job, dict) or "timeout-minutes" not in job:
                raise RuntimeError(f"{path}:{name} lacks timeout-minutes")
        for action in re.findall(r"uses:\s*([^\s#]+)", text):
            if not PINNED_ACTION.fullmatch(action):
                raise RuntimeError(f"{path} has unpinned action: {action}")
        if re.search(r"\b(?:ollama\s+(?:serve|pull|run)|verify-ollama)\b", text.lower()):
            raise RuntimeError(f"{path} must not require Ollama")

    release = (WORKFLOWS / "release.yml").read_text()
    for required in (
        'tags:\n      - "v*"',
        "Validate tag matches package version",
        "make package-check",
        "docker build",
        "make sbom",
        "attest-build-provenance@",
        "gh release create",
    ):
        if required not in release:
            raise RuntimeError(f"release workflow lacks {required}")
    print("workflow validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
