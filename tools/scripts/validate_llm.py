#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Validate and optionally patch llm_config.yaml against installed Ollama models.

Standalone tool — safe to run at any time, including before starting Flask.

Usage:
  python tools/scripts/validate_llm.py              # check only
  python tools/scripts/validate_llm.py --patch       # check + auto-fix
  python tools/scripts/validate_llm.py --list-models # just list installed Ollama models
  python tools/scripts/validate_llm.py --json        # machine-readable output
"""

import argparse
import json
import sys
import re
import urllib.request
import urllib.error
from pathlib import Path

# Windows cp1252 console can't render Unicode — force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import yaml
except ImportError:
    yaml = None

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LLM_CONFIG_PATH = BASE_DIR / "args" / "llm_config.yaml"

PREFERRED_OLLAMA_MODELS = [
    "qwen3:latest",
    "llama3.2:3b",
    "deepseek-r1:latest",
    "gemma3:latest",
    "llama3:latest",
]

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def get_ollama_models(base_url: str) -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as r:
            data = json.loads(r.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return None


def model_available(model_id: str, installed: list[str]) -> bool:
    if model_id in installed:
        return True
    base = model_id.split(":")[0]
    return any(m.split(":")[0] == base for m in installed)


def load_config() -> dict:
    if yaml is None:
        return {}
    if not LLM_CONFIG_PATH.exists():
        return {}
    with open(LLM_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate(config: dict, installed: list[str]) -> dict:
    """Return validation report."""
    providers = config.get("providers", {})
    models = config.get("models", {})
    routing = config.get("routing", {})

    ollama_providers = {n for n, c in providers.items() if c.get("type") == "ollama"}
    bedrock_providers = {n for n, c in providers.items() if c.get("type") == "bedrock"}

    model_status = {}
    for model_name, model_cfg in models.items():
        prov = model_cfg.get("provider", "")
        model_id = model_cfg.get("model_id", "")
        if prov in ollama_providers:
            available = model_available(model_id, installed)
            model_status[model_name] = {
                "type": "ollama",
                "model_id": model_id,
                "available": available,
                "provider": prov,
            }
        elif prov in bedrock_providers:
            model_status[model_name] = {
                "type": "bedrock",
                "model_id": model_id,
                "available": None,  # can't probe without AWS creds
                "provider": prov,
            }
        else:
            model_status[model_name] = {
                "type": "unknown",
                "model_id": model_id,
                "available": None,
                "provider": prov,
            }

    # Check routing chains for broken models
    chain_issues = []
    for func, route in routing.items():
        chain = route.get("chain", [])
        reachable = [m for m in chain if model_status.get(m, {}).get("available") is not False]
        if not reachable:
            chain_issues.append({
                "function": func,
                "chain": chain,
                "issue": "all models in chain unavailable",
            })

    return {
        "models": model_status,
        "chain_issues": chain_issues,
        "ollama_installed": installed,
    }


def patch_config(report: dict) -> int:
    """Auto-fix broken Ollama model IDs. Returns number of patches applied."""
    installed = report["ollama_installed"]
    if not installed:
        return 0

    # Pick best replacement
    replacement = next(
        (m for m in PREFERRED_OLLAMA_MODELS if model_available(m, installed)),
        installed[0],
    )

    content = LLM_CONFIG_PATH.read_text(encoding="utf-8")
    patches = 0
    for model_name, info in report["models"].items():
        if info["type"] == "ollama" and info["available"] is False:
            bad_id = info["model_id"]
            pattern = rf'(model_id:\s*["\']?){re.escape(bad_id)}(["\']?)'
            new_content = re.sub(pattern, rf'\g<1>{replacement}\g<2>', content)
            if new_content != content:
                content = new_content
                patches += 1
                print(f"  {YELLOW}patched{RESET} {model_name}: {bad_id!r} → {replacement!r}")

    if patches:
        LLM_CONFIG_PATH.write_text(content, encoding="utf-8")

    return patches


def print_report(report: dict, installed: list[str] | None):
    models = report["models"]
    chain_issues = report["chain_issues"]

    print(f"\n{BOLD}Ollama{RESET}")
    if installed is None:
        print(f"  {RED}✗{RESET} Ollama not reachable — start with: ollama serve")
    else:
        print(f"  {GREEN}✓{RESET} {len(installed)} model(s) installed")
        for m in installed:
            print(f"    • {m}")

    print(f"\n{BOLD}LLM Config Models{RESET}")
    for name, info in models.items():
        mtype = info["type"]
        mid = info["model_id"]
        avail = info["available"]
        if mtype == "ollama":
            if avail:
                symbol = f"{GREEN}✓{RESET}"
                note = ""
            else:
                symbol = f"{RED}✗{RESET}"
                note = f"  {RED}← not installed{RESET}"
        elif mtype == "bedrock":
            symbol = f"{CYAN}~{RESET}"
            note = f"  (bedrock — cannot probe without AWS creds)"
        else:
            symbol = f"{YELLOW}?{RESET}"
            note = ""
        print(f"  {symbol} {BOLD}{name}{RESET} [{mtype}] {mid}{note}")

    if chain_issues:
        print(f"\n{BOLD}Routing Chain Issues{RESET}")
        for ci in chain_issues:
            print(f"  {RED}✗{RESET} {ci['function']}: {ci['chain']} — {ci['issue']}")
    else:
        print(f"\n  {GREEN}✓{RESET} All routing chains have at least one reachable model")


def main():
    parser = argparse.ArgumentParser(description="Validate llm_config.yaml against Ollama")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--patch", action="store_true",
                        help="Auto-fix unavailable Ollama model IDs in llm_config.yaml")
    parser.add_argument("--list-models", action="store_true",
                        help="List installed Ollama models and exit")
    parser.add_argument("--json", action="store_true", dest="json_out")
    args = parser.parse_args()

    installed = get_ollama_models(args.ollama_url)

    if args.list_models:
        if installed is None:
            print("Ollama not reachable", file=sys.stderr)
            sys.exit(1)
        if args.json_out:
            print(json.dumps(installed))
        else:
            for m in installed:
                print(m)
        return

    config = load_config()
    if not config:
        print("Could not load llm_config.yaml — check PyYAML is installed and file exists",
              file=sys.stderr)
        sys.exit(1)

    report = validate(config, installed or [])
    report["ollama_reachable"] = installed is not None

    if args.json_out:
        print(json.dumps(report, indent=2))
        return

    print_report(report, installed)

    broken = [n for n, i in report["models"].items()
              if i["type"] == "ollama" and i["available"] is False]

    if broken:
        if args.patch:
            n = patch_config(report)
            if n:
                print(f"\n  {GREEN}✓{RESET} Patched {n} model(s) in llm_config.yaml")
            else:
                print(f"\n  {YELLOW}⚠{RESET} Nothing to patch (no installed models found)")
        else:
            print(f"\n  {YELLOW}⚠{RESET} Run with --patch to auto-fix model IDs")
        sys.exit(1)
    else:
        print(f"\n  {GREEN}✓{RESET} All Ollama models are valid\n")


if __name__ == "__main__":
    main()
