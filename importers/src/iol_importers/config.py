"""Configuration resolution — DATABASE_URL, feed credentials, on-disk locations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

# importers/ lives one level below the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DOWNLOAD_DIR = REPO_ROOT / "data" / "property24"
PROPDATA_DIR = REPO_ROOT / "data" / "propdata"

_DEFAULT_DATABASE_URL = "postgresql://localhost:5432/iol_property_plus"
_DEFAULT_PROPDATA_LOGIN_URL = "https://api-gw.propdata.net/users/public-api/login/"


def _from_env_or_local(name: str) -> str | None:
    """Process env, then repo-root .env.local. Never .env.example."""
    value = os.environ.get(name)
    if value:
        return value
    env_local = REPO_ROOT / ".env.local"
    if env_local.is_file():
        return dotenv_values(env_local).get(name) or None
    return None


def resolve_database_url() -> str:
    """DATABASE_URL from the process env, then repo-root .env.local, then the local default.

    Never reads .env.example (safe placeholders) and never hardcodes credentials —
    a username/password only ever arrives via the environment or the untracked
    .env.local, matching how the Next.js side resolves the same variable.
    """
    return _from_env_or_local("DATABASE_URL") or _DEFAULT_DATABASE_URL


@dataclass(frozen=True, slots=True)
class PropdataCredentials:
    username: str
    password: str
    login_url: str


def resolve_propdata_credentials() -> PropdataCredentials | None:
    """Propdata HTTP Basic credentials from the environment or .env.local.

    Returns None (not an error) when unset, so the offline test suite and the
    Next.js side never need them. The password is never logged or persisted here.
    """
    username = _from_env_or_local("PROP_DATA_API_USERNAME")
    password = _from_env_or_local("PROP_DATA_API_PASSWORD")
    if not username or not password:
        return None
    return PropdataCredentials(
        username=username,
        password=password,
        login_url=_from_env_or_local("PROP_DATA_API_LOGIN_URL") or _DEFAULT_PROPDATA_LOGIN_URL,
    )
