# GovProposal UX Audit Report
**Date:** 2026-02-26
**Scope:** All 30 pages + core workflows (AI Draft, HITL Review, Pricing Calculator, Exclusion Masking)
**Method:** Playwright browser automation — full page sweep + interactive workflow testing
**Goal:** iPhone-level intuitiveness for non-technical users

---

## Executive Summary

GovProposal has a solid structural foundation — every page loads, the navigation is consistent, and the data model is rich. However, the platform currently reads like a developer's internal tool rather than a business app. Three issues need urgent attention before non-technical users can succeed:

1. **The HITL Review workflow is broken** — Accept/Reject buttons return HTTP 500. The central AI proposal review feature is non-functional.
2. **Raw developer CLI commands are exposed** on four pages as user-facing guidance.
3. **Government/compliance jargon is unexplained** throughout — users will hit acronyms like CAG, HITL, LCAT, DLR, G&A, FFP, T&M, PWIN, ZTA, OPSEC with no definitions.

---

## Bug Report (Must Fix Before User Testing)

### BUG-01 — CRITICAL: HITL Review API returns HTTP 500
- **Pages affected:** All AI Proposal detail pages
- **Action:** Click "✓ Accept", "✎ Accept with Revisions", or "✗ Reject" on any AI-generated section
- **Result:** `POST /api/rfx/ai/sections/<uuid>/review → 500 INTERNAL SERVER ERROR`
- **Impact:** The core AI proposal review workflow is completely non-functional. Users cannot accept or reject AI-generated content.
- **Fix:** Debug `tools/rfx/rag_service.py` or the review route handler. Likely a missing DB column, incorrect session handling, or unhandled exception in the review endpoint.

### BUG-02 — HIGH: LLM error dumped raw into section content
- **Pages affected:** AI Proposal detail (Generate Section)
- **Result:** When the LLM chain fails, the raw Python exception string appears as the section body: `[LLM error: All providers in chain ['claude_sonnet_4', 'ollama_qwen'] failed... {'message': "model 'qwen2.5-coder:14b' not found"...}]`
- **Impact:** Completely unreadable by non-technical users; exposes system internals.
- **Fix:** Catch LLM errors in the generate route and display a friendly message: *"AI generation is temporarily unavailable. Please try again or contact your system administrator."* Store the technical error in server logs only.

### BUG-03 — MEDIUM: Requirements page shows empty/malformed data
- **Page:** `/rfx/requirements`
- **Result:** All 4 rows show type "OTHER", empty req numbers, empty section, empty volume, empty requirement text — only a "LOW" priority badge and "✗ Open" status
- **Impact:** Page looks broken. Users see no value from it.
- **Fix:** Check the requirement extraction pipeline — the `requirement_text`, `req_number`, `section`, and `volume` fields appear not to be populated by the extractor.

---

## Severity 1 — Critical UX Failures (blocks non-technical users)

### UX-01: Raw CLI commands shown as user guidance
**Affected pages:**
| Page | CLI command exposed |
|------|-------------------|
| Opportunity detail → Qualification Scorecard | `python tools/monitor/opportunity_scorer.py --score --opp-id opp-disa-zt-001` |
| Knowledge Base (empty state) | `python tools/knowledge/kb_manager.py --add` |
| Core Capabilities (empty state) | `python tools/erp/skills_tracker.py --aggregate-capabilities` (appears TWICE) |
| LCAT Rate Cards (footer) | `python tools/erp/lcat_manager.py` |

**Impact:** A non-technical BD manager or capture manager will see these and have no idea what to do. Severely damages trust in the product.

**Fix:** Replace every CLI reference with either:
- A "Refresh Score" button (for Qualification Scorecard) that calls the API in the background
- An "+ Add" button or upload form (for empty states)
- Remove the footer CLI reference from LCAT cards entirely — the data is already rendered

---

## Severity 2 — High Priority UX Issues

### UX-02: Acronym/jargon overload with no tooltips
Non-technical users will encounter the following without any explanation:

**Proposal/Capture jargon:**
- `CAG` — Classification Aggregation Guard (shown as a nav menu item, column header, and page title)
- `HITL` — Human-in-the-Loop (shown in AI Proposals list subtitle)
- `PWIN` — Probability of Win (on opportunities list)
- `LCAT` — Labor Category
- `FFP` / `T&M` — contract types used throughout with no legend
- `CLIN` — Contract Line Item Number
- `PWS` / `SOW` / `RFP` / `RFI` — acquisition document types

**Pricing jargon:**
- `DLR` — Direct Labor Rate
- `G&A` — General & Administrative
- `ODC` — Other Direct Costs
- `Fringe` — fringe benefits rate
- `Wrap Rate` — fully-burdened rate multiplier
- `DLC` — Direct Labor Cost (column header in pricing scenarios)
- `Breakeven` — shown without context that it means "price with 0% profit"

