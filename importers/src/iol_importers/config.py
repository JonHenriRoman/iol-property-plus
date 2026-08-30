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
PROPCTRL_DIR = REPO_ROOT / "data" / "propctrl"
REMAX_DIR = REPO_ROOT / "data" / "remax"

_DEFAULT_DATABASE_URL = "postgresql://localhost:5432/iol_property_plus"
_DEFAULT_PROPDATA_LOGIN_URL = "https://api-gw.propdata.net/users/public-api/login/"
_DEFAULT_PROPCTRL_BASE_URL = "https://api.propctrl.com"
_DEFAULT_REMAX_BASE_URL = "https://ahcjbl9nbb.execute-api.eu-west-1.amazonaws.com/feeds_default"
_REMAX_URL_ENV_NAMES = (
    "REMAX_API_BASE_URL",
    "REMAX_LIST_API_URL",
    "REMAX_AGENT_API_URL",
    "REMAX_LISTING_API_URL",
    "REMAX_OFFICE_API_URL",
)


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


@dataclass(frozen=True, slots=True)
class PropctrlCredentials:
    username: str
    password: str
    base_url: str


def resolve_propctrl_credentials() -> PropctrlCredentials | None:
    """PropCtrl HTTP Basic credentials from the environment or .env.local.

    Returns None (not an error) when unset, so the offline test suite and the
    Next.js side never need them. The credentials are never logged or persisted.
    """
    username = _from_env_or_local("PROPCTRL_API_USERNAME")
    password = _from_env_or_local("PROPCTRL_API_PASSWORD")
    if not username or not password:
        return None
    return PropctrlCredentials(
        username=username,
        password=password,
        base_url=(
            _from_env_or_local("PROPCTRL_API_BASE_URL") or _DEFAULT_PROPCTRL_BASE_URL
        ).rstrip("/"),
    )


@dataclass(frozen=True, slots=True)
class RemaxCredentials:
    access_key: str
    secret_key: str
    api_key: str
    base_url: str


def _resolve_remax_base_url() -> str:
    """The `.../feeds_default` prefix, from REMAX_API_BASE_URL or any REMAX_*_API_URL.

    The operator's .env.local carries per-endpoint URLs (REMAX_LIST_API_URL etc.);
    the adapter only needs the common prefix and builds each of the 8 endpoint
    paths from it.
    """
    for name in _REMAX_URL_ENV_NAMES:
        value = _from_env_or_local(name)
        if not value:
            continue
        value = value.rstrip("/")
        marker = "/feeds_default"
        if marker in value:
            return value[: value.index(marker) + len(marker)]
        return value
    return _DEFAULT_REMAX_BASE_URL


def resolve_remax_credentials() -> RemaxCredentials | None:
    """RE/MAX AWS SigV4 credentials + usage-plan API key from the environment or .env.local.

    The RE/MAX feed authenticates at the API Gateway / IAM layer: every request is
    SigV4-signed with the access/secret key AND carries an `x-api-key` header. The
    objective names the AWS vars `REMAX_AWS_ACCESS_KEY_ID` / `REMAX_AWS_SECRET_ACCESS_KEY`;
    the operator's .env.local uses `REMAX_ACCESS_KEY` / `REMAX_SECRET_KEY` (same
    call as propdata — the real env file wins). Returns None when unset so the
    offline suite and the Next.js side never need them. Nothing here is logged.
    """
    access_key = _from_env_or_local("REMAX_ACCESS_KEY")
    secret_key = _from_env_or_local("REMAX_SECRET_KEY")
    api_key = _from_env_or_local("REMAX_API_KEY")
    if not access_key or not secret_key or not api_key:
        return None
    return RemaxCredentials(
        access_key=access_key,
        secret_key=secret_key,
        api_key=api_key,
        base_url=_resolve_remax_base_url(),
    )
