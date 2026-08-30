"""Configuration resolution — DATABASE_URL and the on-disk download location."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

# importers/ lives one level below the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DOWNLOAD_DIR = REPO_ROOT / "data" / "property24"

_DEFAULT_DATABASE_URL = "postgresql://localhost:5432/iol_property_plus"


def resolve_database_url() -> str:
    """DATABASE_URL from the process env, then repo-root .env.local, then the local default.

    Never reads .env.example (safe placeholders) and never hardcodes credentials —
    a username/password only ever arrives via the environment or the untracked
    .env.local, matching how the Next.js side resolves the same variable.
    """
    from_env = os.environ.get("DATABASE_URL")
    if from_env:
        return from_env

    env_local = REPO_ROOT / ".env.local"
    if env_local.is_file():
        from_file = dotenv_values(env_local).get("DATABASE_URL")
        if from_file:
            return from_file

    return _DEFAULT_DATABASE_URL
