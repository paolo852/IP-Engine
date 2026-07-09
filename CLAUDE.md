# FORGE Mining Engine — Consolidated Redesign Brief for Claude Code
> ONE authoritative brief. It supersedes the earlier separate notes and describes
> the Engine as it should now be, with all new features integrated. Put this file
> at the repo root as `CLAUDE.md` (or read it first every session). Work in thin,
> tested vertical slices, in the task order at the end. Do not rebuild what the
> existing prototype already does well — read the codebase first and evolve it.
---
## 1. What the Engine is (and is not)
The FORGE Mining Engine turns a research organisation's **dormant** intellectual
assets into a ranked, evidence-backed, committee-ready pipeline, and — this is the
new heart — links each asset to **named, reachable company needs** so the route to
valorisation is decided by real market evidence, not by a score.
- It is **orchestration over bought components**: connectors + a database +
  hosted-LLM calls + a transparent scoring model + a light interface + a
  relationship graph. The value is the METHOD, not novel algorithms.
- It is **NOT** a green-field ML platform, and **NOT** a research project.
- **Humans decide.** The Engine ranks, evidences, and proposes; the deal-flow
  committee decides. No component ever decides an asset's fate automatically.
### Scope boundary — two worlds, this Engine serves ONE
- **Dormant IP NOT in development** (already filed/disclosed, idle) → **THIS Engine**.
- **IP in development / pre-disclosure** → a SEPARATE tool (Matching Workspace),
  out of scope here. Do not add pre-disclosure dialogue features to this Engine.
---
## 2. Non-negotiable rules (apply to every task)
1. **Grounding rule.** Every factual sentence the Engine emits carries a pointer to
   a stored evidence record. No source → no claim. Build it into the data model.
2. **Transparent scoring.** Documented weighted model, config-set weights, no
   black-box ML.
3. **Config, not code.** Dormancy thresholds and scoring weights are editable
   configuration, never hard-coded.
4. **Hypotheses stay hypotheses.** A need is never "known"; it is hypothesised and
   only becomes real after human validation. Never present a hypothesis as a need.
5. **The Engine does not guess TRL.** TRL comes from the inventor, not from the
   patent text.
6. **No real/confidential data in development.** Synthetic/public only. Real
   portfolios and any personal data enter only under GDPR/EU-hosted protocols.
7. **Licence separation.** Derived signals stored separately from licensed raw
   data; nothing requires republishing licensed records.
8. **Tests with every slice.** This system is mostly integration — fragility is the
   main risk. Every task delivers code + passing tests incl. edge cases.
---
## 3. Architecture (five layers + governance + the graph)
```
Sources
  University assets (patents · disclosures · software · theses · KERs)
  Free public feeds (EPO OPS · PATSTAT · CORDIS · Innovation Radar)
  Licensed feeds (Dealroom/Crunchbase · optional patent analytics)
  University Relationship Graph  ← NEW data pillar
        │
  L1 Ingestion & connectors      (connector framework · scheduler · dedup/entity-res)
  L2 Asset store                 (unified schema · PostgreSQL · provenance per field)
  L3 Enrichment                  (application decomposition · grounded briefs ·
                                  4-stream cross-referencing · need-hypothesis gen)
  L4 Scoring, clustering, routing (dormancy rules · ventureability score ·
                                  sector clustering · TWO-AXIS routing)
  L5 Output & human interface    (decision-first briefs · need-matching view ·
                                  committee dashboard · decision/outcome capture)
  Governance (cross-cutting)      (grounding/audit · RBAC · GDPR/EU-hosting ·
                                  prompt-injection hygiene · licence separation)
```
---
## 4. Data model (minimum)
- **asset**: id, type {patent|disclosure|software|dataset|thesis|project_result},
  source_layer, title, abstract, claims_or_description, inventors[], owners[],
  co_owners[], legal_status, key_dates{}, fee_status, encumbrances,
  linked_publications[], provenance per field.
- **evidence_record**: asset_id, stream|source, date, match_strength, snippet,
  link. (Backs the grounding rule.)
- **company**: id, name, registry_id, sector, size, country.
- **relationship**: company_id, university_unit, type {research_contract,
  collaborative_project, spin_off, industrial_phd, lab_sponsor, alumni_employer,
  committee_member, other}, topic, dates, strength, source_layer {0|1|2}.
