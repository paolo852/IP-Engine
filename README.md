# FORGE Mining Engine

Turns a research organisation's dormant / orphaned intellectual assets into a
ranked, evidence-backed pipeline for valorisation. The Engine **ranks and
evidences**; humans decide. No component ever decides an asset's fate.

It is *orchestration over bought components*: connectors + a database +
hosted-LLM calls + a transparent scoring model + a light interface. The value is
the **method** — the four streams, the grounding rule, the scoring rubric, the
routing logic — not novel algorithms.

## End-to-end orchestration

`forge.pipeline.Pipeline` runs the whole method over a batch of assets — for each
one: dormancy → LLM profiling (persisted) → the four streams (persisted evidence)
→ corroboration → ventureability scoring → grounded brief. It is fault-tolerant
(a failing step or stream is captured; one asset never blocks the rest) and
idempotent (profile + evidence are replaced on re-run, not duplicated). Stream
clients (S2/S1) are injected; S3/S4 run offline. See `scripts/pipeline_demo.py`
for ingest → pipeline → committee decision → dashboard in one self-contained run.

## Status

Implemented so far:

- **Slice 1 — L2 asset store.** Unified schema, PostgreSQL, Alembic migrations,
  round-trip of a synthetic asset; grounding rule and licence-separation seam
  built in from the start.
- **Slice 2 — EPO OPS connector (stream S2, free, built first).** An L1 connector
  framework plus the EPO Open Patent Services connector: OAuth2 auth, biblio
  fetch, namespace-tolerant XML parsing, and normalisation into the L2 schema
  with provenance on every field. Runs are fault-tolerant and resumable.
- **Slice 3 — deterministic dormancy rules (L4).** A config-driven, explainable
  rule engine for patents and project results: every threshold and signal marker
  comes from config, each verdict lists its conditions (pass/fail/unknown), the
  asset field read, and the threshold. Missing inputs yield `unknown`, never a
  guess. Humans decide; this only flags + evidences candidates.
- **Slice 4 — LLM profiling + grounding scaffolding (L3).** A provider-agnostic
  LLM wrapper (default: Claude via the official SDK; region/vendor swappable via
  `config/llm.yaml`, key from env) and a profiling service that turns an asset's
  claims into a structured `{problem, solution, applications}` profile plus
  problem-space `query_terms`. Every generated statement must carry a verbatim
  quote that is verified against the asset's own text; an unverifiable quote is
  rejected and the asset field each quote came from is recorded — grounding for
  generative output, enforced at build and at persistence.
- **Slice 5 — S2 patents/citations cross-referencing (L3).** A streams framework
  plus the first stream (S2, free, built first): the profile's problem-space
  `query_terms` become typed queries that fan out via EPO OPS to measure
  filing-trend slope, forward citations (+ citing entities), and neighbour
  density. Every finding is normalised into the common `evidence` records
  (source, match-strength, snippet, link) and persisted with provenance. Analysis
  is deterministic; cross-stream agreement/conflict lands when more streams exist.
- **Slice 5 (cont.) — S4 EU taxonomy (L3).** A deterministic classifier (no ML,
  no LLM) matching the profile against configurable green / digital /
  critical-tech term sets with word boundaries; each aligned category becomes a
  sub-signal + evidence record listing exactly which terms matched, persisted
  into the same evidence store with public-licence provenance.
- **Slice 5 (cont.) — S3 roadmaps/standards (L3).** Semantic retrieval over a
  curated, indexed corpus of roadmaps/standards/regulations to gauge
  industrial/regulatory pull. Retrieval is via a pluggable `Retriever` (default:
  a dependency-free, deterministic TF-IDF scorer; an embedding backend can swap
  in); the top matches become evidence records (public-licence provenance).
- **Slice 5 (cont.) — S1 funding flows (L3; LICENSED, built last).** Aggregates
  recent funding rounds in the problem space (Dealroom/Crunchbase) into total
  funding, round count, and active investors. **Licence separation (rule 5):**
  only derived aggregates are persisted as evidence (`licensed_dealroom` source,
  pointer locator); raw per-round records stay in memory and are never stored.
  Folds into corroboration as a `capital_flow` indicator (and the "capital into a
  crowded field with no citations" conflict) and into the `market_pull` score.
- **Slice 5 (cont.) — cross-stream corroboration (L3, the core).** Reads the
  S2/S4/S3 sub-signals, turns each into a qualitative indicator (config
  thresholds), then detects **agreement vs conflict** to emit a routing signal
  (sprint / licence-or-park / watch / park) — *not* averaging numbers. The
  spec's conflict (market/regulatory pull into a crowded field with no forward
  citations → licence-or-park) is detected explicitly; every verdict is
  explainable (indicators + agreements + conflicts).
- **Slice 7 — sector clustering (L4).** Groups scored assets into ranked
  portfolios by theme using a config-defined sector taxonomy. Deterministic, no
  ML: each asset is assigned to its best-matching sector by transparent
  word-boundary term overlap (ties → earlier sector), every membership records
  the terms that placed it, and unmatched assets go to an explicit `unclassified`
  bucket. Members are ranked by ventureability within each sector.
