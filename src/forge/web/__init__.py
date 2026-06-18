"""FORGE demo web UI (L5 presentation).

A thin, server-rendered FastAPI app over the existing read models: it renders the
committee dashboard and per-asset evidence/score/brief straight from the store
(the single source of truth) and lets a committee record decisions and outcomes.
No scoring or grounding logic lives here — it only presents what the engine
persisted, so the UI can never diverge from the method.
"""

from .app import create_app

__all__ = ["create_app"]
