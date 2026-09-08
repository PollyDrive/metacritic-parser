#!/usr/bin/env python3
"""PostToolUse hook: запускает тесты после каждого Edit/Write .py-файла."""
import json
import os
import subprocess
import sys


def main() -> None:
    data = json.load(sys.stdin)
    fp: str = data.get("tool_input", {}).get("file_path", "")

    if not fp.endswith(".py"):
        sys.exit(0)

    skip_patterns = [".venv", "migrations", "__pycache__", "alembic", "skills/", "/skills"]
    if any(s in fp for s in skip_patterns):
        sys.exit(0)

    cwd = os.getcwd()
    if not fp.startswith(cwd):
        sys.exit(0)

    rel = fp[len(cwd) + 1:]

    if rel.startswith("tests/"):
        test_args = [fp]
    elif rel.startswith((
        "metacritic_game_tracker/domain/",
        "metacritic_game_tracker/shared/",
        "metacritic_game_tracker/infrastructure/",
        "metacritic_game_tracker/application/",
        "scripts/",
    )):
        test_args = [os.path.join(cwd, "tests/")]
    else:
        sys.exit(0)

    result = subprocess.run(
        ["poetry", "run", "pytest"] + test_args + ["-q", "--tb=short", "--no-header"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )

    out = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"Tests FAILED after editing {rel}:\n\n{out}",
            }
        }))
        sys.exit(2)


if __name__ == "__main__":
    main()