- **Slice 6 — ventureability scoring (L4).** A transparent, config-weighted
  6-dimension score (technology_maturity, market_pull, ip_defensibility,
  capital_intensity, regulatory_pathway, team_availability) — no ML. Each
  dimension is computed from named stream signals + asset fields by a documented
  rule and exposes its value, rationale, and the **evidence records** that
  produced it. Dimensions with no signal yet (capital_intensity, team_availability)
  are reported **indeterminate** rather than fabricated; the overall score is the
  weighted mean over scorable dimensions and reports its coverage.
- **Slice 8 — market-context brief generator (L5).** Composes the committee
  document deterministically from the grounded inputs (profile, dormancy, stream
  evidence, corroboration, score). Every **factual** sentence carries a source
  pointer (asset field, profile quote, or evidence record) by construction;
  advisory lines (routing, headline score, "no data" notes) are marked
  non-factual. `build_brief` verifies **zero unsourced factual sentences** and
  renders to Markdown.
- **Slice 9 — decision/outcome capture + dashboard (L5).** Persists the
  committee's decision per asset (snapshotting the Engine's routing + score that
  informed it) and the realised outcome later — the data the recalibration loop
  consumes. The `dashboard` read model returns the ranked pipeline (every asset
  with its latest decision/outcome + score) a UI renders. Humans decide; the
  Engine only records.
- **Slice 10 — quarterly recalibration loop + log (L5).** Reads decisions vs
  realised outcomes and asks, transparently, whether the ventureability score
  separated winners (spun-out/licensed) from losers (parked/abandoned). It
  reports the separation, proposes a pursue-cutoff, and writes a
  `recalibration_log` row (sample, stats, verdict, weights snapshot) for audit.
  It only **proposes** — no black-box learning; humans decide whether to retune.

Everything else (enrichment, scoring, dashboard) is stubbed or not yet present;
see "What is stubbed" below.

## Architecture (target)

Five layers + cross-cutting governance:

- **L1 Ingestion & connectors** — connector framework, incremental fetch, dedup.
  ← *framework + EPO OPS connector implemented here.*
- **L2 Asset store** — unified schema, PostgreSQL, single source of truth,
  provenance per field. ← *implemented here.*
- **L3 Enrichment** — LLM profiling, grounded brief drafter, 4-stream
  cross-referencing. ← *profiling + grounding scaffolding + the S2 stream here.*
- **L4 Scoring & clustering** — deterministic dormancy rules, 6-dimension
  ventureability score (configurable weights), sector clustering.
  ← *dormancy rules + ventureability scoring + sector clustering implemented here.*
- **L5 Output** — market-context briefs, committee dashboard, decision capture.
  ← *brief generator + decision/outcome capture + dashboard implemented here.*
- **Governance** — grounding/audit, RBAC, GDPR/EU-hosting, prompt-injection hygiene.

## Non-negotiable rules (how this code is shaped)

1. **Grounding.** Every factual field points at a stored `Source` via
   `field_provenance`. `save_asset` refuses to persist an ungrounded factual
   field — *no source → no claim*, enforced at the seam.
2. **Transparent scoring.** Ventureability is a documented weighted function;
   weights live in `config/scoring.yaml` and are validated (six dimensions, sum
   to 1.0). No black-box ML.
3. **Config, not code.** Dormancy thresholds and scoring weights are YAML, never
   hard-coded (`config/`, loaded by `forge.config`).
4. **No real/confidential data in dev.** Fixtures are synthetic and marked with
   the `synthetic` licence class.
5. **Licence separation.** `Source` stores a licence class and a *pointer*
   (`raw_ref`), never licensed raw payloads. Derived signals live in their own
   `evidence` table, separable from licensed raw data.
6. **Tests with every slice.** `pytest` covers config validation, the schema,
   the round-trip, and grounding enforcement, including edge cases.
7. **Fault tolerance.** (Connectors, later slices.) Designed for resumable,
   source-isolated ingestion.

## Data model (L2)

| Table | Purpose |
|-------|---------|
| `asset` | The unified intellectual asset (single source of truth). |
| `source` | Where data came from; carries a licence class + raw-data pointer. |
| `field_provenance` | Links each populated factual asset field to ≥1 source. |
| `evidence` | Normalised, derived cross-stream signal (S1–S4), kept separate from raw. |
| `asset_profile` | LLM-derived `{problem, solution, applications}` profile (internal-licence source). |
| `profile_grounding` | The verbatim quote + asset field grounding each profile statement. |
| `committee_decision` | The committee's decision + the Engine's routing/score snapshot at decision time. |
| `asset_outcome` | The realised outcome (licensed / spun-out / parked …), feeding recalibration. |
| `recalibration_log` | Audit record of each quarterly recalibration run (stats, verdict, weights snapshot). |

Dormancy assessments are a pure computation over these grounded fields
(`forge.dormancy`), not yet persisted — they are produced and explained on demand.

