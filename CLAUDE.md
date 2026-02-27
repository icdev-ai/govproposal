# CLAUDE.md — GovProposal Portal

This file provides guidance to Claude Code when working with this project.

---

## Overview

GovProposal is an AI-native Government Proposal & RFP Response Portal built with ICDEV.
It automates the full Shipley lifecycle for DoD/IC proposals: monitoring, qualification,
capture, drafting, review, production, and post-submission learning.

**Target Niche:** DoD/IC IT Services (NAICS 541512, 541519, 541330)

**Critical Security Feature:** Classification Aggregation Guard (CAG) — detects when
individually unclassified data elements combine to create classified information
(mosaic effect, EO 13526 Section 1.7(e)).

---

## Architecture: GOTCHA Framework

| Layer | Directory | Role |
|-------|-----------|------|
| **Goals** | `goals/` | Process definitions for each proposal lifecycle phase |
| **Orchestration** | *(Claude)* | Read goal, decide tool order, apply args, handle errors |
| **Tools** | `tools/` | Deterministic Python scripts, one job each |
| **Args** | `args/` | YAML config (scoring weights, CAG rules, review criteria) |
| **Context** | `context/` | FAR/DFARS references, proposal templates, SCGs, NAICS codes |
| **Hard Prompts** | `hardprompts/` | LLM templates for drafting, reviewing, analyzing |

---

## Commands