- **contact** (restricted): company_id, person, role, email, lawful_basis_flag.
  Isolated behind stricter RBAC; company-level matching must work without it.
- **need_hypothesis**: asset_id, company_id, hypothesised_need (sentence),
  track {customer|producer}, strength {weak|medium|strong}, evidence[], rationale.
- **need_validation**: asset_id, company_id, track,
  outcome {need_confirmed|need_denied|no_response}, note, date.
- **inventor_trl_check**: asset_id, trl_band (e.g. "2-4"|"6-9"),
  evidence {prototype?|real_case_tested?|simulation_only?}, note, date.
- **routing**: asset_id, suggested_route, committee_decision, rationale.
---
## 5. The processing pipeline (the new model, end to end)
### L3.1 — Application decomposition (NOT abstract paraphrase)
From claims/description derive candidate MARKET APPLICATIONS in industry language,
each with an end-customer and use-case. Output:
`{technology_summary, candidate_applications[]{application, end_customer, use_case,
industry_terms[]}}`. The `industry_terms` — never the patent's technical
vocabulary — drive all downstream queries. (Querying with the patent's own words
is the "push without pull" bias the system exists to remove.)
### L3.2 — Four-stream cross-referencing
Per candidate application, fan out (queries from industry_terms):
- **S1 Funding** (Dealroom/Crunchbase, behind interface, mock by default):
  "is capital flowing into this problem now?"
- **S2 Patents/citations** (PATSTAT bulk + EPO OPS live): filing-trend slope,
  forward-citation count + citing-entity type (corporate citation = paradox
  signal), neighbour density.
- **S3 Roadmaps/standards** (curated corpus): industrial/regulatory pull.
- **S4 EU taxonomy** (deterministic): green/digital/critical-tech tags.
Normalise all into evidence_records with provenance. Detect **agreement vs
conflict** across streams (corroboration = strong signal; conflict, e.g. high
funding + crowded class with no citations = licensing/parking signal).
### L3.3 — Need-hypothesis generator (four steps)
1. **Capability → value functions** (what it makes someone earn/save).
2. **Value functions → sector need-types** (recurring needs of that sector).
3. **Company + signals → specific hypothesis.** For companies from the graph,
   combine graph relationship + current public signals + value-chain position to
   produce a FALSIFIABLE need_hypothesis with a strength derived from convergence.
4. **(Validation happens later, in L4/L5 — nothing before it is a need.)**
### L3.4 — Two named company lists (dual-track), graph-prioritised
Per application, produce a **customer list** (firms that have the problem — search
where the problem manifests) and a **producer/licensee list** (firms that would
make/sell it — adjacent producers + forward-citers). Different queries; do not
merge. Cross both against the Relationship Graph: related companies rank to the
top, tagged with relationship type and (behind RBAC) whether a contact exists.
### L4.1 — Dormancy (deterministic, config)
Patents: no active licence/option/spin-off, age 3–10y, fees paid/lapsing.
Project results: ended 1–5y ago, no exploitation since, our org owner/co-owner.
### L4.2 — Ventureability score (transparent, explainable)
Six dimensions {technology_maturity, market_pull, ip_defensibility,
capital_intensity, regulatory_pathway, team_availability}, config weights, every
score shows its dimension breakdown + contributing evidence. **Low coverage is a
signal, not a silent gap:** if too few streams return evidence, re-query with
broadened application terms, then flag "insufficient market evidence — human
review" rather than emitting a confident-looking half-score.
### L4.3 — Sector clustering
Cluster the ranked shortlist by technology class into 2–3 dense veins (themed
sprint waves downstream).
### L4.4 — TWO-AXIS routing (the new routing logic)
Routing is NOT the score. It is the crossing of **two human validations** the
Engine prepares but does not decide:
- **Need axis** (from the company, via need_validation): customer / producer / none.
- **TRL axis** (from the inventor, via inventor_trl_check — asked EARLY, before
  routing; the Engine generates the TRL micro-questionnaire but never estimates
  TRL itself).
