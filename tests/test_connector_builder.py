""""Add any site or connector" (Update 1 U9): find it first, build it only when nothing matches, keep keys out of sight."""

from __future__ import annotations

import json

import pytest

import connector_builder
import connector_use
from connectors import catalog


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    secrets = {}
    import secret_store

    monkeypatch.setattr(secret_store, "get_keys", lambda name: list(secrets.get(name, [])))
    monkeypatch.setattr(secret_store, "set_keys",
                        lambda name, values: secrets.__setitem__(name, [v for v in values if v]) or list(values))
    monkeypatch.setattr(catalog, "_store_path", lambda: tmp_path / "connections.json")
    monkeypatch.setattr(connector_builder, "_custom_path", lambda: tmp_path / "custom.json")
    monkeypatch.setattr(connector_builder, "_store_path", lambda: tmp_path / "custom_connections.json")
    return secrets


def _never(_text):
    raise AssertionError("no model should be asked when the words name something Nyx can place")


@pytest.mark.parametrize("words,source,connector_id,kind", [
    ("add vercel", "catalog", "vercel", "rest"),
    ("https://vercel.com/my-team/dashboard", "catalog", "vercel", "rest"),
    ("stripe.com", "catalog", "stripe", "rest"),
    ("connect my calendar", "catalog", "google_calendar", "oauth_google"),
    ("add sheets", "catalog", "google_sheets", "oauth_google"),
    ("https://mcp.deepwiki.com/mcp", "known_mcp", "deepwiki", "mcp"),
    ("add the github mcp server", "known_mcp", "github-mcp", "mcp"),
    ("https://mcp.acme.dev/mcp", "mcp", "acme-mcp", "mcp"),
    ("https://api.acme.dev/v2", "api", "acme-api", "rest"),
    ("https://www.example.org/docs", "website", "example-org", "website"),
])
def test_find_places_the_words_without_a_model(stores, words, source, connector_id, kind):
    spec, found = connector_builder.find(words)
    assert (found, spec["id"], spec["kind"]) == (source, connector_id, kind)


def test_an_oauth_only_mcp_server_is_named_honestly_with_the_working_alternative(stores):
    draft = connector_builder.draft("add notion mcp", propose=_never)
    assert not draft["ready"] and draft["suggest"] == "notion" and "OAuth" in draft["message"]
    with pytest.raises(connector_builder.BuilderError, match="OAuth"):
        connector_builder.add(draft["draft_id"])


def test_a_sign_in_app_opens_its_own_card_instead_of_a_form(stores):
    draft = connector_builder.draft("add gmail", propose=_never)
    assert draft["open"] == "gmail" and not draft["ready"] and "Sign in with Google" in draft["message"]


def test_a_pasted_key_is_used_but_only_shown_masked(stores):
    draft = connector_builder.draft("add vercel, token is vcl_abcdefgh12345678wxyz", propose=_never)
    assert draft["ready"] and draft["catalog_id"] == "vercel"
    assert "vcl_abcdefgh12345678wxyz" not in json.dumps(draft)
    assert draft["fields"][0]["masked"].endswith("wxyz")
    added = connector_builder.add(draft["draft_id"])
    assert added["connected"] and stores["connector:vercel:token"] == ["vcl_abcdefgh12345678wxyz"]


def test_a_website_is_added_as_a_readable_custom_connector(stores):
    draft = connector_builder.draft("https://www.example.org/docs", propose=_never)
    assert draft["ready"] and draft["kind"] == "website"
    added = connector_builder.add(draft["draft_id"])
    entry = connector_use.entry(added["id"])
    assert entry["origin"] == "custom" and entry["base_url"] == "https://www.example.org/docs"
    assert connector_use.is_connected(added["id"])
    assert connector_use.actions_for(added["id"])[0]["id"] == "read"


def test_a_new_mcp_server_keeps_its_token_in_the_secret_store(stores):
    draft = connector_builder.draft("https://mcp.acme.dev/mcp", propose=_never)
    added = connector_builder.add(draft["draft_id"], fields={"token": "acme-secret-token-1234"})
    assert stores[f"connector:{added['id']}:token"] == ["acme-secret-token-1234"]
    custom = json.loads(connector_builder._custom_path().read_text(encoding="utf-8"))
    assert "acme-secret-token-1234" not in json.dumps(custom)
    assert connector_use.entry(added["id"])["mcp_url"] == "https://mcp.acme.dev/mcp"


def test_an_address_typed_into_the_draft_must_be_https(stores):
    draft = connector_builder.draft("https://api.acme.dev/v2", propose=_never)
    with pytest.raises(connector_builder.BuilderError, match="https"):
        connector_builder.add(draft["draft_id"], fields={"base_url": "http://api.acme.dev/v2"})


def test_unknown_words_still_fall_back_to_a_validated_proposal(stores):
    def propose(_text):
        return json.dumps({"name": "Acme", "kind": "rest", "base_url": "http://insecure.example.com",
                           "fields": [{"key": "api_key", "label": "API key", "secret": True}]})

    draft = connector_builder.draft("connect the acme widgets thing", propose=propose)
    assert draft["source"] == "proposed" and draft["kind"] == "rest"
    assert any(f["key"] == "base_url" for f in draft["fields"])  # the http address was refused, so it is asked for


def test_the_find_route_returns_a_draft(stores):
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app, client=("127.0.0.1", 50030))
    draft = client.post("/api/connectors/find", json={"text": "add wikipedia"}).json()["draft"]
    assert draft["ready"] and draft["catalog_id"] == "wikipedia"
    added = client.post("/api/connectors/add", json={"draft_id": draft["draft_id"]}).json()
    assert added["connected"] and added["connector"]["connected"]
