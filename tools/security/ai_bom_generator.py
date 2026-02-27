#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN (Proprietary Business Information)
# Distribution: D
# POC: GovProposal System Administrator
"""AI Bill of Materials (AI BOM) Generator.

Catalogs all AI/ML components in the project: LLM providers, embedding models,
AI framework dependencies, and MCP server configurations.

Adapted from ICDEV Phase 37 (MITRE ATLAS Integration).

CLI:
    python tools/security/ai_bom_generator.py --project-dir . --json
    python tools/security/ai_bom_generator.py --gate --json
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "govproposal.db"

# AI framework packages to detect in requirements files
AI_FRAMEWORK_PACKAGES = {
    "openai", "anthropic", "boto3", "ibm-watsonx-ai",
    "google-generativeai", "langchain", "langchain-core",
    "langchain-community", "transformers", "torch", "tensorflow",
    "numpy", "scikit-learn", "scipy", "pandas", "keras",
    "onnx", "onnxruntime", "sentence-transformers", "tiktoken",
    "tokenizers", "safetensors", "accelerate", "peft",
    "huggingface-hub", "diffusers",
}


class AIBOMGenerator:
    """Generate an AI Bill of Materials cataloging AI/ML components."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH

    def _scan_llm_config(self, project_dir: Path) -> List[Dict]:
        """Scan args/llm_config.yaml for LLM and embedding model components."""
        components = []
        config_path = project_dir / "args" / "llm_config.yaml"
        if not config_path.exists():
            # Fall back to proposal_config.yaml llm section
            config_path = project_dir / "args" / "proposal_config.yaml"
        if not config_path.exists():
            return components

        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except ImportError:
            config = self._parse_yaml_fallback(config_path)
        except Exception:
            return components

        # LLM config format
        models = config.get("models", {})
        for model_name, model_info in models.items():
            if not isinstance(model_info, dict):
                continue
            components.append({
                "component_type": "model",
                "component_name": model_name,
                "version": model_info.get("model_id", "unknown"),
                "provider": model_info.get("provider", "unknown"),
                "license": "proprietary",
                "source": str(config_path),
            })

        # Direct llm section (proposal_config.yaml format)
        llm = config.get("llm", {})
        if llm:
            for key in ("model", "drafting_model", "review_model"):
                model_id = llm.get(key)
                if model_id:
                    components.append({
                        "component_type": "model",
                        "component_name": key,
                        "version": model_id,
                        "provider": llm.get("provider", "unknown"),
                        "license": "proprietary",
                        "source": str(config_path),
                    })
            embed_model = llm.get("embedding_model")
            if embed_model:
                components.append({
                    "component_type": "model",
                    "component_name": "embedding",
                    "version": embed_model,
                    "provider": llm.get("provider", "unknown"),
                    "license": "proprietary",
                    "source": str(config_path),
                })

        # Embeddings section
        embeddings = config.get("embeddings", {})
        for embed_name, embed_info in embeddings.get("models", {}).items():
            if not isinstance(embed_info, dict):
                continue
            components.append({
                "component_type": "model",
                "component_name": f"embedding:{embed_name}",
                "version": embed_info.get("model_id", "unknown"),
                "provider": embed_info.get("provider", "unknown"),
                "license": "proprietary",
                "source": str(config_path),
            })

        return components

    def _parse_yaml_fallback(self, config_path: Path) -> Dict:
        """Minimal YAML parser fallback when pyyaml unavailable."""
        result: Dict = {"models": {}, "llm": {}, "embeddings": {"models": {}}}
        try:
            content = config_path.read_text(encoding="utf-8")
        except Exception:
            return result

        current_section = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if not line.startswith(" ") and stripped.endswith(":"):
                section_name = stripped.rstrip(":")
                if section_name in ("models", "llm", "embeddings"):
                    current_section = section_name
                else:
                    current_section = None
                continue
            if current_section == "llm" and line.startswith("  "):
                match = re.match(r'\s+(\w+):\s*"?([^"]+)"?', line)
                if match:
                    result["llm"][match.group(1)] = match.group(2).strip()

        return result

    def _scan_requirements(self, project_dir: Path) -> List[Dict]:
        """Scan requirements.txt for AI framework dependencies."""
        components = []
        req_file = project_dir / "requirements.txt"
        if not req_file.exists():
            return components

        try:
            with open(req_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue

                    match = re.match(
                        r'^([a-zA-Z0-9._-]+)\s*(?:([<>=!~]+)\s*([a-zA-Z0-9.*_-]+))?',
                        line,
                    )
                    if not match:
                        continue

                    name = match.group(1).lower().replace("_", "-")
                    version = match.group(3) or "unspecified"

                    if name not in AI_FRAMEWORK_PACKAGES:
                        continue

                    components.append({
                        "component_type": "library",
                        "component_name": name,
                        "version": version,
                        "provider": "pypi",
                        "license": self._infer_license(name),
                        "source": str(req_file),
                    })
        except Exception:
            pass

        return components

    def _scan_mcp_config(self, project_dir: Path) -> List[Dict]:
        """Scan .mcp.json for MCP server configurations."""
        components = []
        mcp_path = project_dir / ".mcp.json"
        if not mcp_path.exists():
            return components

        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            return components

        servers = config.get("mcpServers", {})
        for server_name, server_info in servers.items():
            if not isinstance(server_info, dict):
                continue
            command = server_info.get("command", "unknown")
            args_list = server_info.get("args", [])
            script = args_list[0] if args_list else "unknown"

            components.append({
                "component_type": "service",
                "component_name": server_name,
                "version": "1.0.0",
                "provider": f"{command}:{script}",
                "license": "proprietary",
                "source": str(mcp_path),
            })

        return components

    def _compute_hash(self, component_data: Dict) -> str:
        """Compute SHA-256 hash of component data for change detection."""
        key_fields = (
            f"{component_data.get('component_type', '')}"
            f"/{component_data.get('component_name', '')}"
            f"@{component_data.get('version', '')}"
            f":{component_data.get('provider', '')}"
        )
        return hashlib.sha256(key_fields.encode("utf-8")).hexdigest()

    def _assess_risk(self, component: Dict) -> str:
        """Assess risk level of an AI component."""
        comp_type = component.get("component_type", "")
        provider = component.get("provider", "").lower()
        version = component.get("version", "unspecified")
        name = component.get("component_name", "").lower()

        if comp_type == "model":
            if provider in ("bedrock", "anthropic", "openai", "gemini"):
                return "medium"
            if provider == "ollama":
                return "low"
            return "medium"

        if comp_type == "library" and version in ("unspecified", "unknown"):
            return "high"

        high_risk_libs = {"torch", "tensorflow", "transformers"}
        if name in high_risk_libs:
            return "medium"

        if comp_type == "service":
            return "medium"

        return "low"

    def _infer_license(self, package_name: str) -> str:
        """Infer license for known AI packages."""
        licenses = {
            "openai": "MIT", "anthropic": "MIT", "boto3": "Apache-2.0",
            "google-generativeai": "Apache-2.0", "langchain": "MIT",
            "transformers": "Apache-2.0", "torch": "BSD-3-Clause",
            "tensorflow": "Apache-2.0", "numpy": "BSD-3-Clause",
            "scikit-learn": "BSD-3-Clause", "tiktoken": "MIT",
            "ibm-watsonx-ai": "Apache-2.0",
        }
        return licenses.get(package_name, "unknown")

    def scan_project(self, project_dir: str) -> Dict:
        """Scan a project for all AI/ML components."""
        project_path = Path(project_dir)
        now = datetime.now(timezone.utc)
        all_components = []

        all_components.extend(self._scan_llm_config(project_path))
        all_components.extend(self._scan_requirements(project_path))
        all_components.extend(self._scan_mcp_config(project_path))

        for comp in all_components:
            comp["hash"] = self._compute_hash(comp)
            comp["risk_level"] = self._assess_risk(comp)

        type_counts = {}
        for comp in all_components:
            ctype = comp.get("component_type", "unknown")
            type_counts[ctype] = type_counts.get(ctype, 0) + 1

        return {
            "project_dir": str(project_path),
            "scan_date": now.isoformat(),
            "total_components": len(all_components),
            "type_counts": type_counts,
            "components": all_components,
        }

    def store_bom(self, components: List[Dict]) -> int:
        """Store AI BOM components in the database."""
        if not self.db_path.exists():
            return 0

        conn = sqlite3.connect(str(self.db_path))
        now = datetime.now(timezone.utc).isoformat()
        stored = 0

        for comp in components:
            comp_id = str(uuid.uuid4())
            try:
                conn.execute(
                    """INSERT INTO ai_bom
                       (id, component_type, component_name, version, provider,
                        license, risk_level, classification, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        comp_id,
                        comp.get("component_type", "library"),
                        comp.get("component_name", "unknown"),
                        comp.get("version", "unknown"),
                        comp.get("provider", "unknown"),
                        comp.get("license", "unknown"),
                        comp.get("risk_level", "medium"),
                        "CUI // SP-PROPIN",
                        now, now,
                    ),
                )
                stored += 1
            except sqlite3.IntegrityError:
                stored += 1

        conn.commit()
        conn.close()
        return stored

    def evaluate_gate(self) -> Dict:
        """Evaluate the AI BOM security gate."""
        blocking = []
        warnings = []

        if not self.db_path.exists():
            blocking.append("ai_bom_missing: Database not found")
            return {"pass": False, "gate": "ai_bom", "blocking_issues": blocking, "warnings": warnings}

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        row = conn.execute("SELECT COUNT(*) as cnt FROM ai_bom").fetchone()
        bom_count = row["cnt"] if row else 0

        if bom_count == 0:
            blocking.append("ai_bom_missing: No AI BOM entries found")

        risk_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM ai_bom WHERE risk_level IN ('critical', 'high')"
        ).fetchone()
        high_risk = risk_row["cnt"] if risk_row else 0
        if high_risk > 0:
            warnings.append(f"ai_bom_high_risk: {high_risk} component(s) with high/critical risk level")

        conn.close()

        return {
            "pass": len(blocking) == 0,
            "gate": "ai_bom",
            "total_components": bom_count,
            "high_risk_components": high_risk,
            "blocking_issues": blocking,
            "warnings": warnings,
        }


def main():
    parser = argparse.ArgumentParser(description="Generate AI Bill of Materials (AI BOM)")
    parser.add_argument("--project-dir", help="Path to project directory to scan")
    parser.add_argument("--gate", action="store_true", help="Evaluate AI BOM gate")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    generator = AIBOMGenerator()

    if args.gate:
        result = generator.evaluate_gate()
    elif args.project_dir:
        result = generator.scan_project(args.project_dir)
        generator.store_bom(result["components"])
    else:
        parser.print_help()
        return

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if args.gate:
            status = "PASS" if result["pass"] else "FAIL"
            print(f"AI BOM Gate: {status}")
            print(f"  Components: {result.get('total_components', 0)}")
        else:
            print(f"AI BOM scanned: {result['total_components']} components")
            for comp in result["components"]:
                print(f"  [{comp['risk_level']:8s}] {comp['component_type']:10s} {comp['component_name']}")


if __name__ == "__main__":
    main()
