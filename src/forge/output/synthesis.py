"""Decision-oriented synthesis (L5): the committee's first read, market-framed.

This runs an LLM AFTER the streams/scoring, over the engine's OWN derived signals
(score + per-dimension rationales, corroboration routing, cross-stream evidence,
the market hypotheses) — never over the raw invention text. It produces what the
committee actually needs to decide: a one-line recommendation, a short market
reading (which customer, why now, capital profile), and the open questions the
first sprint gate must answer.

It is advisory analysis, not a grounded factual claim and not a human decision —
the model is told to introduce no facts beyond the signals it is given, and the
exact signals fed in are recorded as ``basis`` for transparency. Best-effort: if
no capable LLM is available (e.g. the offline demo provider), ``build_synthesis``
returns None and the engine simply shows the raw score instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..llm.provider import LLMProvider

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string"},
        "summary": {"type": "string"},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recommendation", "summary", "open_questions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a technology-transfer analyst preparing a committee briefing. You are "
    "given ONLY the engine's derived SIGNALS for one asset (a transparent score "
    "with per-dimension rationales, a cross-stream routing, evidence snippets, and "
    "candidate markets). Do not restate the invention and do NOT introduce any "
    "fact not present in the signals.\n\n"
    "Write, for the committee:\n"
    " - RECOMMENDATION: one line — the route that fits the evidence (e.g. 'License "
    "to an instrument maker', 'Spin-out candidate', 'Park — no market pull found', "
    "'Sprint to validate market'). Name the market, not the technology.\n"
    " - SUMMARY: 2-4 sentences reading the signals for a decision — which customer/"
    "market, why now, capital profile, what the evidence does and does NOT support. "
    "Be honest about thin evidence; if coverage is low, say the read is provisional.\n"
    " - OPEN_QUESTIONS: 2-4 specific unknowns the first sprint gate must resolve "
    "(e.g. 'Is the resolution gain a real advantage over incumbent tools, and who "
    "pays for it?'). Make them decision-relevant, not generic.\n\n"
    "Respond with JSON only, matching the provided schema."
)


@dataclass
class DecisionSynthesis:
    recommendation: str
    summary: str
    open_questions: list[str]
    model: str
    basis: list[str] = field(default_factory=list)


@dataclass
class SynthesisInputs:
    asset: object
    profile: object | None = None
    score: object | None = None  # forge.scoring.VentureabilityScore
    corroboration: object | None = None
    stream_results: list = field(default_factory=list)
    dormancy: object | None = None


def _signal_lines(inp: SynthesisInputs) -> list[str]:
    """Flatten the engine's derived signals into plain lines for the prompt."""
    lines: list[str] = []
    asset = inp.asset
    title = getattr(asset, "title", None) or "(untitled)"
    lines.append(f"ASSET: {title} [{getattr(getattr(asset, 'asset_type', None), 'value', '?')}]")

    if inp.dormancy is not None:
        try:
            lines.append(f"DORMANCY: {inp.dormancy.verdict()}")
        except Exception:  # noqa: BLE001
            pass

    score = inp.score
    if score is not None:
        if score.value is None:
            lines.append("SCORE: indeterminate (no scorable dimensions)")
        else:
            lines.append(f"SCORE: ventureability {score.value:.2f} (coverage {score.coverage:.0%})")
        for d in getattr(score, "dimensions", []):
            shown = f"{d.value:.2f}" if d.value is not None else "n/a"
            lines.append(f"  dim {d.dimension}: {shown} — {d.rationale}")

    corr = inp.corroboration
    if corr is not None:
        lines.append(f"ROUTING: {corr.routing.value} — {getattr(corr, 'rationale', '')}")
        for c in getattr(corr, "conflicts", []) or []:
            lines.append(f"  conflict: {c}")

    profile = inp.profile
    if profile is not None:
        apps = getattr(profile, "applications", []) or []
        app_vals = [getattr(a, "value", str(a)) for a in apps]
        if app_vals:
            lines.append("CANDIDATE MARKETS: " + "; ".join(app_vals))
        terms = getattr(profile, "query_terms", []) or []
        if terms:
            lines.append("MARKET QUERY TERMS: " + ", ".join(terms))

    for result in inp.stream_results or []:
        for sig in getattr(result, "sub_signals", []) or []:
            if getattr(sig, "evidence", None):
                detail = sig.detail or f"{sig.name}={getattr(sig, 'value', '')}"
                lines.append(f"EVIDENCE [{result.stream}]: {detail}")
    return lines


def build_synthesis(inputs: SynthesisInputs, provider: LLMProvider) -> DecisionSynthesis | None:
    """Produce a decision-oriented synthesis from the engine's signals.

    Best-effort: returns None if there are no signals to reason over or the
    provider does not return a usable synthesis JSON (e.g. the offline provider).
    """
    basis = _signal_lines(inputs)
    if len(basis) <= 1:  # nothing but the title — nothing to synthesise
        return None

    user = "SIGNALS:\n" + "\n".join(basis)
    try:
        response = provider.complete(
            SYSTEM_PROMPT, user, json_schema=SYNTHESIS_SCHEMA, max_tokens=800
        )
        data = json.loads(response.text)
    except Exception:  # noqa: BLE001 - provider/JSON failure -> no synthesis
        return None

    recommendation = data.get("recommendation")
    summary = data.get("summary")
    questions = data.get("open_questions", [])
    if not isinstance(recommendation, str) or not isinstance(summary, str):
        return None
    if not recommendation.strip() or not summary.strip():
        return None
    if not isinstance(questions, list):
        questions = []
    questions = [q for q in questions if isinstance(q, str) and q.strip()]

    return DecisionSynthesis(
        recommendation=recommendation.strip(),
        summary=summary.strip(),
        open_questions=questions,
        model=getattr(response, "model", "unknown"),
        basis=basis,
    )