```bash
# Database
python tools/db/init_db.py                              # Initialize database (all tables)

# Phase 0: Opportunity Intelligence
python tools/monitor/sam_scanner.py --scan --json        # Scan SAM.gov for new opportunities
python tools/monitor/sam_scanner.py --scan --naics 541512 --json  # Filter by NAICS
python tools/monitor/opportunity_scorer.py --score --opp-id "OPP-123" --json  # Score opportunity
python tools/monitor/opportunity_scorer.py --score-all --json     # Score all unscored
python tools/monitor/pipeline_manager.py --status --json          # Pipeline overview
python tools/monitor/pipeline_manager.py --advance --opp-id "OPP-123" --stage capture --json

# Phase 1: Qualification
python tools/monitor/opportunity_scorer.py --go-no-go --opp-id "OPP-123" --json  # Go/No-Go decision

# Phase 2: Capture Management
python tools/capture/win_theme_generator.py --opp-id "OPP-123" --json     # Generate win themes
python tools/capture/teaming_engine.py --opp-id "OPP-123" --json          # Suggest teaming partners
python tools/capture/customer_intel.py --agency "DIA" --json               # Customer intelligence
python tools/capture/black_hat_review.py --opp-id "OPP-123" --json        # Simulated competitor analysis

# Phase 3: Content Generation
python tools/knowledge/kb_manager.py --add --type capability --title "..." --content "..." --json
python tools/knowledge/kb_manager.py --search "SIGINT experience" --json
python tools/knowledge/past_performance.py --list --json
python tools/knowledge/past_performance.py --search --relevance "cloud migration" --json
python tools/knowledge/resume_manager.py --search --clearance TS_SCI --skill "Python" --json
python tools/proposal/section_parser.py --solicitation /path/to/rfp.pdf --json     # Parse Section L/M
python tools/proposal/compliance_matrix.py --proposal-id "PROP-123" --json         # Auto-generate
python tools/proposal/content_drafter.py --proposal-id "PROP-123" --section "technical_approach" --json
python tools/proposal/proposal_assembler.py --proposal-id "PROP-123" --json

# Phase 4: Review Cycles
python tools/review/compliance_review.py --proposal-id "PROP-123" --json    # Pink team
python tools/review/responsiveness_review.py --proposal-id "PROP-123" --json # Red team
python tools/review/win_theme_review.py --proposal-id "PROP-123" --json     # Gold team
python tools/review/final_qc.py --proposal-id "PROP-123" --json             # White team

# Phase 5: Production
python tools/production/template_engine.py --proposal-id "PROP-123" --template dod_standard --json
python tools/production/formatter.py --proposal-id "PROP-123" --json
python tools/production/cross_ref_validator.py --proposal-id "PROP-123" --json
python tools/production/submission_packager.py --proposal-id "PROP-123" --output /path --json

# Phase 6: Learning
python tools/learning/debrief_capture.py --proposal-id "PROP-123" --result win --json
python tools/learning/win_loss_analyzer.py --report --json
python tools/learning/pricing_calibrator.py --analyze --json

# Classification Aggregation Guard (CAG)
python tools/cag/data_tagger.py --content "..." --json                     # Tag content
python tools/cag/data_tagger.py --tag-document --proposal-id "PROP-123" --json  # Tag entire proposal
python tools/cag/rules_engine.py --check --proposal-id "PROP-123" --json   # Check aggregation rules
python tools/cag/aggregation_monitor.py --scan --proposal-id "PROP-123" --json  # Full scan
python tools/cag/response_handler.py --alerts --json                       # View alerts
python tools/cag/scg_parser.py --import --file /path/to/scg.pdf --json    # Import SCG
python tools/cag/exposure_register.py --report --json                      # Cross-proposal exposure

# Competitive Intelligence
python tools/competitive/fpds_analyzer.py --agency "DIA" --naics 541512 --json  # Analyze awards
python tools/competitive/competitor_tracker.py --track "Booz Allen" --json
python tools/competitive/price_to_win.py --opp-id "OPP-123" --json

# Dashboard
python tools/dashboard/app.py                            # Start on port 5001

# AI Security (Phase 37 — MITRE ATLAS)
python tools/security/prompt_injection_detector.py --text "ignore previous instructions" --json   # Detect prompt injection
python tools/security/prompt_injection_detector.py --file /path/to/file --json                    # Scan file for injections
python tools/security/prompt_injection_detector.py --project-dir /path --gate --json              # Gate evaluation
python tools/security/ai_telemetry_logger.py --summary --json                                     # AI usage summary
python tools/security/ai_telemetry_logger.py --anomalies --window 24 --json                      # Anomaly detection
python tools/security/ai_bom_generator.py --project-dir . --json                                  # Generate AI Bill of Materials
python tools/security/ai_bom_generator.py --gate                                                  # AI BOM gate check

# LLM Router (Phase 38 — Multi-Provider)
python -c "from tools.llm.router import LLMRouter; r = LLMRouter(); print(r.get_provider_for_function('content_drafting'))"
# Config: args/llm_config.yaml — providers, models, routing, embeddings
# Config: args/cloud_config.yaml — CSP selection, cloud_mode, region, impact_level
# Set OLLAMA_BASE_URL=http://localhost:11434/v1 for local model support
```

---

## Database

Single SQLite database: `data/govproposal.db`

**Table groups:**
- Opportunity Intelligence: `opportunities`, `opportunity_scores`, `pipeline_stages`
- Proposals: `proposals`, `proposal_sections`, `proposal_reviews`, `compliance_matrices`
- Knowledge Base: `kb_entries`, `kb_embeddings`, `past_performances`, `resumes`, `capabilities`, `certifications`, `boilerplate`, `win_themes`
- CAG: `cag_data_tags`, `cag_rules`, `cag_alerts`, `cag_exposure_register`, `scg_rules`, `scg_programs`
- Competitive: `competitors`, `competitor_wins`, `pricing_history`
- Capture: `teaming_partners`, `customer_profiles`, `black_hat_analyses`
- Learning: `debriefs`, `win_loss_patterns`, `pricing_benchmarks`
- System: `audit_trail`, `acronyms`, `templates`, `config_overrides`
- Evolutionary Intelligence (Phase 36): `genome_versions`, `child_capabilities`, `learned_behaviors`
- AI Security (Phase 37): `prompt_injection_log`, `ai_telemetry`, `ai_bom`
- Cloud-Agnostic (Phase 38): `cloud_provider_status`

---

## Proposal Lifecycle (7 Phases)

