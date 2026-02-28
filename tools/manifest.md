# Tools Manifest — GovProposal

> Master index of all tool modules. Check before writing new scripts.

---

## Opportunity Intelligence (`tools/monitor/`)

| Tool | Script | Purpose |
|------|--------|---------|
| SAM Scanner | `sam_scanner.py` | Scan SAM.gov API for new opportunities, filter by NAICS/set-aside |
| Opportunity Scorer | `opportunity_scorer.py` | 7-dimension weighted fit scoring, Go/No-Go decision |
| Pipeline Manager | `pipeline_manager.py` | Pipeline stage tracking, advancement, status overview |

## Capture Management (`tools/capture/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Win Theme Generator | `win_theme_generator.py` | Generate discriminators and win themes from opportunity data |
| Teaming Engine | `teaming_engine.py` | Suggest teaming partners based on gap analysis; `--discover` for SAM.gov entity search |
| Black Hat Review | `black_hat_review.py` | Simulated competitor analysis, weakness identification |

## Customer Intelligence (`tools/capture/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Customer Intel | `customer_intel.py` | Agency-level customer intelligence gathering |

## Proposal Content (`tools/proposal/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Section Parser | `section_parser.py` | Parse Section L/M from solicitation PDFs; `--shred` mode extracts ALL sections (C/F/H/J/L/M) |
| Compliance Matrix | `compliance_matrix.py` | Auto-generate compliance traceability matrix |
| Content Drafter | `content_drafter.py` | AI-drafted proposal sections with RAG retrieval |
| Proposal Assembler | `proposal_assembler.py` | Assemble complete proposal from drafted sections |

## Review (`tools/review/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Review Engine | `review_engine.py` | Unified review engine (Pink/Red/Gold/White teams) |

## Production (`tools/production/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Template Engine | `template_engine.py` | Document templates per agency format |
| Formatter | `formatter.py` | Auto-formatting (fonts, margins, page limits) |
| Cross-Ref Validator | `cross_ref_validator.py` | Cross-reference and acronym validation |
| Submission Packager | `submission_packager.py` | Package proposal for submission with checklists; `--format docx` for Word export |

## Knowledge Base (`tools/knowledge/`)

| Tool | Script | Purpose |
|------|--------|---------|
| KB Manager | `kb_manager.py` | Add, update, tag knowledge base entries |
| KB Search | `kb_search.py` | Search KB with keyword + semantic retrieval |
| Past Performance | `past_performance.py` | Past performance narrative search and management |
| Resume Manager | `resume_manager.py` | Personnel resume search by clearance/skill/cert |

## Learning (`tools/learning/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Debrief Capture | `debrief_capture.py` | Capture post-submission debrief data |
| Win/Loss Analyzer | `win_loss_analyzer.py` | Pattern analysis across win/loss outcomes |
| Pricing Calibrator | `pricing_calibrator.py` | Calibrate pricing from actual award data |
| Analytics Engine | `analytics_engine.py` | Unified win-rate analytics with multi-dimensional FPDS correlation |

## Classification Aggregation Guard (`tools/cag/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Data Tagger | `data_tagger.py` | Tag content with classification + security categories |
| Rules Engine | `rules_engine.py` | Evaluate aggregation rules (EO 13526 + SCG + org) |
| Aggregation Monitor | `aggregation_monitor.py` | Real-time combination tracking during proposal assembly |
| Exposure Register | `exposure_register.py` | Cross-proposal cumulative exposure tracking |
| SCG Parser | `scg_parser.py` | Import Security Classification Guides |
| Response Handler | `response_handler.py` | Alert/Block/Quarantine/Sanitize actions |

## Competitive Intelligence (`tools/competitive/`)

| Tool | Script | Purpose |
|------|--------|---------|
| FPDS Analyzer | `fpds_analyzer.py` | Analyze FPDS.gov award data by agency/NAICS |
| Competitor Tracker | `competitor_tracker.py` | Track competitor wins, capabilities, pricing |
| Price-to-Win | `price_to_win.py` | Estimate competitive pricing from historical data |

