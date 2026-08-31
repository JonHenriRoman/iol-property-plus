"""Offline unit tests — the Fusion SecurityToken."""

from __future__ import annotations

import datetime as dt

from iol_importers.fusion.security import digest, security_params

_NOW = dt.datetime(2011, 12, 3, 22, 5, tzinfo=dt.UTC)
_PASSWORD = "do-not-log-this"
_SALT = "23872387232"


def test_digest_is_stable_known_answer():
    # base64(sha1("2011-12-03-22-05*do-not-log-this*23872387232")) — regression guard
    assert digest("2011-12-03-22-05", _PASSWORD, _SALT) == "PRYqcS967LXLWMLTeM7eljkUOSE="
    value = digest("2011-12-03-22-05", _PASSWORD, _SALT)
    assert len(value) == 28 and value.endswith("=")  # base64 of a 20-byte sha1


def test_security_params_shape_and_no_password_leak():
    params = security_params(458, _PASSWORD, now=_NOW, salt=_SALT)
    assert params == {
        "clientId": "458",
        "timeStamp": "2011-12-03-22-05",
        "salt": _SALT,
        "digest": digest("2011-12-03-22-05", _PASSWORD, _SALT),
    }
    assert _PASSWORD not in "".join(params.values())


def test_salt_varies_between_calls():
    a = security_params(1, _PASSWORD)
    b = security_params(1, _PASSWORD)
    assert a["salt"] != b["salt"]
    assert a["digest"] != b["digest"]


def test_timestamp_is_utc_minute_resolution():
    naive_est = dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    assert security_params(1, "p", now=naive_est)["timeStamp"] == "2026-01-02-08-04"
