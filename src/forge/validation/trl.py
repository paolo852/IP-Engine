"""The TRL micro-questionnaire the Engine GENERATES for the inventor (rule 5).

The Engine asks; the inventor answers. This module only assembles the questions
and validates an inventor's chosen band against the allowed set — it never fills
an answer and never estimates TRL from the patent text.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import TrlConfig


@dataclass
class TrlQuestionnaire:
    bands: tuple[str, ...]
    questions: tuple[dict, ...]  # ({"id", "text"}, ...) — asked, never answered

    def render(self) -> str:
        lines = ["Inventor TRL micro-check (the inventor answers — the Engine does not):"]
        lines.append(f"  Pick a TRL band: {', '.join(self.bands)}")
        for q in self.questions:
            lines.append(f"  [{q['id']}] {q['text']} (yes/no)")
        return "\n".join(lines)


def build_questionnaire(cfg: TrlConfig) -> TrlQuestionnaire:
    return TrlQuestionnaire(bands=cfg.bands, questions=cfg.questions)


def validate_band(band: str, cfg: TrlConfig) -> str:
    """Return the band if it is one the inventor was offered, else raise."""
    if band not in cfg.bands:
        raise ValueError(f"TRL band {band!r} is not one of {list(cfg.bands)}")
    return band
