/**
 * GovProposal — Global Acronym Tooltip System
 * Auto-detects government contracting abbreviations in page text
 * and shows friendly plain-English definitions on hover.
 *
 * Zero dependencies. Air-gap safe.
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* Glossary — add new terms here only                                  */
  /* ------------------------------------------------------------------ */
  var GLOSSARY = {
    "CAG":     "Competitive Assessment Gate — a score (0–100) measuring how well your bid position compares to known competitors. Higher is better.",
    "HITL":    "Human-in-the-Loop — a checkpoint where a person reviews and approves AI-generated content before it's finalized.",
    "PWIN":    "Probability of Win — an estimate (0–100%) of how likely the company is to win a specific contract.",
    "LCAT":    "Labor Category — a job classification (e.g., Senior Engineer, Program Manager) that determines the billing rate for contract work.",
    "DLR":     "Direct Labor Rate — the base hourly wage paid to an employee, before benefits, overhead, and profit are added.",
    "FBR":     "Fully-Burdened Rate — the total cost per hour including salary, benefits, overhead, G&A, and profit margin. This is what gets billed to the government.",
    "G&A":     "General & Administrative — indirect overhead costs like HR, finance, and facilities that are spread across all contracts.",
    "OH":      "Overhead — indirect costs tied to a specific business unit or contract (e.g., lab space, equipment, supervision).",
    "Wrap":    "Wrap Rate — a multiplier applied to direct labor to get the fully-burdened rate. Example: a 1.85× wrap on a $50/hr salary = $92.50/hr billed.",
    "FFP":     "Firm Fixed Price — a contract type where the government pays a set price regardless of the contractor's actual costs.",
    "T&M":     "Time & Materials — a contract type where the government pays for actual labor hours plus the cost of materials.",
    "NAICS":   "North American Industry Classification System — a 6-digit code that categorizes the type of business or work being contracted.",
    "SAM":     "System for Award Management — the government's official vendor registration database. Companies must be registered in SAM to receive federal contracts.",
    "SAM.gov": "System for Award Management — the government's official vendor registration and contract opportunity database at sam.gov.",
    "RFP":     "Request for Proposal — a formal government solicitation asking vendors to submit detailed bids for a contract.",
    "RFQ":     "Request for Quote — a simplified solicitation for smaller or well-defined purchases.",
    "RFI":     "Request for Information — market research sent before a formal solicitation; responding does not mean you'll win a contract.",
    "SOW":     "Statement of Work — the section of a contract that defines exactly what the contractor must deliver.",
    "PWS":     "Performance Work Statement — similar to a SOW, but focused on outcomes (what must be achieved) rather than specific tasks (how to do it).",
    "CUI":     "Controlled Unclassified Information — sensitive government information that requires protection but is not classified. Examples: export-controlled data, personal info, law enforcement sensitive.",
    "ATO":     "Authority to Operate — official government approval allowing an IT system to process data at a given security level.",
    "IDIQ":    "Indefinite Delivery / Indefinite Quantity — a contract vehicle for a range of services over time, with a maximum ceiling value. Work is ordered via task orders.",
    "GSA":     "General Services Administration — the federal agency that manages government-wide procurement vehicles like GSA Schedules.",
    "FSS":     "Federal Supply Schedule — a GSA-managed catalog of pre-approved vendors and pricing for common goods and services.",
    "CMMC":    "Cybersecurity Maturity Model Certification — a DoD requirement that defense contractors must meet specific cybersecurity standards.",
    "RAG":     "Retrieval-Augmented Generation — an AI technique that searches a knowledge base for relevant context before generating a response, making answers more accurate.",
    "LLM":     "Large Language Model — an AI system (like GPT-4 or Claude) that can read, write, and reason about text.",
    "SSP":     "System Security Plan — a document describing how a system implements required security controls.",
    "POAM":    "Plan of Action & Milestones — a tracking document for known security weaknesses and the plan to fix them.",
    "SBOM":    "Software Bill of Materials — a complete inventory of all software components in a system, used for vulnerability tracking.",
    "STIG":    "Security Technical Implementation Guide — DoD security configuration standards for specific software and hardware.",
    "BD":      "Business Development — the team or activities focused on identifying and pursuing new contract opportunities.",
    "KO":      "Contracting Officer — the government official with legal authority to award and administer contracts.",
    "COR":     "Contracting Officer Representative — the government technical person who monitors contractor performance day-to-day.",
    "PM":      "Program Manager — the person responsible for delivering a project on schedule, within budget, and meeting requirements.",
    "PoP":     "Period of Performance — the time period during which contract work must be completed.",
    "B&P":     "Bid and Proposal — the internal cost (not billable) of preparing a bid response.",
    "SDVOSB":  "Service-Disabled Veteran-Owned Small Business — a set-aside category for businesses majority-owned by service-disabled veterans.",
    "WOSB":    "Women-Owned Small Business — a set-aside category for businesses majority-owned by women.",
    "HUBZone": "Historically Underutilized Business Zone — a set-aside for companies in economically distressed areas.",
    "FPDS":    "Federal Procurement Data System — the government's central repository of federal contract award data, useful for market research and pricing benchmarks.",
    "FPDS-NG": "Federal Procurement Data System — Next Generation. The government's central repository of federal contract award data.",
    "IL2":     "Impact Level 2 — DoD cloud security tier for publicly releasable information (no CUI).",
    "IL4":     "Impact Level 4 — DoD cloud security tier for Controlled Unclassified Information (CUI).",
    "IL5":     "Impact Level 5 — DoD cloud security tier for CUI requiring higher protection (National Security Systems).",
    "IL6":     "Impact Level 6 — DoD cloud security tier for classified information up to SECRET.",
    "SBIR":    "Small Business Innovation Research — a competitive grant program funding R&D at small businesses.",
    "STTR":    "Small Business Technology Transfer — similar to SBIR but requires a formal partnership with a research institution.",
    "OTA":     "Other Transaction Authority — a flexible contracting mechanism used for prototype and R&D work, not subject to standard FAR rules.",
    "FAR":     "Federal Acquisition Regulation — the primary set of rules governing the government's purchasing process.",
    "DFARS":   "Defense Federal Acquisition Regulation Supplement — additional rules for DoD procurement beyond the FAR.",
    "BAA":     "Broad Agency Announcement — an open solicitation for research proposals across a wide range of topics.",
    "SB":      "Small Business — a company that meets SBA size standards and may qualify for set-aside contracts.",
    "SBA":     "Small Business Administration — the federal agency that certifies small business status and runs set-aside programs.",
    "CONUS":   "Continental United States — the 48 contiguous states (excludes Alaska, Hawaii, and US territories).",
    "OCONUS":  "Outside the Continental United States — work performed in Alaska, Hawaii, US territories, or foreign countries.",
    "TS/SCI":  "Top Secret / Sensitive Compartmented Information — the highest clearance level, required for access to classified intelligence programs.",
    "CAC":     "Common Access Card — the smart-card ID issued to DoD military and civilian personnel, used for physical access and digital authentication.",
    "PIV":     "Personal Identity Verification — a smart-card credential issued to federal employees and contractors for secure access.",
    "MFA":     "Multi-Factor Authentication — logging in with two or more verification methods (e.g., password + phone code).",
    "ZTA":     "Zero Trust Architecture — a security model that requires continuous verification of every user and device, even inside the network.",
    "SSA":     "Source Selection Authority — the government official who makes the final contract award decision.",
    "SSEB":    "Source Selection Evaluation Board — the government team that evaluates and scores vendor proposals.",
    "TRL":     "Technology Readiness Level — a 1–9 scale measuring how mature a technology is, from basic research (1) to proven in operations (9).",
    "CDR":     "Critical Design Review — a formal milestone review ensuring detailed design meets requirements before development begins.",
    "PDR":     "Preliminary Design Review — an earlier milestone confirming the system design approach before detailed design.",
    "MDR":     "Mission Dependency Rating — a score indicating how critical a system is to mission success."
  };

  /* ------------------------------------------------------------------ */
  /* Terms auto-detected in page text (only unambiguous gov-contract     */
  /* abbreviations — short common English words are excluded)            */
  /* ------------------------------------------------------------------ */
  var AUTO_DETECT = [
    "CAG","HITL","PWIN","LCAT","DLR","FBR","FFP","T&M","NAICS","SAM\\.gov",
    "RFP","RFQ","RFI","SOW","PWS","CUI","ATO","IDIQ","GSA","CMMC",
    "FPDS-NG","FPDS","SBOM","STIG","SDVOSB","WOSB","HUBZone",
    "IL2","IL4","IL5","IL6","SBIR","STTR","OTA","DFARS","BAA",
    "CONUS","OCONUS","MDR","TRL","CDR","PDR","SSA","SSEB",
    "COR","PoP","LLM","RAG","SSP","POAM",
    "G&A","B&P"
  ];

  /* ------------------------------------------------------------------ */
  /* Elements to skip when walking text nodes                            */
  /* ------------------------------------------------------------------ */
  var SKIP_TAGS = new Set([
    "SCRIPT","STYLE","CODE","PRE","INPUT","SELECT","TEXTAREA",
    "ABBR","A","BUTTON","LABEL","OPTION","NOSCRIPT","TEMPLATE"
  ]);

  /* ------------------------------------------------------------------ */
  /* Tooltip element (single shared instance)                            */
  /* ------------------------------------------------------------------ */
  var _tooltip = null;

  function _createTooltip() {
    var el = document.createElement('div');
    el.id = 'glossary-tooltip';
    el.setAttribute('role', 'tooltip');
    el.setAttribute('aria-live', 'polite');
    el.style.cssText = [
      'position:fixed',
      'z-index:10000',
      'max-width:340px',
      'background:#1e2a3a',
      'color:#f0f4f8',
      'padding:.65rem 1rem',
      'border-radius:6px',
      'font-size:.82rem',
      'line-height:1.55',
      'box-shadow:0 6px 20px rgba(0,0,0,.35)',
      'pointer-events:none',
      'display:none',
      'border-left:3px solid #3d85c8',
      'word-wrap:break-word'
    ].join(';');
    document.body.appendChild(el);
    return el;
  }

  /* ------------------------------------------------------------------ */
  /* Auto-wrap matching text nodes                                       */
  /* ------------------------------------------------------------------ */
  function _autoWrap() {
    var pattern = new RegExp(
      '(?<![\\w/])(' + AUTO_DETECT.join('|') + ')(?![\\w/])',
      'g'
    );

    var walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          var p = node.parentElement;
          if (!p || SKIP_TAGS.has(p.tagName)) return NodeFilter.FILTER_REJECT;
          if (p.closest('[data-glossary]')) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    var nodes = [];
    var n;
    while ((n = walker.nextNode())) {
      pattern.lastIndex = 0;
      if (pattern.test(n.textContent)) nodes.push(n);
    }

    nodes.forEach(function (node) {
      _replaceNode(node, pattern);
    });
  }

  function _replaceNode(node, pattern) {
    var text = node.textContent;
    pattern.lastIndex = 0;
    if (!pattern.test(text)) return;

    var frag = document.createDocumentFragment();
    var last = 0;
    pattern.lastIndex = 0;
    var m;

    while ((m = pattern.exec(text))) {
      if (m.index > last) {
        frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      }
      var abbr = document.createElement('abbr');
      // Normalise SAM.gov key
      var key = m[1].replace('SAM.gov', 'SAM.gov');
      abbr.dataset.glossary = key in GLOSSARY ? key : m[1];
      abbr.textContent = m[1];
      abbr.style.cssText = 'cursor:help;border-bottom:1px dotted #2980b9;text-decoration:none;color:inherit';
      abbr.setAttribute('tabindex', '0');
      abbr.setAttribute('aria-describedby', 'glossary-tooltip');
      frag.appendChild(abbr);
      last = m.index + m[1].length;
    }

    if (last < text.length) {
      frag.appendChild(document.createTextNode(text.slice(last)));
    }

    if (node.parentNode) {
      node.parentNode.replaceChild(frag, node);
    }
  }

  /* ------------------------------------------------------------------ */
  /* Tooltip show / hide                                                 */
  /* ------------------------------------------------------------------ */
  function _show(el) {
    var term = el.dataset.glossary;
    var def = GLOSSARY[term];
    if (!def) return;

    _tooltip.innerHTML = '<strong style="color:#7ec8e3">' +
      _esc(term) + '</strong><br><span style="color:#d0dce8">' + _esc(def) + '</span>';
    _tooltip.style.display = 'block';

    var rect = el.getBoundingClientRect();
    var tw = 340;
    var left = Math.min(rect.left, window.innerWidth - tw - 16);
    left = Math.max(8, left);

    var top = rect.bottom + 8;
    _tooltip.style.top = '0';
    _tooltip.style.left = '0';
    _tooltip.style.display = 'block';
    var th = _tooltip.offsetHeight;
    if (top + th > window.innerHeight - 8) {
      top = rect.top - th - 8;
    }
    top = Math.max(8, top);

    _tooltip.style.top = top + 'px';
    _tooltip.style.left = left + 'px';
  }

  function _hide() {
    if (_tooltip) _tooltip.style.display = 'none';
  }

  function _esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  /* ------------------------------------------------------------------ */
  /* Event delegation                                                    */
  /* ------------------------------------------------------------------ */
  function _attachListeners() {
    document.addEventListener('mouseover', function (e) {
      var t = e.target && e.target.closest ? e.target.closest('[data-glossary]') : null;
      if (t) { _show(t); } else { _hide(); }
    });

    document.addEventListener('mouseout', function (e) {
      var t = e.target && e.target.closest ? e.target.closest('[data-glossary]') : null;
      if (t) { _hide(); }
    });

    document.addEventListener('focusin', function (e) {
      var t = e.target && e.target.closest ? e.target.closest('[data-glossary]') : null;
      if (t) { _show(t); }
    });

    document.addEventListener('focusout', function (e) {
      var t = e.target && e.target.closest ? e.target.closest('[data-glossary]') : null;
      if (t) { _hide(); }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { _hide(); }
    });
  }

  /* ------------------------------------------------------------------ */
  /* Init                                                                */
  /* ------------------------------------------------------------------ */
  function init() {
    _tooltip = _createTooltip();
    _autoWrap();
    _attachListeners();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
