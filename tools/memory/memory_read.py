#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Memory Read — loads MEMORY.md and recent daily logs for session context.

Usage:
    python tools/memory/memory_read.py --format markdown
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MEMORY_FILE = BASE_DIR / "memory" / "MEMORY.md"
LOGS_DIR = BASE_DIR / "memory" / "logs"


def read_memory(fmt: str = "markdown") -> str:
    """Read MEMORY.md and recent logs."""
    parts = []

    # Read MEMORY.md
    if MEMORY_FILE.exists():
        parts.append(MEMORY_FILE.read_text(encoding="utf-8"))
    else:
        parts.append("# No MEMORY.md found\n")

    # Read today's log
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_log = LOGS_DIR / f"{today}.md"
    if today_log.exists():
        parts.append(f"\n---\n\n## Today's Log ({today})\n\n")
        parts.append(today_log.read_text(encoding="utf-8"))

    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Memory Read")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    args = parser.parse_args()

    output = read_memory(args.format)
    print(output)


if __name__ == "__main__":
    main()
