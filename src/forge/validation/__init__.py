"""Human validation capture (T13): the NEED axis and the TRL axis.

A need becomes real only when a human confirms it (rule 4); TRL comes from the
inventor, never an Engine estimate (rule 5). These records feed two-axis routing.
"""

from .repository import (
    confirmed_tracks,
    latest_need_validation,
    latest_trl_check,
    record_need_validation,
    record_trl_check,
)
from .trl import TrlQuestionnaire, build_questionnaire, validate_band

__all__ = [
    "record_need_validation",
    "latest_need_validation",
    "confirmed_tracks",
    "record_trl_check",
    "latest_trl_check",
    "build_questionnaire",
    "validate_band",
    "TrlQuestionnaire",
]
