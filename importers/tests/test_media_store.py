"""Offline unit tests — the shared media store, sniffer and fetch layer."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from iol_importers.media.fetch import SourceUrlIndex, fetch_and_store
from iol_importers.media.sniff import detect, dimensions
from iol_importers.media.store import MediaStore, UnsupportedMediaError

IMG = Path(__file__).resolve().parents[1] / "src/iol_importers/entegral/fixtures/img"
JPG = (IMG / "sample.jpg").read_bytes()
PNG = (IMG / "sample.png").read_bytes()
NOT_IMAGE = (IMG / "notimage.txt").read_bytes()


def test_detect_and_dimensions():
    assert detect(JPG) == ("image/jpeg", "jpg")
    assert detect(PNG) == ("image/png", "png")
    assert detect(NOT_IMAGE) is None
    assert dimensions(PNG, "image/png") == (5, 7)
    assert dimensions(JPG, "image/jpeg") == (6, 4)


def test_store_is_content_addressed(tmp_path):
    store = MediaStore(tmp_path)
    a = store.put(PNG, feed="entegral")
    b = store.put(PNG, feed="entegral")
    assert a.url == b.url
    assert a.sha256 == b.sha256
    assert a.url.startswith("/media/entegral/")
    assert a.url.endswith(".png")
    assert list(tmp_path.rglob("*.png")) == [a.path]


def test_store_rejects_non_image(tmp_path):
    with pytest.raises(UnsupportedMediaError):
        MediaStore(tmp_path).put(NOT_IMAGE, feed="entegral")


def _transport(body: bytes, content_type: str = "image/jpeg") -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda r: httpx.Response(200, content=body, headers={"content-type": content_type})
    )


def test_extension_comes_from_magic_bytes_not_header(tmp_path):
    # server lies: says jpeg, sends png
    http = httpx.Client(transport=_transport(PNG, "image/jpeg"))
    assets, stats = fetch_and_store(
        ["https://x.test/a"], feed="entegral", store=MediaStore(tmp_path), http=http
    )
    assert stats.downloaded == 1
    assert assets[0].content_type == "image/png"
    assert assets[0].url.endswith(".png")


def test_mislabelled_non_image_is_skipped(tmp_path):
    http = httpx.Client(transport=_transport(NOT_IMAGE, "image/jpeg"))
    assets, stats = fetch_and_store(
        ["https://x.test/a"], feed="entegral", store=MediaStore(tmp_path), http=http
    )
    assert assets == []
    assert stats.failed == 1


def test_size_cap_aborts_download(tmp_path):
    big = b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)
    http = httpx.Client(transport=_transport(big))
    assets, stats = fetch_and_store(
        ["https://x.test/big"],
        feed="entegral",
        store=MediaStore(tmp_path),
        http=http,
        max_bytes=1024,
    )
    assert assets == []
    assert stats.failed == 1


def test_source_url_index_skips_second_fetch(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=JPG, headers={"content-type": "image/jpeg"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    store = MediaStore(tmp_path)
    index = SourceUrlIndex(tmp_path)

    first, s1 = fetch_and_store(
        ["https://x.test/a"], feed="entegral", store=store, http=http, index=index
    )
    second, s2 = fetch_and_store(
        ["https://x.test/a"], feed="entegral", store=store, http=http, index=index
    )
    assert calls["n"] == 1
    assert s2.reused == 1
    assert first[0].url == second[0].url


def test_refresh_media_bypasses_index(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=JPG, headers={"content-type": "image/jpeg"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    store, index = MediaStore(tmp_path), SourceUrlIndex(tmp_path)
    fetch_and_store(["https://x.test/a"], feed="entegral", store=store, http=http, index=index)
    fetch_and_store(
        ["https://x.test/a"],
        feed="entegral",
        store=store,
        http=http,
        index=index,
        refresh=True,
    )
    assert calls["n"] == 2


def test_photo_404_is_skipped_not_fatal(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("gone"):
            return httpx.Response(404)
        return httpx.Response(200, content=JPG, headers={"content-type": "image/jpeg"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assets, stats = fetch_and_store(
        ["https://x.test/gone", "https://x.test/ok"],
        feed="entegral",
        store=MediaStore(tmp_path),
        http=http,
    )
    assert len(assets) == 1
    assert stats.failed == 1
    assert stats.downloaded == 1