**Compliance jargon:**
- `CUI // SP-PROPIN` — classification banner (appears top and bottom of EVERY page)
- `OPSEC`, `ZTA`, `FISMA`, `FedRAMP`, `IL4/IL5` — scattered across descriptions
- `UEI / CAGE code` — in the New Contact form (SAM.gov identifiers)

**Recommended fix:** Add a global tooltip system. Any abbreviation tagged with `data-glossary="LCAT"` should show a popover: *"Labor Category — the job classification used for pricing (e.g., Cloud Engineer Level II)."* A 1-day implementation with a JSON glossary file covers 90% of cases.

### UX-03: "0/?" notation in AI proposal stats is confusing
- The "Reqs Addressed" stat tile shows `0/?` — the `?` reads as broken data or an error.
- **Fix:** Show `0 / —` when requirements haven't been extracted yet, or show `0 requirements mapped` as plain text with a link: *"Extract requirements from your RFP documents to enable tracking."*

### UX-04: Kanban board cuts off after 4 columns
- The Proposals Kanban board shows Draft → Pink Review → Red Review → Gold Review, but the remaining columns (White Review, Final, Submitted, Awarded, Lost) are hidden without any visual scroll hint.
- Non-technical users won't know there are more columns.
- **Fix:** Add a faded right edge with a "→ scroll" arrow indicator, or collapse the review stages into a single expandable column group. Consider a horizontal scroll bar that's always visible.

### UX-05: Color-coded review stages (pink/red/gold) have no legend
- Proposal statuses like "gold review", "pink review", "red review" appear in the list, detail, and kanban with no explanation of what each color means.
- **Fix:** Add a "?" icon next to the status badge that reveals: *"Review stages: Pink → Red → Gold → White → Final. Each color requires sign-off before advancing."* A one-line legend in the Kanban header would also work.

### UX-06: "not indexed" document label is unexplained
- Documents in the AI Proposal sidebar show "not indexed" in orange with no call to action.
- Users don't know what indexing is, why it matters, or how to trigger it.
- **Fix:** Change to: *"⚠ Not processed yet — click to index"* with a button or link. Add a tooltip: *"Indexing extracts text from your RFP so the AI can reference it when generating proposal sections."*

### UX-07: Generate Section shows no progress feedback
- Clicking "⚡ Generate Section" submits the form and the page refreshes. There is no loading spinner, progress bar, or "Generating..." state during what could be a 10–30 second operation.
- **Fix:** Disable the button and show a spinner + message: *"AI is drafting your section… this takes 15–30 seconds."* Use AJAX or SSE so the user doesn't see a full page reload.

---

## Severity 3 — Medium Priority UX Issues

### UX-08: CAG (Classification Aggregation Guard) is unexplained
- "CAG Monitor" appears in the nav, the proposal list as a column, and on proposal detail pages. No non-technical user will understand what it means or why it matters.
- **Fix:** Rename the nav item to "Security Monitor" with a subtitle *"AI mosaic effect detection"*, or add a persistent info banner on the CAG page explaining it in one sentence: *"CAG automatically flags when your proposal could accidentally reveal classified information through the combination of multiple pieces of sensitive data."*

### UX-09: Analytics page all zeros looks broken
- Every metric on the Analytics page shows 0.0% — win rate gauge, pipeline value charts, identified patterns. It reads as a broken page rather than "no historical data yet."
- **Fix:** Show a visible empty state message with context: *"Win/loss data will appear here after your first proposal is marked Won or Lost. You have 5 proposals in progress."* Make the gauge start at a neutral/empty visual rather than showing "0.0%".

### UX-10: Empty states lack actionable "Add" buttons
- Knowledge Base, Capabilities, and Competitors pages show empty states with no way to add content from the UI.
- **Fix:** Add clear "+ Add" buttons or simple upload/entry forms inline. Even if the full data management is CLI-based, a basic form for the most common action (adding an entry) should exist in the UI.

### UX-11: Proposal detail — no way to add sections from the main tab
- The Proposal detail page (standard proposals, not AI) shows "No sections created yet" but there is no "Add Section" button visible — only an AI Draft button in a separate tab.
- **Fix:** Add an "+ Add Section" button directly on the sections empty state that links to the AI Draft or a manual section editor.

### UX-12: Fine-tuning page is developer-facing, not business-facing
- The page title "Fine-Tuning" and subtitle "Unsloth / LoRA adapter training — runs locally via Python subprocess" are entirely incomprehensible to non-technical users.
- The requirements banner lists raw pip packages (`unsloth, transformers, datasets, trl, peft`).
- **Fix:** Rename to "Train on Your Voice" or "AI Writing Style Training." Rewrite the description: *"Teach the AI to write in your company's proposal voice by training on your best accepted sections. Requires a GPU-enabled computer."* Keep the technical details in a collapsible "Advanced" section for the IT administrator.

