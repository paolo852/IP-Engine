#!/usr/bin/env bash
# SessionStart setup: make the project runnable (tests + migrations) in a fresh
# session/container. Idempotent; safe to re-run. No secrets, synthetic data only.
set -euo pipefail
cd "$(dirname "$0")/.."

# Install the package + dev tools (pytest). Quiet unless it fails.
pip install -q -e ".[dev]" 2>&1 | tail -n 2 || {
  echo "FORGE setup: pip install failed" >&2
  exit 1
}

echo "FORGE setup: dependencies installed. Run 'pytest' to verify the L2 slice."
