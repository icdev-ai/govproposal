# CAG Workflow — Classification Aggregation Guard

> Prevent the mosaic effect: when individually unclassified data combines to create classified information (EO 13526 Section 1.7(e), DoDM 5200.01).

---

## Overview

The CAG is a 4-layer defense system that monitors, detects, and prevents inadvertent classification breaches during proposal assembly.

```
DATA TAGS → RULES ENGINE → AGGREGATION MONITOR → RESPONSE
```

---

## Layer 1: Data Tagging

**Goal:** Tag every piece of content with classification level and security categories before use.

**Tool:** `tools/cag/data_tagger.py`

**Usage:**
```bash
# Tag individual content
python tools/cag/data_tagger.py --content "..." --json

# Tag entire proposal
python tools/cag/data_tagger.py --tag-document --proposal-id "PROP-123" --json
```

**10 Security Categories:**
PERSONNEL, CAPABILITY, LOCATION, TIMING, PROGRAM, VULNERABILITY, METHOD, SCALE, SOURCE, RELATIONSHIP

**Hard Prompt:** `hardprompts/cag/classification_tagging.md`

**Rules:**
- ALL knowledge base entries MUST be tagged before use in proposals
- Tags include: classification level (U, CUI, C, S, TS) + security categories
- Untagged content triggers a blocking gate

---

## Layer 2: Rules Engine

**Goal:** Apply declarative aggregation rules to detect dangerous combinations.

**Tool:** `tools/cag/rules_engine.py`

**Usage:**
```bash
python tools/cag/rules_engine.py --check --proposal-id "PROP-123" --json
```

**Args:** `args/cag_rules.yaml` — Contains:
- Universal rules (always active)
- Organization-specific rules (per program/contract)
- Category combination thresholds

**Rule Types:**
- **Combination rules** — "If PERSONNEL + LOCATION + TIMING appear together, trigger ALERT"
- **Threshold rules** — "If ≥ 3 categories from {CAPABILITY, METHOD, VULNERABILITY} co-occur, trigger BLOCK"
- **Program-specific rules** — Custom rules loaded from SCG imports

---

## Layer 3: Aggregation Monitor

**Goal:** Real-time monitoring during proposal assembly to catch aggregation before export.

**Tool:** `tools/cag/aggregation_monitor.py`

**Usage:**
```bash
python tools/cag/aggregation_monitor.py --scan --proposal-id "PROP-123" --json
```

**Proximity Scoring:**
| Proximity | Weight |
|-----------|--------|
| Same sentence | 1.0x |
| Same paragraph | 0.9x |
| Same section | 0.7x |
| Same volume | 0.4x |
| Cross-volume | 0.2x |

**Cross-Proposal Tracking:**
- `tools/cag/exposure_register.py` — Tracks cumulative category exposure across ALL proposals
- Detects compilation risk when the same categories appear across multiple deliverables

---

## Layer 4: Response

**Goal:** Take appropriate action when aggregation is detected.

**Response Actions:**
| Severity | Action | Description |
|----------|--------|-------------|
| LOW-MEDIUM | ALERT | Advisory — recommend security officer review |
| HIGH | BLOCK | Prevent assembly/export, suggest redactions |
| CRITICAL | QUARANTINE | Spillage response — lock access, incident report |
| Any | SANITIZE | Automated redaction suggestions, generalized alternatives |

**Tool:** `tools/cag/response_handler.py`

**Usage:**
```bash
python tools/cag/response_handler.py --alerts --json
```

**Rules:**
- Security officer approval REQUIRED for any BLOCK or QUARANTINE override
- QUARANTINE events are logged to the append-only audit trail
- Sanitization suggestions are advisory — human must approve redactions

---

## SCG Integration

**Tool:** `tools/cag/scg_parser.py`

**Usage:**
```bash
python tools/cag/scg_parser.py --import --file /path/to/scg.pdf --json
```

**Context:** `context/scg/` — Security Classification Guide reference material

Imported SCG rules feed into Layer 2 (Rules Engine) as program-specific aggregation rules.

---

## When to Run CAG

1. **Before using KB content in proposals** — Tag all entries
2. **After each section draft** — Run aggregation monitor
3. **Before export or share** — Full scan (blocking gate)
4. **After SCG import** — Re-scan affected proposals
5. **Periodically** — Cross-proposal exposure register review

---

## Applicable Regulations

- **EO 13526** — Classified National Security Information (Section 1.7(e) — compilation/mosaic)
- **DoDM 5200.01** — Information Security Program
- **FAR 3.104** — Procurement Integrity Act
- **DFARS 204.73** — Safeguarding Covered Defense Information
- **NIST 800-171** — Protecting CUI in Nonfederal Systems

---

## Related Files

- **args/cag_rules.yaml** — Aggregation rule definitions
- **context/scg/** — Security Classification Guide references
- **hardprompts/cag/classification_tagging.md** — LLM tagging instructions
- **goals/proposal_lifecycle.md** — CAG integration points in the proposal lifecycle