## Getting started

Requires Python 3.11+ and PostgreSQL 16 binaries on the host.

```bash
pip install -e ".[dev]"

# Boot a throwaway local Postgres and export FORGE_DATABASE_URL:
eval "$(scripts/pg_dev.sh)"

# Create the schema, then round-trip a synthetic asset:
alembic upgrade head
python scripts/roundtrip_demo.py

# Ingest real patents from EPO OPS (needs free OPS credentials):
export FORGE_EPO_OPS_KEY=...  FORGE_EPO_OPS_SECRET=...
python scripts/ingest_epo_ops.py EP1000000 EP1000001

# Classify synthetic assets with the dormancy rules (no DB/network needed):
python scripts/dormancy_demo.py

# Profile a synthetic asset and show the grounding (canned LLM, no key/network):
python scripts/profile_demo.py

# Run the S2 patents/citations stream over canned data (no OPS creds/network):
python scripts/stream_s2_demo.py

# Classify a profile against the EU taxonomy (S4 — deterministic, no network):
python scripts/stream_s4_demo.py

# Retrieve roadmaps/standards for a profile (S3 — TF-IDF, no network):
python scripts/stream_s3_demo.py

# Aggregate funding flows (S1 — derived/licensed only, no key/network):
python scripts/stream_s1_demo.py

# Corroborate S2+S4+S3 into a routing signal (sprint vs licence-or-park):
python scripts/corroborate_demo.py

# Score ventureability with a full, evidence-backed breakdown (no network):
python scripts/ventureability_demo.py

# Generate a grounded market-context brief (zero unsourced sentences, no network):
python scripts/brief_demo.py

# Capture decisions and print the ranked committee dashboard (throwaway DB):
python scripts/dashboard_demo.py

# Run the quarterly recalibration loop over synthetic history (throwaway DB):
python scripts/recalibration_demo.py

# Run the WHOLE method end to end: ingest -> pipeline -> decision -> dashboard:
python scripts/pipeline_demo.py

# Cluster a scored pipeline into sector portfolios (deterministic, no network):
python scripts/clustering_demo.py
```

### Tests

```bash
pytest
```

Tests are self-contained: if neither `FORGE_TEST_DATABASE_URL` nor
`FORGE_DATABASE_URL` is set, an ephemeral PostgreSQL cluster is booted from the
system binaries for the duration of the run. Point them at an existing database
(e.g. a CI Postgres service) via `FORGE_TEST_DATABASE_URL`.

## Configuration & secrets

- `config/dormancy.yaml`, `config/scoring.yaml` — editable thresholds/weights.
- `config/connectors.yaml` — connector endpoints/formats (no secrets).
- `config/organisation.yaml` — our org's identity for ownership-based rules.
- `config/llm.yaml` — LLM provider/model/region (no keys; EU-hosting via base_url).
- `config/streams.yaml` — cross-referencing stream parameters (S2 window/sampling).
- `config/taxonomy.yaml` — EU-taxonomy term sets for the S4 classifier.
- `data/s3_corpus.jsonl` — curated roadmaps/standards corpus for the S3 stream.
- `config/corroboration.yaml` — thresholds for cross-stream agreement/conflict.
- `config/recalibration.yaml` — outcome-quality mapping + recalibration thresholds.
- `config/sectors.yaml` — the sector taxonomy for L4 clustering.
- `FORGE_DATABASE_URL` — database connection (see `.env.example`). Secrets and
  API keys go in the environment, never in source.

## What is stubbed / not yet built

- L1 scheduler / incremental cron, dedup & cross-source entity resolution
  (the EPO OPS connector is built; re-runs are idempotent per publication, but
  cross-connector entity resolution is not yet implemented).
- EPO OPS legal-status and claims/description endpoints (`legal_status` and
  `claims_or_description` are left unset by the biblio connector for now).
- A live Dealroom-backed S1 client path (the stream + parser exist and are
  network-isolated; live runs need a licence key) and folding S1 evidence into
  the brief inputs.
- OPS forward-citation *entity* enrichment (the S2 count is live; citing-applicant
  names need a biblio follow-up per citing doc — currently fake-only).
- A scheduler/CLI around the orchestration (the `Pipeline` runs a batch in-process
  and is idempotent; a cron/queue front-end and a real-LLM/real-API smoke path —
  which need credentials — are not built).
- Persisting ventureability scores/briefs (the pipeline returns them in memory and
  decisions snapshot the score; a dedicated score table is not yet added).
- Persisting dormancy verdicts + a batch "dormancy sweep" over the store (the
  rule engine exists; wiring it across the DB and recording results is later).
- L4 capital_intensity + team_availability dimensions (indeterminate until cost/
  TRL and internal team data land); persisting scores/clusters across the store.
- L5 dashboard UI (the read model is built; the web front-end is out of scope here);
  recalibration *applying* proposals automatically (it only proposes today);
  governance (RBAC, EU-hosting).

Build order and full scope live in the project context (`CLAUDE.md` equivalent).
