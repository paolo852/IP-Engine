# FORGE Mining Engine

Turns a research organisation's dormant / orphaned intellectual assets into a
ranked, evidence-backed pipeline for valorisation. The Engine **ranks and
evidences**; humans decide. No component ever decides an asset's fate.

It is *orchestration over bought components*: connectors + a database +
hosted-LLM calls + a transparent scoring model + a light interface. The value is
the **method** — the four streams, the grounding rule, the scoring rubric, the
routing logic — not novel algorithms.

## Status

This repository currently implements **build-order slice 1: the L2 asset store**
— the unified schema, PostgreSQL, migrations, and a round-trip of a synthetic
asset, with the grounding rule and licence-separation seam built in from the
start. Everything else (connectors, enrichment, scoring, dashboard) is stubbed
or not yet present; see "What is stubbed" below.

## Architecture (target)

Five layers + cross-cutting governance:

- **L1 Ingestion & connectors** — connector framework, incremental fetch, dedup.
- **L2 Asset store** — unified schema, PostgreSQL, single source of truth,
  provenance per field. ← *implemented here.*
- **L3 Enrichment** — LLM profiling, grounded brief drafter, 4-stream
  cross-referencing.
- **L4 Scoring & clustering** — deterministic dormancy rules, 6-dimension
  ventureability score (configurable weights), sector clustering.
- **L5 Output** — market-context briefs, committee dashboard, decision capture.
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

## Getting started

Requires Python 3.11+ and PostgreSQL 16 binaries on the host.

```bash
pip install -e ".[dev]"

# Boot a throwaway local Postgres and export FORGE_DATABASE_URL:
eval "$(scripts/pg_dev.sh)"

# Create the schema, then round-trip a synthetic asset:
alembic upgrade head
python scripts/roundtrip_demo.py
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
- `FORGE_DATABASE_URL` — database connection (see `.env.example`). Secrets and
  API keys go in the environment, never in source.

## What is stubbed / not yet built

- L1 connectors (EPO OPS first), the scheduler, dedup/entity resolution.
- L3 LLM profiling, grounded brief drafter, the four streams (S2 → S4 → S3 → S1).
- L4 dormancy rule *evaluation* and the scoring *function* (the **config** for
  both exists and is validated; the consuming logic is a later slice).
- L5 dashboard and decision/outcome capture; governance (RBAC, EU-hosting).

Build order and full scope live in the project context (`CLAUDE.md` equivalent).
