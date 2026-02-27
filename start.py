#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Smart GovProposal startup script.

Automates the three failure modes hit in manual testing:
  1. Stale Flask processes holding port 5001 → ConnectionResetError
  2. llm_config.yaml pointing at an Ollama model that isn't installed
  3. Ollama not running at all (silent failure at generation time)

Usage:
  python start.py                   # validate + start Flask
  python start.py --port 5002       # override port
  python start.py --validate-only   # check without starting Flask
  python start.py --patch-models    # auto-fix model names in llm_config.yaml
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
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

BASE_DIR = Path(__file__).resolve().parent
LLM_CONFIG_PATH = BASE_DIR / "args" / "llm_config.yaml"
APP_PATH = BASE_DIR / "tools" / "dashboard" / "app.py"

# Preferred model priority when auto-patching (first available wins)
PREFERRED_OLLAMA_MODELS = [
    "qwen3:latest",
    "llama3.2:3b",
    "deepseek-r1:latest",
    "gemma3:latest",
    "llama3:latest",
]

GREEN = "\033[32m"
RED   = "\033[31m"
YELLOW = "\033[33m"
CYAN  = "\033[36m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def _ok(msg):   print(f"{GREEN}  ✓{RESET} {msg}")
def _warn(msg): print(f"{YELLOW}  ⚠{RESET} {msg}")
def _err(msg):  print(f"{RED}  ✗{RESET} {msg}")
def _info(msg): print(f"{CYAN}  →{RESET} {msg}")


# ── Port / Process Management ──────────────────────────────────────────────────

def find_pid_on_port(port: int) -> list[int]:
    """Return list of PIDs listening on the given port (Windows + Unix)."""
    pids = []
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        try:
                            pids.append(int(parts[-1]))
                        except ValueError:
                            pass
        else:
            out = subprocess.check_output(
                ["lsof", "-ti", f"tcp:{port}"], text=True, stderr=subprocess.DEVNULL
            )
            for p in out.strip().splitlines():
                try:
                    pids.append(int(p))
                except ValueError:
                    pass
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return list(set(pids))


def kill_port(port: int) -> bool:
    """Kill any process listening on port. Returns True if port was cleared."""
    pids = find_pid_on_port(port)
    if not pids:
        return True  # already free

    for pid in pids:
        _warn(f"Port {port} held by PID {pid} — terminating")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError) as e:
            _err(f"Could not kill PID {pid}: {e}")
            return False

    # Wait up to 3 seconds for port to free
    for _ in range(6):
        time.sleep(0.5)
        if not find_pid_on_port(port):
            _ok(f"Port {port} is now free")
            return True

    _err(f"Port {port} still in use after kill attempt")
    return False


# ── Ollama Probing ─────────────────────────────────────────────────────────────

def get_ollama_models(base_url: str = "http://localhost:11434") -> list[str] | None:
    """Return list of installed Ollama model names, or None if Ollama is unreachable."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return None


def normalize_model_name(name: str) -> str:
    """Normalize 'qwen3:latest' → 'qwen3:latest' (already canonical)."""
    return name.strip()


def model_available(model_id: str, installed: list[str]) -> bool:
    """Check if model_id matches any installed model (exact or prefix match)."""
    normalized = normalize_model_name(model_id)
    if normalized in installed:
        return True
    # Also match 'qwen3' against 'qwen3:latest'
    base = normalized.split(":")[0]
    return any(m.split(":")[0] == base for m in installed)


# ── LLM Config Validation / Patching ──────────────────────────────────────────

def load_llm_config() -> dict:
    if yaml is None:
        _warn("PyYAML not installed — skipping LLM config validation")
        return {}
    if not LLM_CONFIG_PATH.exists():
        _warn(f"LLM config not found at {LLM_CONFIG_PATH}")
        return {}
    with open(LLM_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_llm_config(config: dict, ollama_models: list[str]) -> list[tuple[str, str, str]]:
    """Validate ollama model entries against installed models.

    Returns list of (model_name, configured_id, issue) tuples for problems found.
    """
    issues = []
    providers = config.get("providers", {})
    models = config.get("models", {})

    # Find ollama-type provider names
    ollama_providers = {
        name for name, cfg in providers.items()
        if cfg.get("type") == "ollama"
    }

    for model_name, model_cfg in models.items():
        if model_cfg.get("provider") in ollama_providers:
            model_id = model_cfg.get("model_id", "")
            if not model_available(model_id, ollama_models):
                issues.append((model_name, model_id, "not installed"))

    return issues


def patch_llm_config(issues: list[tuple[str, str, str]],
                     ollama_models: list[str]) -> bool:
    """Auto-patch llm_config.yaml: replace broken model IDs with best available.

    Returns True if any patches were made.
    """
    if not issues or not ollama_models:
        return False

    # Pick best replacement from priority list
    replacement = None
    for pref in PREFERRED_OLLAMA_MODELS:
        if model_available(pref, ollama_models):
            replacement = pref
            break
    if replacement is None:
        replacement = ollama_models[0]  # fallback to first installed

    content = LLM_CONFIG_PATH.read_text(encoding="utf-8")
    patched = False
    for model_name, bad_id, _ in issues:
        # Replace the specific model_id line for this model entry
        pattern = rf'(model_id:\s*["\']?){re.escape(bad_id)}(["\']?)'
        new_content = re.sub(pattern, rf'\g<1>{replacement}\g<2>', content)
        if new_content != content:
            _info(f"  Patching {model_name}: {bad_id!r} → {replacement!r}")
            content = new_content
            patched = True

    if patched:
        LLM_CONFIG_PATH.write_text(content, encoding="utf-8")
        _ok(f"llm_config.yaml updated (patched {len(issues)} model(s))")

    return patched


# ── Flask Startup ──────────────────────────────────────────────────────────────

def wait_for_flask(port: int, timeout: float = 15.0) -> bool:
    """Poll until Flask responds on the given port. Returns True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=2
            ) as resp:
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def start_flask(port: int) -> subprocess.Popen:
    """Launch Flask in a subprocess. Returns the Popen object."""
    env = os.environ.copy()
    env["FLASK_PORT"] = str(port)
    # Load .env if python-dotenv available
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())

    proc = subprocess.Popen(
        [sys.executable, str(APP_PATH)],
        cwd=str(BASE_DIR),
        env=env,
    )
    return proc