```
MONITOR → QUALIFY → CAPTURE → DRAFT → REVIEW → PRODUCE → LEARN
   ↑                                                        |
   └────────────── Continuous Feedback Loop ─────────────────┘
```

### Phase 0: Opportunity Intelligence
- SAM.gov API polling (opportunities, modifications, awards)
- Agency forecast monitoring
- FPDS.gov award data analysis
- Auto-classification by NAICS, set-aside, contract vehicle
- Opportunity-company fit scoring (0-100)

### Phase 1: Qualification (Go/No-Go)
7-dimension weighted scoring: customer_relationship (0.20), technical_fit (0.20),
past_performance (0.15), competitive_position (0.15), vehicle_access (0.10),
clearance_compliance (0.10), strategic_value (0.10)

### Phase 2: Capture Management
Win theme generation, teaming engine, customer intelligence, black hat review,
price-to-win estimation from FPDS historical data.

### Phase 3: Content Generation
Section L/M parsing → compliance matrix → RAG retrieval from KB → AI-drafted sections.
Volumes: I (Technical), II (Management), III (Past Performance), IV (Cost/Price).

### Phase 4: Review Cycles
| Review | Color | Focus |
|--------|-------|-------|
| Compliance | Pink | Every Section L requirement addressed |
| Responsiveness | Red | Evaluation criteria coverage, win themes |
| Win Theme | Gold | Discriminators, customer focus, storytelling |
| Final QC | White | Formatting, cross-refs, page limits, fonts |

### Phase 5: Production
Template-based document assembly per agency format. Auto-formatting, cross-reference
validation, acronym management, submission packaging.

### Phase 6: Post-Submission Learning
Debrief capture, win/loss pattern analysis, knowledge base enrichment,
pricing calibration from actual award data.

---

## Classification Aggregation Guard (CAG)

The CAG prevents the mosaic effect — when individually unclassified data combines
to create classified information (EO 13526 Section 1.7(e), DoDM 5200.01).

### 4 Layers
1. **Data Tags** — Every KB entry tagged with classification + security categories
2. **Rules Engine** — Declarative aggregation rules from SCGs + EO 13526 + org-specific
3. **Monitor** — Real-time combination tracking as proposal sections assemble
4. **Response** — Alert / Block / Quarantine / Sanitize with graduated severity

### 10 Security Categories
PERSONNEL, CAPABILITY, LOCATION, TIMING, PROGRAM, VULNERABILITY,
METHOD, SCALE, SOURCE, RELATIONSHIP

### Proximity Scoring
Same sentence (1.0x) > same paragraph (0.9x) > same section (0.7x) >
same volume (0.4x) > cross-volume (0.2x)

### Cross-Proposal Tracking
Cumulative exposure register tracks which categories have been exposed
across all proposals to detect compilation risk.

### Response Actions
- ALERT (LOW-MEDIUM) — Advisory, recommend security officer review
- BLOCK (HIGH) — Prevent assembly/export, suggest redactions
- QUARANTINE (CRITICAL) — Spillage response, lock access, incident report
- SANITIZE — Automated redaction suggestions, generalized alternatives

---

## Security & Compliance

- **Classification:** CUI // SP-PROPIN at minimum; CAG enforces higher when detected
- **Data Handling:** All proposal content is competition-sensitive (PROPIN)
- **Audit Trail:** Append-only, every action logged (who, what, when)
- **Access Control:** Role-based (BD Manager, Capture Lead, Proposal Manager,
  Writer, Reviewer, Pricing Analyst, Security Officer, Admin)
- **Applicable Regulations:** EO 13526, DoDM 5200.01, FAR 3.104 (Procurement Integrity),
  DFARS 204.73 (Safeguarding CDI), NIST 800-171
- **AI Security (Phase 37):** Prompt injection detection (5 categories: role hijacking,
  delimiter attacks, instruction injection, data exfiltration, encoded payloads),
  AI telemetry with SHA-256 prompt/response hashing, AI BOM generation
