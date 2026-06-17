"""L2 asset store — the single source of truth.

PostgreSQL-backed unified schema with provenance per field. The grounding rule
(rule 1) is built into the model here, not bolted on later: every factual field
value points at a stored Source via FieldProvenance.
"""
