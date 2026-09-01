"""Configuration resolution — DATABASE_URL, feed credentials, on-disk locations."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

logger = logging.getLogger("iol_importers.config")

# importers/ lives one level below the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DOWNLOAD_DIR = REPO_ROOT / "data" / "property24"
PROPDATA_DIR = REPO_ROOT / "data" / "propdata"
PROPCTRL_DIR = REPO_ROOT / "data" / "propctrl"
REMAX_DIR = REPO_ROOT / "data" / "remax"
ENTEGRAL_DIR = REPO_ROOT / "data" / "entegral"
PROPERTYENGINE_DIR = REPO_ROOT / "data" / "propertyengine"
FUSION_DIR = REPO_ROOT / "data" / "fusion"
MEDIA_DIR = REPO_ROOT / "data" / "media"

_DEFAULT_DATABASE_URL = "postgresql://localhost:5432/iol_property_plus"
_DEFAULT_PROPDATA_LOGIN_URL = "https://api-gw.propdata.net/users/public-api/login/"
_DEFAULT_PROPCTRL_BASE_URL = "https://api.propctrl.com"
_DEFAULT_REMAX_BASE_URL = "https://ahcjbl9nbb.execute-api.eu-west-1.amazonaws.com/feeds_default"
# Entegral gave us http:// endpoints; the client tries https:// first and only
# falls back to http:// when TLS is unreachable (see entegral/client.py).
_DEFAULT_ENTEGRAL_BASE_URL = "https://sync.entegral.net/api"
# Fusion FeedStore — production sync host. Point FUSION_API_BASE_URL at the doc's
# QA host (plaintext http) for testing.
_DEFAULT_FUSION_BASE_URL = "https://za-feedstore.fusionagency.net/v1/sync"
# AllSA Property — one public, unauthenticated XML endpoint. The per-agency
# `agencyid` query parameter is config on the feed_sources row, never here.
_DEFAULT_ALLSA_BASE_URL = "https://www.allsaproperty.co.za/feeds/iol.ashx"
# MyRoof — per-franchise bracket-KV feed at `{base_url}/{token}`. The opaque
# `token` path segment is the credential and lives on the feed_sources row, not
# here (see `iol_importers.myroof.source`).
_DEFAULT_MYROOF_BASE_URL = "https://rat.myroof.co.za"
# PropertyPost — one static per-agency URL (e.g. `.../BstProperties.txt`), a plain
# GET with no auth of any kind. The full URL lives on the feed_sources row
# (`base_url`); this only supplies a default host for a row that omits it.
_DEFAULT_PROPERTYPOST_BASE_URL = "http://lms.propertypost.co.za"
# RT3 (Rawson) — one bracket-KV file per province at `{base_url}/iol-{Province}.txt`,
# a plain GET with no auth. Which provinces an agency publishes is config on the
# feed_sources row (`auth_config->>'provinces'`), never here (see
# `iol_importers.rt3.source`).
_DEFAULT_RT3_BASE_URL = "https://webservices.rawsonproperties.co.za"
# Webbox — one XML file per site at `{domain}{path}`, a plain GET where the URL
# itself is the credential (siteid + securitykey embedded in the path). The
# per-agency domain and the siteid/securitykey live on the feed_sources row
# (`base_url` + `auth_config`); this is only the shared path template.
_DEFAULT_WEBBOX_FEED_URL_TEMPLATE = (
    "/template/feeds,WebboxFeedForSite.vm/siteid/{siteid}/securitykey/{securitykey}/feed.xml"
)
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
        base_url=(_from_env_or_local("PROPCTRL_API_BASE_URL") or _DEFAULT_PROPCTRL_BASE_URL).rstrip(
            "/"
        ),
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


@dataclass(frozen=True, slots=True)
class EntegralCredentials:
    username: str
    password: str
    base_url: str


def resolve_entegral_credentials() -> EntegralCredentials | None:
    """Entegral Sync-API HTTP Basic credentials from the environment or .env.local.

    Entegral confirmed (Dillon Gray, 2026-08-13) this is a pull feed: two Basic-auth
    GET endpoints on ``sync.entegral.net``. Reads ``ENTEGRAL_USERNAME`` /
    ``ENTEGRAL_PASSWORD``; returns None (not an error) when unset, so the offline
    suite and the Next.js side never need them. Nothing here is logged.
    """
    username = _from_env_or_local("ENTEGRAL_USERNAME")
    password = _from_env_or_local("ENTEGRAL_PASSWORD")
    if not username or not password:
        return None
    base_url = _from_env_or_local("ENTEGRAL_API_BASE_URL") or _DEFAULT_ENTEGRAL_BASE_URL
    return EntegralCredentials(username=username, password=password, base_url=base_url.rstrip("/"))


_PROPERTYENGINE_AUTH_SCHEMES = ("bearer", "basic")


@dataclass(frozen=True, slots=True)
class PropertyengineFeed:
    """Where the PropertyEngine feed file lives, and how (if at all) to authenticate.

    The Gumtree Pro "Real Estate Standard Template Feed" doc specifies the JSON/XML
    format only — never a hosting URL, a schedule, or an auth scheme. It does say
    "Authorization may be implemented" at the hosting URL, so ``auth_token`` is
    optional and, when present, ``auth_scheme`` decides the header.
    """

    feed_url: str
    auth_token: str | None
    auth_scheme: str  # "bearer" | "basic"


def resolve_propertyengine_feed() -> PropertyengineFeed | None:
    """PropertyEngine feed location + optional auth from the environment or .env.local.

    Returns None (not an error) when ``PROPERTYENGINE_FEED_URL`` is unset — the
    URL is still pending from PropertyEngine, the offline suite never needs it, and
    ``--file`` runs bypass this entirely. ``PROPERTYENGINE_FEED_AUTH_TOKEN`` is
    optional; ``PROPERTYENGINE_FEED_AUTH_SCHEME`` is ``bearer`` (default) or
    ``basic``. The token is never logged or persisted.
    """
    feed_url = _from_env_or_local("PROPERTYENGINE_FEED_URL")
    if not feed_url:
        return None
    scheme = (_from_env_or_local("PROPERTYENGINE_FEED_AUTH_SCHEME") or "bearer").strip().lower()
    if scheme not in _PROPERTYENGINE_AUTH_SCHEMES:
        scheme = "bearer"
    return PropertyengineFeed(
        feed_url=feed_url.strip(),
        auth_token=_from_env_or_local("PROPERTYENGINE_FEED_AUTH_TOKEN"),
        auth_scheme=scheme,
    )


@dataclass(frozen=True, slots=True)
class FusionCredentials:
    client_id: int
    password: str
    base_url: str


def resolve_fusion_credentials() -> FusionCredentials | None:
    """Fusion FeedStore credentials from the environment or .env.local.

    Fusion signs every call with a SecurityToken whose digest is
    ``base64(sha1(f"{timestamp}*{password}*{salt}"))`` — the password is fed
    straight into that digest but is still a raw credential and is never logged or
    persisted here. ``FUSION_CLIENT_ID`` is a numeric id issued by Fusion; a
    non-numeric value is treated as unset (with a warning). Returns None (not an
    error) when either value is missing, so the offline suite and the Next.js side
    never need them. ``FUSION_API_BASE_URL`` overrides the production host (use the
    doc's QA host for testing).
    """
    client_id_raw = _from_env_or_local("FUSION_CLIENT_ID")
    password = _from_env_or_local("FUSION_PASSWORD")
    if not client_id_raw or not password:
        return None
    try:
        client_id = int(client_id_raw.strip())
    except ValueError:
        logger.warning("FUSION_CLIENT_ID is not numeric — treating Fusion as unconfigured")
        return None
    base_url = _from_env_or_local("FUSION_API_BASE_URL") or _DEFAULT_FUSION_BASE_URL
    return FusionCredentials(client_id=client_id, password=password, base_url=base_url.rstrip("/"))


def resolve_allsa_base_url() -> str:
    """The AllSA feed endpoint, from ALLSA_FEED_BASE_URL (process env or .env.local)
    else the public default.

    There are no credentials — the endpoint is unauthenticated. The per-agency
    ``agencyid`` is not resolved here; it lives on the ``feed_sources`` row (see
    ``iol_importers.allsa.source``).
    """
    return (_from_env_or_local("ALLSA_FEED_BASE_URL") or _DEFAULT_ALLSA_BASE_URL).strip()


def resolve_myroof_base_url() -> str:
    """The MyRoof feed host, from MYROOF_FEED_BASE_URL (process env or .env.local)
    else the default ``https://rat.myroof.co.za``.

    Only the host is resolved here. The per-franchise ``token`` path segment is the
    credential and lives on the ``feed_sources`` row (see
    ``iol_importers.myroof.source``); it is never an env var and never logged.
    """
    raw = _from_env_or_local("MYROOF_FEED_BASE_URL") or _DEFAULT_MYROOF_BASE_URL
    return raw.strip().rstrip("/")


def resolve_propertypost_base_url() -> str:
    """The PropertyPost feed host, from PROPERTYPOST_FEED_BASE_URL (process env or
    .env.local) else the default ``http://lms.propertypost.co.za``.

    Only the host is resolved here — used as a fallback when a ``feed_sources`` row
    carries a bare host with no ``/<file>.txt`` path. The full per-agency URL lives
    on the row (see ``iol_importers.propertypost.source``). The vendor redirects
    plain HTTP to HTTPS; the client follows that redirect. There is no credential.
    """
    raw = _from_env_or_local("PROPERTYPOST_FEED_BASE_URL") or _DEFAULT_PROPERTYPOST_BASE_URL
    return raw.strip().rstrip("/")


def resolve_rt3_base_url() -> str:
    """The RT3 (Rawson) feed host, from RT3_FEED_BASE_URL (process env or
    .env.local) else the default ``https://webservices.rawsonproperties.co.za``.

    Only the host is resolved here. Which provinces an agency publishes is config
    on the ``feed_sources`` row (``auth_config->>'provinces'``, see
    ``iol_importers.rt3.source``) — never an env var. There is no credential; the
    province files are plain public URLs.
    """
    raw = _from_env_or_local("RT3_FEED_BASE_URL") or _DEFAULT_RT3_BASE_URL
    return raw.strip().rstrip("/")


def resolve_webbox_feed_template() -> str:
    """The Webbox feed URL path template, from WEBBOX_FEED_URL_TEMPLATE (process
    env or .env.local) else the default
    ``/template/feeds,WebboxFeedForSite.vm/siteid/{siteid}/securitykey/{securitykey}/feed.xml``.

    Only the path template is resolved here. The per-agency domain lives on the
    ``feed_sources`` row (``base_url``) and the ``siteid`` / ``securitykey`` live
    in its ``auth_config`` (see ``iol_importers.webbox.source``) — the URL itself
    is the credential and is never an env var and never logged.
    """
    raw = _from_env_or_local("WEBBOX_FEED_URL_TEMPLATE") or _DEFAULT_WEBBOX_FEED_URL_TEMPLATE
    return raw.strip()
