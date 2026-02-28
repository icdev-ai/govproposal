# Proposal Lifecycle — 7-Phase Shipley Workflow

> End-to-end government proposal management from opportunity discovery to post-submission learning.

---

## Pipeline Overview

```
MONITOR → QUALIFY → CAPTURE → DRAFT → REVIEW → PRODUCE → LEARN
   ↑                                                        |
   └────────────── Continuous Feedback Loop ─────────────────┘
```

---

## Phase 0: Opportunity Intelligence (Monitor)

**Goal:** Discover and track relevant government opportunities.

**Tools:**
- `tools/monitor/sam_scanner.py` — Scan SAM.gov for opportunities by NAICS, set-aside, agency
- `tools/monitor/opportunity_scorer.py` — Score opportunity-company fit (0-100)
- `tools/monitor/pipeline_manager.py` — Track pipeline stages, advance opportunities

**Args:** `args/proposal_config.yaml` (SAM.gov API key, polling interval, NAICS filters)

**Output:** Scored opportunities in pipeline with fit assessment.

---

## Phase 1: Qualification (Go/No-Go)

**Goal:** Decide whether to pursue an opportunity using structured scoring.

**Tools:**
- `tools/monitor/opportunity_scorer.py --go-no-go` — 7-dimension weighted decision

**Args:** `args/scoring_config.yaml` — Dimension weights:
| Dimension | Weight |
|-----------|--------|
| Customer Relationship | 0.20 |
| Technical Fit | 0.20 |
| Past Performance | 0.15 |
| Competitive Position | 0.15 |
| Vehicle Access | 0.10 |
| Clearance Compliance | 0.10 |
| Strategic Value | 0.10 |

**Gate:** Score ≥ 70 = GO, 50-69 = CONDITIONAL, < 50 = NO-GO

---

## Phase 2: Capture Management

**Goal:** Build competitive advantage before RFP release.

**Tools:**
- `tools/capture/win_theme_generator.py` — Generate discriminating win themes
- `tools/capture/teaming_engine.py` — Suggest teaming partners based on capability gaps
- `tools/capture/customer_intel.py` — Agency intelligence and relationship history
- `tools/capture/black_hat_review.py` — Simulate competitor strategies
- `tools/competitive/price_to_win.py` — Estimate competitive pricing from FPDS data
- `tools/competitive/fpds_analyzer.py` — Historical award analysis by agency/NAICS
- `tools/competitive/competitor_tracker.py` — Track competitor capabilities and wins

**Context:** `context/naics/` (classification codes), `context/far_dfars/` (regulatory requirements)

---

## Phase 3: Content Generation (Draft)

**Goal:** Create compliant, compelling proposal content.

**Tools:**
- `tools/proposal/section_parser.py` — Parse Section L/M requirements from solicitation
- `tools/proposal/compliance_matrix.py` — Auto-generate compliance traceability matrix
- `tools/proposal/content_drafter.py` — AI-assisted section drafting with KB retrieval
- `tools/proposal/proposal_assembler.py` — Assemble sections into complete volumes
- `tools/knowledge/kb_manager.py` — Search/add knowledge base entries
- `tools/knowledge/past_performance.py` — Retrieve relevant past performance narratives
- `tools/knowledge/resume_manager.py` — Search resumes by clearance, skill, certification

**Hard Prompts:** `hardprompts/proposal/drafting.md` — LLM instructions for section drafting

**Args:** `args/llm_config.yaml` (model routing for content_drafting function)

**Volumes:**
- Volume I: Technical Approach
- Volume II: Management Approach
- Volume III: Past Performance
- Volume IV: Cost/Price

**CAG Integration:** Run `tools/cag/data_tagger.py` on all KB entries before use. Run `tools/cag/aggregation_monitor.py` after each section draft.

---

## Phase 4: Review Cycles

**Goal:** Validate proposal quality through structured review teams.

**Tools:**
- `tools/review/compliance_review.py` — **Pink Team**: Every Section L requirement addressed
- `tools/review/responsiveness_review.py` — **Red Team**: Evaluation criteria coverage, win themes
- `tools/review/win_theme_review.py` — **Gold Team**: Discriminators, customer focus, storytelling
- `tools/review/final_qc.py` — **White Team**: Formatting, cross-refs, page limits, fonts

**Hard Prompts:** `hardprompts/proposal/review.md` — LLM instructions for review analysis

**Args:** `args/review_config.yaml` — Criteria and thresholds per review color

**Gate:** Pink and Red team reviews MUST complete before production (see `args/security_gates.yaml`).

---

## Phase 5: Production

**Goal:** Format, validate, and package for submission.

**Tools:**
- `tools/production/template_engine.py` — Apply agency-specific document templates
- `tools/production/formatter.py` — Enforce formatting rules (fonts, margins, page limits)
- `tools/production/cross_ref_validator.py` — Validate internal cross-references and acronyms
- `tools/production/submission_packager.py` — Package volumes for electronic submission

**Context:** `context/templates/` — Agency-specific proposal templates

**Gate:** CAG alerts must be resolved, compliance matrix complete, all required volumes present.

---

## Phase 6: Post-Submission Learning

**Goal:** Capture lessons learned and improve future proposals.

**Tools:**
- `tools/learning/debrief_capture.py` — Record debrief outcomes (win/loss/no-decision)
- `tools/learning/win_loss_analyzer.py` — Analyze patterns across win/loss history
- `tools/learning/pricing_calibrator.py` — Calibrate pricing models against actual awards

**Output:** Updated knowledge base, refined scoring weights, improved win themes.

---

## Security Gates

| Gate | Blocking Conditions |
|------|---------------------|
| CAG | `cag_status_quarantined`, `untagged_content_in_proposal` |
| Submission | `compliance_matrix_incomplete`, `cag_alerts_unresolved`, `missing_required_volumes` |
| AI Security | `prompt_injection_defense_inactive`, `high_confidence_injection_unresolved`, `ai_bom_missing` |
| Knowledge Base | `untagged_kb_entries_used`, `unapproved_content_in_final` |
| Review | `pink_team_not_completed`, `red_team_not_completed` |

---

## Related Files

- **CLAUDE.md** — Full project architecture and command reference
- **goals/build_app.md** — ATLAS workflow for building features
- **goals/cag_workflow.md** — CAG 4-layer defense workflow
- **args/security_gates.yaml** — Gate threshold definitions