# ── Main ───────────────────────────────────────────────────────────────────────

def run(args):
    port = args.port
    ollama_url = args.ollama_url

    print(f"\n{BOLD}GovProposal Smart Startup{RESET}  (port {port})\n")

    # ── Step 1: Port cleanup ───────────────────────────────────────────────────
    print(f"{BOLD}[1/3] Port check{RESET}")
    pids = find_pid_on_port(port)
    if pids:
        if args.no_kill:
            _warn(f"Port {port} in use by PID(s) {pids}. Pass --no-kill=false to auto-kill.")
        else:
            kill_port(port)
    else:
        _ok(f"Port {port} is free")

    # ── Step 2: Ollama validation ──────────────────────────────────────────────
    print(f"\n{BOLD}[2/3] Ollama model validation{RESET}")
    ollama_models = get_ollama_models(ollama_url)

    if ollama_models is None:
        _warn(f"Ollama not reachable at {ollama_url} — LLM generation will fall back to cloud providers")
        _warn("Start Ollama with: ollama serve")
    else:
        _ok(f"Ollama online — {len(ollama_models)} model(s) installed")
        for m in ollama_models:
            _info(f"  {m}")

        config = load_llm_config()
        if config:
            issues = validate_llm_config(config, ollama_models)
            if not issues:
                _ok("llm_config.yaml models all valid")
            else:
                for model_name, bad_id, reason in issues:
                    _warn(f"Model '{model_name}' → '{bad_id}' is {reason}")

                if args.patch_models or args.auto_patch:
                    patch_llm_config(issues, ollama_models)
                else:
                    _warn("Run with --patch-models to auto-fix, or edit args/llm_config.yaml manually")
                    _info(f"Available Ollama models: {', '.join(ollama_models)}")

    if args.validate_only:
        print(f"\n{BOLD}Validation complete.{RESET} (--validate-only, not starting Flask)\n")
        return 0

    # ── Step 3: Start Flask ────────────────────────────────────────────────────
    print(f"\n{BOLD}[3/3] Starting Flask{RESET}")

    if not APP_PATH.exists():
        _err(f"App not found: {APP_PATH}")
        return 1

    proc = start_flask(port)
    _info(f"Flask PID {proc.pid} started, waiting for readiness...")

    if wait_for_flask(port, timeout=20.0):
        _ok(f"GovProposal is ready → http://127.0.0.1:{port}")
        print()
    else:
        _warn("Flask didn't respond within 20s — it may still be starting")

    print(f"  Press {BOLD}Ctrl+C{RESET} to stop.\n")

    try:
        proc.wait()
    except KeyboardInterrupt:
        _info("Shutting down Flask...")
        proc.terminate()
        proc.wait(timeout=5)
        _ok("Stopped")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Smart GovProposal startup")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FLASK_PORT", 5001)))
    parser.add_argument("--ollama-url", default="http://localhost:11434",
                        help="Ollama base URL")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate Ollama models and exit without starting Flask")
    parser.add_argument("--patch-models", action="store_true",
                        help="Auto-fix llm_config.yaml if Ollama models are missing")
    parser.add_argument("--auto-patch", action="store_true",
                        help="Same as --patch-models (alias)")
    parser.add_argument("--no-kill", action="store_true",
                        help="Don't kill existing processes on the port")
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