### UX-13: Research page subtitle is developer jargon
- Subtitle: "SAM.gov • USASpending.gov • Web — 24h TTL cache"
- **Fix:** *"Search government contract databases and the web. Results are cached for 24 hours."*

### UX-14: HITL — no feedback when actions fail
- When Accept/Reject fails (500 error), the buttons simply remain active/clickable. The user has no idea the action failed. There is no toast notification, no error message, nothing.
- **Fix:** All AJAX actions need a response handler that shows either a success toast ("✓ Section accepted") or an error toast ("✗ Unable to save your review — please try again") with retry option.

### UX-15: Team detail page has many empty fields
- "Experience: — yrs" and "Education: —" appear for most team members. The Security Clearance shows "Status: Unknown."
- **Fix:** Either hide fields with no data (show only populated fields), or add inline edit buttons so users can fill them in directly from the UI.

---

## Severity 4 — Low Priority / Polish

### UX-16: File upload button is plain browser default
- The "Choose File" button on RFX Documents upload is an unstyled native browser control — visually inconsistent with the rest of the application.
- **Fix:** Style with a drag-and-drop zone: *"📎 Drop your RFP here or click to browse"* consistent with the app's design language.

### UX-17: CRM contact form has government-procurement-specific fields without explanation
- "SAM Entity ID" with placeholder "UEI or CAGE code" — only government contracting professionals will know what these are.
- **Fix:** Add a help text below: *"Optional: The Unique Entity Identifier from SAM.gov. Used to verify government contractors and teaming partners."*

### UX-18: Pricing page — "Rate Builder & Calculator" heading is cut short
- The heading reads "Rate Builder & Calculator Build a custom pricing scenario or load from a package above" — the heading and subtitle are merged together.
- **Fix:** Separate into `<h2>Rate Builder & Calculator</h2>` and `<p class="subtitle">Build a custom pricing scenario or load from a package above</p>`.

### UX-19: The "⚡ AI Draft" nav button looks like an action, not a page link
- The highlighted button in the nav looks like it will immediately trigger an AI draft. It's actually a link to the AI Proposals list page.
- **Fix:** Label it "AI Proposals" with a lightning bolt icon rather than "⚡ AI Draft" to clarify it's a section, not an action button.

### UX-20: Dashboard pipeline chart labels use contract-type jargon
- The pipeline health section shows "FFP" and "T&M" in charts without any legend.
- **Fix:** Add a legend: "FFP = Firm Fixed Price | T&M = Time & Materials".

---

## What Works Well (Keep)

| Feature | Notes |
|---------|-------|
| **Navigation** | Consistent top nav across all pages, active state highlighting works |
| **CUI classification banners** | Present on every page, top and bottom — compliant |
| **Exclusion masking** | Works flawlessly — 8/8 terms replaced correctly |
| **Pricing calculator** | "Use in Calculator" button auto-populates correctly, math is accurate |
| **Breadcrumb navigation** | AI Proposals → detail breadcrumb works |
| **Filter/search** | Team, CRM, and Opportunities filters work |
| **Pricing Scenarios page** | Portfolio summary with service-line breakdown is excellent |
| **CRM contact detail** | Log Interaction form is clean and functional |
| **Exclusion list grouping** | Grouped by type (Person/Location/etc.) is intuitive |
| **AI Proposal sidebar** | Win Themes + Requirements Coverage is valuable context |
| **Kanban board** | Visual pipeline is the right concept |
| **New Contact form** | Comprehensive but manageable |

---

## Top 5 Recommended Fixes (Prioritized for Impact)

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| **1** | Fix HITL Accept/Reject 500 error | Low (bug fix) | Critical — core feature broken |
| **2** | Replace all CLI commands with UI actions | Medium | High — damages trust immediately |
| **3** | Implement global acronym tooltip system | Medium | High — affects every page |
| **4** | Fix LLM error display (show friendly message) | Low | High — confuses users seeing stack traces |
| **5** | Add loading state to "Generate Section" | Low | High — users think nothing is happening |

---

## iPhone-Level UX Benchmark (Gap Analysis)

| iPhone Principle | Current State | Gap |
|-----------------|--------------|-----|
| **No learning curve** — actions are self-evident | CLI commands, unexplained acronyms, jargon-heavy labels | Large gap |
| **Feedback for every action** | No loading states, no success/failure toasts, silent 500 errors | Large gap |
| **Progressive disclosure** — complexity when needed | Fine-tuning technical details always visible | Medium gap |
| **Empty states guide you to the next step** | Empty states show CLI commands or blank pages | Large gap |
| **Errors are human-readable** | Raw Python exceptions in content areas | Large gap |
| **Everything works** | HITL review broken, requirements data empty | Critical gap |
| **Consistent visual language** | Navigation, cards, and tables are consistent | Small gap |
| **Fast, responsive** | Pages load quickly, no lag | No gap |

---

*Screenshots for all 30 pages saved to `playwright/screenshots/`.*
*Report generated: 2026-02-26 by Playwright UX audit.*
