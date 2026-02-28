# GovProposal — Project Memory

## Project Identity

- **Name:** GovProposal — AI-native Government Proposal & RFP Response Portal
- **Parent:** ICDEV (Intelligent Coding Development)
- **Domain:** DoD/IC IT Services proposals (NAICS 541512, 541519, 541330)
- **Architecture:** GOTCHA Framework (6 layers) with 7-phase Shipley lifecycle
- **Database:** SQLite at `data/govproposal.db`
- **Dashboard:** Flask on port 5001

## Key Features

- 7-phase proposal lifecycle: Monitor → Qualify → Capture → Draft → Review → Produce → Learn
- Classification Aggregation Guard (CAG): 4-layer defense against mosaic effect
- Multi-provider LLM routing: Bedrock GovCloud + Ollama + OpenAI-compatible
- AI security: MITRE ATLAS prompt injection detection (5 categories)
- Append-only audit trail (NIST AU compliance)

## Tool Categories (19)

monitor, capture, proposal, review, production, learning, knowledge, cag, competitive, security, llm, dashboard, db, crm, erp, rfx, mcp, compat, scripts

## Security

- Classification: CUI // SP-PROPIN minimum; CAG enforces higher when detected
- 10 CAG categories: PERSONNEL, CAPABILITY, LOCATION, TIMING, PROGRAM, VULNERABILITY, METHOD, SCALE, SOURCE, RELATIONSHIP
- Applicable regulations: EO 13526, DoDM 5200.01, FAR 3.104, DFARS 204.73, NIST 800-171
- 5 security gates: CAG, Submission, AI Security, Knowledge Base, Review

## Preferences

- Always run CAG check before document export or share
- Audit trail is append-only — never UPDATE/DELETE
- Never auto-submit proposals — human approval required
- Past performance must be CPARS-verified before use
