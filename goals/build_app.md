# Build App — ATLAS Workflow

> Standard build process for GovProposal features and enhancements.

---

## ATLAS Steps

### A — Architect

Define the approach before writing code.

1. Read the requirement or feature request
2. Identify which tools already exist (check `tools/` directories)
3. Identify which args control behavior (check `args/` YAML files)
4. Design the data model (DB tables, fields, relationships)
5. Define the API surface (routes, parameters, responses)
6. Consider CAG implications — does this feature handle classified or competition-sensitive data?

**Tools:** `tools/proposal/`, `tools/cag/`, `tools/db/`
**Args:** `args/proposal_config.yaml`, `args/cag_rules.yaml`, `args/security_gates.yaml`

### T — Trace

Map requirements to existing context and patterns.

1. Check `context/far_dfars/` for applicable regulations
2. Check `context/templates/` for document structure requirements
3. Reference `args/scoring_config.yaml` for evaluation criteria
4. Map to security gates in `args/security_gates.yaml`

**Context:** `context/far_dfars/`, `context/templates/`, `context/naics/`, `context/scg/`

### L — Link

Connect components and configure behavior.

1. Wire new tools to appropriate args configuration
2. Set up database tables via `tools/db/init_db.py`
3. Add dashboard routes if UI is needed
4. Configure LLM routing in `args/llm_config.yaml` if AI features are involved

**Args:** `args/llm_config.yaml`, `args/cloud_config.yaml`

### A — Assemble

Build and integrate.

1. Write deterministic Python tools (one job each, no LLM thinking)
2. Add routes to `tools/dashboard/app.py` if dashboard integration needed
3. Write tests in `tests/`
4. Run CAG check on any content that touches proposal data

**Tools:** All `tools/` directories
**Testing:** `pytest tests/ -v`

### S — Stress-test

Validate before declaring done.

1. Run all tests: `pytest tests/ -v`
2. Run security gates: check `args/security_gates.yaml` thresholds
3. Run CAG scan on affected proposals: `python tools/cag/aggregation_monitor.py --scan`
4. Verify dashboard renders correctly (if UI changes)
5. Check audit trail captures the new actions

---

## GOTCHA Layer Mapping

| ATLAS Step | GOTCHA Layer |
|------------|--------------|
| Architect | Goals (define the process) |
| Trace | Context (reference patterns) |
| Link | Args (environment setup) |
| Assemble | Tools (execution) |
| Stress-test | Orchestration (AI validates) |

---

## Common Mistakes

1. **Skipping Trace** — Building without checking FAR/DFARS compliance requirements
2. **No CAG check** — Assembling proposal content without running aggregation monitor
3. **Hardcoding config** — Putting scoring weights or thresholds in code instead of args/
4. **No audit trail** — Forgetting to log actions to the append-only audit table
5. **Skipping review gates** — Exporting proposals without completing Pink/Red team reviews

---

## Related Files

- **Args:** `args/proposal_config.yaml`, `args/scoring_config.yaml`, `args/cag_rules.yaml`
- **Context:** `context/far_dfars/`, `context/templates/`
- **Hard Prompts:** `hardprompts/proposal/`, `hardprompts/cag/`
