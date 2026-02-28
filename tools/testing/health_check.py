#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Health Check — verifies GovProposal system components are operational.

Usage:
    python tools/testing/health_check.py
    python tools/testing/health_check.py --json
"""

import argparse
import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def check_health() -> dict:
    """Run health checks on key system components."""
    checks = {}

    # Database
    db_path = BASE_DIR / "data" / "govproposal.db"
    checks["database"] = {
        "status": "ok" if db_path.exists() else "missing",
        "path": str(db_path),
    }
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            tables = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            conn.close()
            checks["database"]["tables"] = tables
        except Exception as e:
            checks["database"]["status"] = "error"
            checks["database"]["error"] = str(e)

    # Memory
    memory_path = BASE_DIR / "memory" / "MEMORY.md"
    checks["memory"] = {
        "status": "ok" if memory_path.exists() else "missing",
    }

    # Goals
    goals_dir = BASE_DIR / "goals"
    goal_files = list(goals_dir.glob("*.md")) if goals_dir.exists() else []
    checks["goals"] = {
        "status": "ok" if len(goal_files) >= 2 else "incomplete",
        "count": len(goal_files),
    }

    # Args
    args_dir = BASE_DIR / "args"
    arg_files = list(args_dir.glob("*.yaml")) if args_dir.exists() else []
    checks["args"] = {
        "status": "ok" if arg_files else "missing",
        "count": len(arg_files),
    }

    # Tools
    tools_dir = BASE_DIR / "tools"
    tool_dirs = [d for d in tools_dir.iterdir() if d.is_dir()] if tools_dir.exists() else []
    checks["tools"] = {
        "status": "ok" if len(tool_dirs) >= 3 else "incomplete",
        "directories": len(tool_dirs),
    }

    overall = all(c["status"] == "ok" for c in checks.values())
    return {"overall": "healthy" if overall else "degraded", "checks": checks}


def main():
    parser = argparse.ArgumentParser(description="Health Check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = check_health()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Overall: {result['overall'].upper()}")
        for name, check in result["checks"].items():
            print(f"  {name}: {check['status']}")


if __name__ == "__main__":
    main()