## CRM (`tools/crm/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Contact Manager | `contact_manager.py` | Customer contact relationship tracking |
| Vendor Assessor | `vendor_assessor.py` | Vendor qualification and assessment |

## ERP / Workforce (`tools/erp/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Employee Manager | `employee_manager.py` | Employee records and availability |
| LCAT Manager | `lcat_manager.py` | Labor category mapping and rate management |
| LinkedIn Importer | `linkedin_importer.py` | Import personnel data from LinkedIn profiles |
| Skills Tracker | `skills_tracker.py` | Track employee skills, certifications, clearances |

## RFX AI Engine (`tools/rfx/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Document Processor | `document_processor.py` | Process uploaded solicitation documents |
| RAG Service | `rag_service.py` | Retrieval-augmented generation for proposal content |
| Exclusion Service | `exclusion_service.py` | Mask sensitive content before LLM, merge after |
| Requirement Extractor | `requirement_extractor.py` | Extract shall/must/should from solicitation text |
| Research Service | `research_service.py` | Research competitor and market data for proposals |
| LLM Bridge | `llm_bridge.py` | LLM integration layer for RFX pipeline |
| Compliance | `compliance.py` | RFX compliance: CUI marking, NIST AU mapping |
| Fine-tune Runner | `finetune_runner.py` | Unsloth/LoRA fine-tuning for proposal models |

## AI Security (`tools/security/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Prompt Injection Detector | `prompt_injection_detector.py` | 5-category prompt injection detection |
| AI Telemetry Logger | `ai_telemetry_logger.py` | SHA-256 hashed AI usage audit logging |
| AI BOM Generator | `ai_bom_generator.py` | AI Bill of Materials generation |

## LLM Routing (`tools/llm/`)

| Tool | Script | Purpose |
|------|--------|---------|
| LLM Router | `router.py` | Multi-provider routing with fallback chains |
| Provider ABC | `provider.py` | Abstract base class for LLM providers |
| Bedrock Provider | `bedrock_provider.py` | AWS Bedrock GovCloud provider |
| OpenAI Provider | `openai_provider.py` | OpenAI-compatible provider (Ollama, vLLM) |

## Infrastructure & System (`tools/`)

| Tool | Script | Purpose |
|------|--------|---------|
| DB Init | `db/init_db.py` | Initialize govproposal.db with all tables |
| DB Migrate (ERP/CRM) | `db/migrate_erp_crm.py` | ERP/CRM table migration |
| DB Migrate (Pricing) | `db/migrate_pricing.py` | Pricing table migration |
| DB Migrate (RFX) | `db/migrate_rfx.py` | RFX table migration |
| Seed Demo Data | `db/seed_demo_data.py` | Seed demonstration data |
| Seed Pricing Data | `db/seed_pricing_data.py` | Seed pricing benchmark data |
| Audit Logger | `audit/audit_logger.py` | Append-only audit trail writer (NIST AU) |
| Memory Read | `memory/memory_read.py` | Load MEMORY.md and daily logs for session context |
| Health Check | `testing/health_check.py` | System component health verification |
| Proposal MCP Server | `mcp/proposal_server.py` | MCP server exposing proposal tools |
| Platform Compat | `compat/__init__.py` | Cross-platform compatibility utilities |
| RFX Pipeline | `scripts/rfx_pipeline.py` | End-to-end RFX processing pipeline |
| LLM Validator | `scripts/validate_llm.py` | Validate LLM provider connectivity |

## Dashboard (`tools/dashboard/`)

| Tool | Script | Purpose |
|------|--------|---------|
| Dashboard App | `app.py` | Flask web dashboard on port 5001 |

## Agent (`tools/agent/`)

| File | Purpose |
|------|---------|
| `cards/orchestrator.json` | A2A agent card for GovProposal orchestrator |

---

## Adding New Tools

1. Create the script in the appropriate `tools/<domain>/` directory
2. Add an entry to this manifest
3. Update `CLAUDE.md` commands section if the tool has a CLI
4. Update relevant goal files if the tool changes a workflow
