#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    candidates = []
    configured = os.environ.get("PROJECT_CONTINUITY_CLI")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path.home() / ".codex" / "skills" / "project-continuity" / "scripts" / "project_continuity.py",
            Path("/Users/xuyufan/Documents/蒸馏技能/project-continuity/scripts/project_continuity.py"),
        ]
    )
    for path in candidates:
        if path.is_file():
            os.execv(sys.executable, [sys.executable, str(path), *sys.argv[1:]])
    print(
        "project-continuity CLI is not installed; expected ~/.codex/skills/project-continuity/scripts/project_continuity.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
