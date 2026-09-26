"""Sources drop-down links and chat pictures (Request H15)."""

from __future__ import annotations

import pytest

import sources


def test_links_come_out_clean_titled_and_once_each():
    text = (
        "1. Photosynthesis — Wikipedia https://en.wikipedia.org/wiki/Photosynthesis_(biology).\n"
        "See [NASA Earth](https://earthobservatory.nasa.gov/features/Photosynthesis?utm_source=x&id=7) and "
        "(https://www.khanacademy.org/science/biology).\n"
        "Again: https://en.wikipedia.org/wiki/Photosynthesis_(biology)\n"
        "local: /api/uploads/abc and ftp://nope.example"
    )
    found = sources.extract(text)
    assert [s["url"] for s in found] == [
        "https://earthobservatory.nasa.gov/features/Photosynthesis?id=7",
        "https://en.wikipedia.org/wiki/Photosynthesis_(biology)",
        "https://www.khanacademy.org/science/biology",
    ]
    assert found[0]["title"] == "NASA Earth"
    assert found[1]["title"] == "Photosynthesis — Wikipedia"
    assert found[2]["domain"] == "khanacademy.org"


class _Response:
    def __init__(self, status=200, headers=None, body=b""):
        self.status_code, self.headers, self._body = status, headers or {}, body

    def iter_content(self, size):
        yield self._body


class _Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self.responses.pop(0)


def test_pictures_are_https_public_raster_images_only(monkeypatch):
    public = []
    monkeypatch.setattr(sources, "_public_host", lambda host: public.append(host))
    png = _Response(headers={"content-type": "image/png"}, body=b"\x89PNG....")
    data, kind = sources.fetch_image("https://img.example.com/a.png", session=_Session([png]))
    assert kind == "image/png" and data.startswith(b"\x89PNG")

    with pytest.raises(sources.ImageRefused):
        sources.fetch_image("http://img.example.com/a.png", session=_Session([png]))
    svg = _Response(headers={"content-type": "image/svg+xml"}, body=b"<svg/>")
    with pytest.raises(sources.ImageRefused):
        sources.fetch_image("https://img.example.com/a.svg", session=_Session([svg]))
    redirect_to_http = _Response(302, {"location": "http://evil.example/x.png"})
    with pytest.raises(sources.ImageRefused):
        sources.fetch_image("https://img.example.com/r", session=_Session([redirect_to_http]))


def test_local_network_addresses_are_never_fetched():
    with pytest.raises(sources.ImageRefused):
        sources._public_host("127.0.0.1")
    with pytest.raises(sources.ImageRefused):
        sources._public_host("169.254.169.254")


def test_sources_are_saved_with_the_message(tmp_path):
    from chat_sessions import ChatSessionStore

    store = ChatSessionStore(path=tmp_path / "chats.json")
    chat = store.ensure_active()
    store.append("assistant", "answer", chat_id=chat, extra={"sources": [{"url": "https://a.example/", "title": "A", "domain": "a.example"}],
                                                             "ignored": True})
    saved = store.messages(chat)[-1]
    assert saved["sources"][0]["url"] == "https://a.example/" and "ignored" not in saved