Routing stays PENDING until both records exist, then:
| | TRL high (~6–9) | TRL low (~2–4) |
|---|---|---|
| **Customer confirmed** | venture creation (sprint) | needs-oriented maturation* |
| **Producer confirmed** | licensing | option / co-development** |
| **None / denied / no-response** | park (logged) | park (logged) |
\* needs-oriented maturation: FORGE tracks the outcome and **signposts external
funding (EIC Transition, proof-of-market) but does not fund maturation itself**.
\** option/co-development: the corporate-option module of the IP-for-Equity standard.
Routing is a SUGGESTION; the committee decides. Store suggestion AND decision.
### L5 — Output
Decision-first asset brief, ordered: (1) decision synthesis + suggested route;
(2) transparent score with per-dimension rationale; (3) the two company lists
(related firms on top, contacts hidden by default); (4) validation + TRL status;
(5) open questions for Day-0; (6) coverage indicator / human-review flag. Raw
profile and full evidence go in a collapsed "see grounding" appendix. Committee
dashboard captures routing decisions and later realised outcomes against the
Engine's prediction, feeding a quarterly recalibration with a logged weight trail.
---
## 6. The Relationship Graph — layered population (data pillar)
The graph gives a RELATIONSHIP, not a need — but it is what makes need hypotheses
specific and reachable. Build it in layers (this is a data-sourcing problem, not a
code problem):
- **Layer 0 — public (build first, near-free):** the university's own EU-project
  industrial partners from CORDIS. The only realistic layer for validation sites.
- **Layer 1 — registered:** research contracts, spin-offs, licences via internal
  export/CSV (full pilots, where the university collaborates).
- **Layer 2 — tacit (targeted):** a form for a researcher to add "I know this
  company", only for assets actually entering matching.
- **Contacts:** separate, restricted, lawful-basis-gated; never a default field.
Expose which layers contributed to each company — "how much does matching improve
as the graph gets richer?" is a measured research variable.
---
## 7. Governance & compliance (cross-cutting, verify throughout)
Grounding audit (no unsourced factual sentence escapes); RBAC with the contact
sub-record behind stricter access; full audit log of every generated output + its
sources; prompt-injection hygiene on all LLM inputs; licence-separation test;
GDPR/EU-hosting configuration — the graph raises the GDPR bar because it holds
personal data, so company-level matching must work with contacts hidden.
---
## 8. Task order (thin vertical slices — one per session, tests each)
Foundations / fixes (if not already in the prototype):
- **T1** L2 data model + asset store + evidence_record + provenance.
- **T2** EPO OPS connector (free) → normalise into schema.
- **T3** Deterministic dormancy rules (config) + tests.
- **T4** LLM **application decomposition** (replaces abstract paraphrase) + grounding.
- **T5** Four-stream cross-referencing: S2 → S4 → S3 → S1 (mock) ; agreement/conflict.
- **T6** Ventureability score (transparent) + explainability + **coverage-as-signal**.
- **T7** Sector clustering.
- **T8** Decision-first output/brief (decision synthesis first; raw profile collapsed).
New capability — need-matching, graph, routing:
- **T9** Governance/privacy scaffolding for the graph (RBAC, contact isolation, GDPR).
- **T10** Relationship Graph model + **Layer-0 CORDIS connector** + entity resolution.
- **T11** Need-hypothesis generator (the four-step chain, falsifiable output).
- **T12** Two dual-track company lists + graph prioritisation.
- **T13** Validation capture (company need) + inventor TRL micro-check record.
- **T14** **Two-axis routing** (need × TRL → four outcomes; pending until both).
- **T15** Need-matching view + decision/outcome capture + quarterly recalibration.
- **T16** Governance hardening pass (grounding audit, licence-separation, audit log).
---
## 9. Test fixtures
Public patent **US10041971B2** (diamond NV-centre scanning sensor) is the standard
fixture — a real case where a naive profiler returned mostly n/a (proving why
application decomposition is needed). Use a SYNTHETIC relationship graph (invented
companies/relationships); never real contact data in dev.
---
## 10. The real bottleneck (not solved by code — keep visible)
Procuring the Dealroom/PATSTAT licences; keeping access to each university's
IP-management system (the least standardised connector); curating the S3 corpus;
assembling the relationship graph beyond Layer 0; and CALIBRATING scoring weights
with the human committee. Build everything on synthetic/public data first; connect
real, confidential sources only under GDPR/EU-hosted protocols.
---
## 11. How to work with Claude Code
Read the existing codebase before each task; reuse what's there; one task per
session; deliver code + passing tests; commit between tasks. If a task is bigger
than a session, split it and say so. Before starting, confirm current Claude Code
setup (install, runtime requirements, repo connection) against the official
Anthropic documentation — setup details change.
