"""Code-version stamp recorded with every dataset and experiment."""

from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any

from candle_intel.config.settings import PROJECT_ROOT


def code_version() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(  # noqa: S603 — fixed argv, no shell
                ["git", *args],  # noqa: S607 — git from PATH, fixed arguments
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    return {"git_commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]
