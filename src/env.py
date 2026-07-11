"""Environment bootstrap for ResearchPilot.

Loads the project-root ``.env`` via python-dotenv so Streamlit, CLI scripts,
and pipeline modules all see the same configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_LOADED = False


def project_root() -> Path:
    """Return the ResearchPilot project root directory."""
    return _PROJECT_ROOT


def load_env(*, override: bool = False) -> Path:
    """Load environment variables from the project-root ``.env`` file.

    Args:
        override: When True, values in ``.env`` replace existing process env vars.

    Returns:
        Path to the ``.env`` file that was considered.
    """
    global _ENV_LOADED
    env_path = _PROJECT_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(dotenv_path=env_path, override=override)
    _ENV_LOADED = True
    return env_path


def openai_api_key_status() -> dict[str, object]:
    """Return safe diagnostics about OPENAI_API_KEY (never the key itself)."""
    if not _ENV_LOADED:
        load_env()
    raw = os.getenv("OPENAI_API_KEY")
    present = bool(raw and raw.strip())
    value = (raw or "").strip()
    return {
        "present": present,
        "length": len(value) if present else 0,
        "prefix": f"{value[:7]}…" if present and len(value) >= 7 else ("set" if present else "missing"),
        "model": (os.getenv("LLM_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini",
    }


# Load once on import so early callers see .env values.
load_env()