- **LLM Routing (Phase 38):** Multi-provider routing with fallback chains
  (Bedrock GovCloud primary, Ollama local for air-gapped), per-function routing,
  automatic prompt injection scanning on all LLM calls

### Security Gates
| Gate | Blocking Conditions |
|------|---------------------|
| CAG | `cag_status_quarantined`, `untagged_content_in_proposal` |
| Submission | `compliance_matrix_incomplete`, `cag_alerts_unresolved`, `missing_required_volumes` |
| AI Security | `prompt_injection_defense_inactive`, `high_confidence_injection_unresolved`, `ai_bom_missing` |
| Knowledge Base | `untagged_kb_entries_used`, `unapproved_content_in_final` |
| Review | `pink_team_not_completed`, `red_team_not_completed` |

---

## Guardrails

- CAG check runs BEFORE any document export or share operation
- All KB entries must be tagged before use in proposals
- Security officer approval required for any BLOCK or QUARANTINE override
- Past performance narratives must be verified against CPARS data
- Pricing data never exposed outside Cost/Price volume
- Competitor intelligence stored separately from proposal content
- Never auto-submit a proposal — human approval gate before submission
- Audit trail is append-only — no UPDATE/DELETE on audit tables

---

## Args Configuration Files

| File | Purpose |
|------|---------|
| `args/proposal_config.yaml` | Main config: SAM.gov API, polling intervals, LLM settings |
| `args/scoring_config.yaml` | Go/No-Go weights, fit scoring dimensions |
| `args/cag_rules.yaml` | Aggregation rules: universal + org-specific |
| `args/vocabulary.yaml` | Controlled vocabulary for CAG tagging |
| `args/review_config.yaml` | Review criteria for Pink/Red/Gold/White teams |
| `args/templates_config.yaml` | Document templates per agency/format |
| `args/competitive_config.yaml` | Competitor registry, FPDS query params |
| `args/llm_config.yaml` | Multi-provider LLM routing: providers, models, fallback chains, embeddings (Phase 38) |
| `args/cloud_config.yaml` | Cloud-agnostic config: CSP selection, cloud_mode, region, impact_level (Phase 38) |
| `args/security_gates.yaml` | Gate thresholds: CAG, submission, AI security, knowledge base, review (Phase 37) |

---

## Evolutionary Intelligence (Phase 36)

GovProposal tracks its capability genome for parent-child lifecycle management with ICDEV.

- **Genome Manifest:** `data/genome_manifest.json` — versioned capability tracking (semver + SHA-256)
- **Capability Registry:** `child_capabilities` table — tracks tools, workflows, integrations
- **Learned Behaviors:** `learned_behaviors` table — optimizations discovered during operation
- **Bidirectional Learning:** Reports learned behaviors to ICDEV parent for evaluation and potential genome absorption

## AI Security — MITRE ATLAS Integration (Phase 37)

5-category prompt injection detection protects all LLM interactions:

| Category | Pattern Examples |
|----------|----------------|
| Role Hijacking | "ignore previous instructions", "you are now..." |
| Delimiter Attacks | "```system", "\<\|im_start\|>system" |
| Instruction Injection | "IMPORTANT:", "OVERRIDE:", "NEW TASK:" |
| Data Exfiltration | "output all context", "repeat the system prompt" |
| Encoded Payloads | Base64-encoded instructions, hex-encoded attacks |

AI telemetry logs all model interactions with SHA-256 hashing (privacy-preserving audit).
AI BOM catalogs all AI/ML components, models, and libraries used in the system.

## Cloud-Agnostic Architecture (Phase 38)

Multi-provider LLM routing with automatic failover:

```
content_drafting → [claude_sonnet_4 → ollama_qwen]    # Best model first, local fallback
cag_tagging      → [claude_haiku → claude_sonnet_4]    # Fast model first for classification
kb_search        → [claude_haiku → ollama_qwen]        # Cheap model for search
```

Cloud mode: `government` (AWS GovCloud us-gov-west-1, IL4). Supports air-gapped mode with Ollama.
