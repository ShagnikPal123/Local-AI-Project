"""The connectors catalogue (Plan Null N10, Update 1 U9/U24): honest data, secrets kept out of sight, real calls."""

from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest

import connector_builder
import connector_use
from connectors import catalog


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    """Every connector store and the secret store point at this test's folder (never the owner's)."""
    secrets = {}
    import secret_store

    monkeypatch.setattr(secret_store, "get_keys", lambda name: list(secrets.get(name, [])))
    monkeypatch.setattr(secret_store, "set_keys",
                        lambda name, values: secrets.__setitem__(name, [v for v in values if v]) or list(values))
    monkeypatch.setattr(catalog, "_store_path", lambda: tmp_path / "connections.json")
    monkeypatch.setattr(connector_builder, "_custom_path", lambda: tmp_path / "custom.json")
    monkeypatch.setattr(connector_builder, "_store_path", lambda: tmp_path / "custom_connections.json")
    monkeypatch.setattr(connector_use, "_settings_path", lambda: tmp_path / "use.json")
    connector_use._cc_tokens.clear()
    return secrets


class _Response:
    def __init__(self, status=200, payload=None, text=None, headers=None):
        self.status_code = status
        self.text = text if text is not None else json.dumps(payload if payload is not None else {})
        self.headers = headers or {"Content-Type": "application/json"}
        self._payload = payload

    def json(self):
        return self._payload if self._payload is not None else json.loads(self.text)


class _Http:
    """Records every request; answers with ``reply`` (or a function of the request)."""

    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply or (lambda call: _Response(200, {"ok": True}))

    def request(self, method, url, headers=None, params=None, data=None, timeout=0, **_):
        call = {"method": method, "url": url, "headers": dict(headers or {}), "params": dict(params or {}),
                "body": json.loads(data) if data else None}
        self.calls.append(call)
        return self.reply(call)

    def post(self, url, data=None, json=None, auth=None, headers=None, timeout=0, **_):
        call = {"method": "POST", "url": url, "data": data, "json": json, "auth": auth, "headers": dict(headers or {})}
        self.calls.append(call)
        return self.reply(call)


@pytest.fixture()
def http(monkeypatch):
    fake = _Http()
    monkeypatch.setattr(connector_use, "_requests", lambda: fake)
    return fake


# --- the catalogue is data, and honest data ---------------------------------------------------------------------


def test_the_catalogue_covers_what_the_owner_asked_for():
    ids = {e["id"] for e in catalog.list_catalog(include_custom=False)}
    asked = {"vercel", "gmail", "google_docs", "google_sheets", "excel", "word", "outlook", "onedrive", "teams",
             "openai", "anthropic", "gemini", "mistral", "github", "notion", "slack", "alpaca", "polygon", "stripe",
             "alpha_vantage", "finnhub", "coinbase", "plaid", "yahoo_finance", "custom_website", "custom_mcp",
             "custom_rest", "zapier", "aws_s3", "supabase", "cloudflare", "wikipedia", "arxiv", "spotify"}
    assert asked <= ids
    assert len(ids) >= 80


def test_every_entry_is_well_formed():
    categories = {c["id"] for c in catalog.categories()}
    seen = set()
    for entry in catalog.list_catalog(include_custom=False):
        assert entry["id"] not in seen and re.fullmatch(r"[a-z0-9_]+", entry["id"]), entry["id"]
        seen.add(entry["id"])
        assert entry["kind"] in catalog.KINDS and entry["category"] in categories, entry["id"]
        assert entry["name"] and entry["description"] and entry["color"].startswith("#")
        for url_key in ("base_url", "mcp_url", "docs_url", "enable_url"):
            value = str(entry.get(url_key) or "")
            assert not value or value.startswith("https://"), (entry["id"], url_key)
        for field in entry["fields"]:
            if field["key"] in ("token", "api_key", "secret", "secret_key", "client_secret", "secret_access_key",
                                "webhook_url", "key"):
                assert field["secret"], (entry["id"], field["key"])
            assert not field.get("help_url") or field["help_url"].startswith("https://")
        for action in entry["actions"]:
            assert action["id"] and action["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE")
            if action["method"] != "GET" and entry["kind"] not in ("webhook",):
                assert "write" in action, (entry["id"], action["id"])
            for name in re.findall(r"\{(\w+)}", action["path"]):
                field_keys = {f["key"] for f in entry["fields"]}
                assert name in action["params"] or name in field_keys, (entry["id"], action["id"], name)
        if entry["kind"] == "rest" and not entry.get("template"):
            assert entry["base_url"], entry["id"]
        if entry["kind"] == "mcp" and not entry.get("template"):
            assert entry["mcp_url"], entry["id"]


def test_secrets_never_appear_in_a_public_entry(stores):
    catalog.connect("github", {"token": "ghp_" + "a" * 36})
    shown = catalog.public(catalog.get("github"))
    assert shown["connected"] and shown["saved"]["token"] == "•••• aaaa"
    assert "ghp_" not in json.dumps(shown)
    assert stores["connector:github:token"] == ["ghp_" + "a" * 36]
    stored = json.loads(catalog._store_path().read_text(encoding="utf-8"))
    assert "ghp_" not in json.dumps(stored)


def test_connect_names_what_is_missing_and_forgives_a_pasted_address(stores):
    with pytest.raises(ValueError, match="API token"):
        catalog.connect("jira", {"site": "acme", "email": "me@acme.com"})
    catalog.connect("jira", {"site": "https://acme.atlassian.net/jira/", "email": "me@acme.com", "token": "t" * 24})
    assert catalog.connection_values("jira")["site"] == "acme"
    with pytest.raises(ValueError):
        catalog.connect("jira", {"site": "acme corp!", "email": "a@b.c", "token": "t" * 24})


def test_a_keyless_connector_turns_on_and_off(stores):
    assert not catalog.is_connected("wikipedia")
    catalog.connect("wikipedia", {})
    assert catalog.is_connected("wikipedia")
    assert catalog.disconnect("wikipedia") and not catalog.is_connected("wikipedia")


def test_disconnect_removes_the_secrets(stores):
    catalog.connect("vercel", {"token": "v" * 24})
    assert catalog.disconnect("vercel")
    assert stores.get("connector:vercel:token") == []
    assert catalog.connection_values("vercel") == {}


def test_sign_in_apps_are_not_connected_with_a_form(stores):
    for connector_id in ("gmail", "google_sheets", "excel"):
        with pytest.raises(ValueError, match="Sign in"):
            catalog.connect(connector_id, {"token": "x" * 20})


def test_an_ai_provider_shares_the_key_keys_and_models_uses(stores, monkeypatch):
    saved = {}
    import routes_models

    monkeypatch.setattr(routes_models, "store_provider_key", lambda provider, key: saved.update({provider: key}))
    catalog.connect("groq", {"api_key": "gsk_" + "b" * 30})
    assert saved == {"groq": "gsk_" + "b" * 30}
    with pytest.raises(ValueError, match="too short"):
        catalog.connect("groq", {"api_key": "short"})


def test_a_webhook_must_be_on_the_services_own_domain(stores):
    with pytest.raises(ValueError, match="hooks.zapier.com"):
        catalog.connect("zapier", {"webhook_url": "https://evil.example.com/catch"})
    with pytest.raises(ValueError, match="https"):
        catalog.connect("zapier", {"webhook_url": "http://hooks.zapier.com/hooks/catch/1/2"})
    catalog.connect("zapier", {"webhook_url": "https://hooks.zapier.com/hooks/catch/1/abc"})
    assert catalog.is_connected("zapier")


def test_gmail_counts_as_connected_through_an_app_password(stores, monkeypatch):
    monkeypatch.setattr(catalog, "_google_accounts", lambda product: [])
    monkeypatch.setattr(catalog, "_mail_accounts", lambda provider="": ["owner@gmail.com"] if provider in ("", "gmail") else [])
    assert catalog.is_connected("gmail")
    state = catalog.status("gmail")
    assert state["how"] == "app password" and state["mail_accounts"] == ["owner@gmail.com"]
    assert not catalog.is_connected("google_sheets")


def test_google_apps_use_the_sign_in_token(stores, monkeypatch, http):
    import google_oauth

    monkeypatch.setattr(google_oauth, "accounts_for", lambda product: ["owner@gmail.com"] if product == "sheets" else [])
    monkeypatch.setattr(google_oauth, "access_token", lambda address, http=None: "ya29.token")
    assert catalog.is_connected("google_sheets") and not catalog.is_connected("google_docs")
    connector_use.call("google_sheets", "values", params={"spreadsheet_id": "abc123", "range": "Sheet1!A1:B2"})
    call = http.calls[-1]
    assert call["url"] == "https://sheets.googleapis.com/v4/spreadsheets/abc123/values/Sheet1%21A1:B2"
    assert call["headers"]["Authorization"] == "Bearer ya29.token"


# --- calling connectors ----------------------------------------------------------------------------------------


def test_a_bearer_call_reaches_only_the_connectors_own_host(stores, http):
    catalog.connect("github", {"token": "ghp_" + "c" * 36})
    result = connector_use.call("github", "issues", params={"owner": "octo", "repo": "hello world", "state": "open"})
    call = http.calls[-1]
    assert result["ok"] and call["method"] == "GET"
    assert call["url"] == "https://api.github.com/repos/octo/hello%20world/issues"
    assert call["params"] == {"state": "open"} and call["headers"]["Authorization"] == "Bearer ghp_" + "c" * 36
    connector_use.call("github", "", path="//evil.example.com/steal")  # a raw path still lands on GitHub
    assert urlsplit(http.calls[-1]["url"]).hostname == "api.github.com"
    connector_use.call("github", "", path="@evil.example.com/steal")
    assert urlsplit(http.calls[-1]["url"]).hostname == "api.github.com"
    with pytest.raises(connector_use.ConnectorCallError, match="https"):
        connector_use._https("http://api.github.com/user")


def test_a_path_value_cannot_reshape_the_path(stores, http):
    catalog.connect("github", {"token": "ghp_" + "d" * 36})
    connector_use.call("github", "issues", params={"owner": "../../orgs", "repo": "x"})
    assert "/repos/..%2F..%2Forgs/x/issues" in http.calls[-1]["url"]


def test_basic_auth_and_a_site_in_the_address(stores, http):
    catalog.connect("jira", {"site": "acme", "email": "me@acme.com", "token": "jira-token-123456"})
    connector_use.call("jira", "search", params={"jql": "assignee = currentUser()"})
    call = http.calls[-1]
    assert call["url"] == "https://acme.atlassian.net/rest/api/3/search/jql"
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"me@acme.com:jira-token-123456").decode()


def test_several_query_credentials_and_fixed_query_values(stores, http):
    catalog.connect("trello", {"api_key": "k" * 32, "token": "t" * 64})
    connector_use.call("trello", "boards")
    assert http.calls[-1]["params"] == {"key": "k" * 32, "token": "t" * 64}
    catalog.connect("alpha_vantage", {"token": "AV" * 8})
    connector_use.call("alpha_vantage", "quote", params={"symbol": "IBM"})
    assert http.calls[-1]["params"] == {"function": "GLOBAL_QUOTE", "symbol": "IBM", "apikey": "AV" * 8}


def test_header_pairs_and_a_chosen_environment(stores, http):
    catalog.connect("alpaca", {"key_id": "PKTEST", "secret_key": "s" * 40})
    connector_use.call("alpaca", "account")
    call = http.calls[-1]
    assert call["url"] == "https://paper-api.alpaca.markets/v2/account"  # practice money unless the owner picks real
    assert call["headers"]["APCA-API-KEY-ID"] == "PKTEST" and call["headers"]["APCA-API-SECRET-KEY"] == "s" * 40


def test_a_write_sends_json_and_needs_a_yes_first(stores, http):
    catalog.connect("slack", {"token": "xoxb-" + "1" * 30})
    message = connector_use.tool_use_connector("slack", "post", {"channel": "C1", "text": "hi"})
    assert "Ask them" in message and not http.calls
    connector_use.tool_use_connector("slack", "post", {"channel": "C1", "text": "hi"}, confirm=True)
    assert http.calls[-1]["method"] == "POST" and http.calls[-1]["body"] == {"channel": "C1", "text": "hi"}


def test_structured_arguments_arrive_as_structures(stores, http, monkeypatch):
    import google_oauth

    monkeypatch.setattr(google_oauth, "accounts_for", lambda product: ["o@gmail.com"])
    monkeypatch.setattr(google_oauth, "access_token", lambda address, http=None: "ya29.t")
    connector_use.call("google_sheets", "append",
                       params={"spreadsheet_id": "s1", "range": "Sheet1!A1", "values": '[["2026-10-04", 12.5]]'})
    call = http.calls[-1]
    assert call["url"].endswith("/spreadsheets/s1/values/Sheet1%21A1:append")
    assert call["params"] == {"valueInputOption": "USER_ENTERED"} and call["body"] == {"values": [["2026-10-04", 12.5]]}


def test_s3_requests_are_signed_with_every_amz_header(stores, http):
    catalog.connect("aws_s3", {"region": "us-west-2", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "x" * 40})
    connector_use.call("aws_s3", "files", params={"bucket": "my-bucket", "prefix": "notes/"})
    call = http.calls[-1]
    assert call["url"] == "https://s3.us-west-2.amazonaws.com/my-bucket?list-type=2&prefix=notes%2F"
    auth = call["headers"]["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/") and "/us-west-2/s3/aws4_request" in auth
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in auth
    assert "x" * 40 not in json.dumps(call)


def test_client_credentials_are_exchanged_once_and_reused(stores, monkeypatch):
    def reply(call):
        if call["url"].startswith("https://accounts.spotify.com"):
            return _Response(200, {"access_token": "BQ-token", "expires_in": 3600})
        return _Response(200, {"tracks": {"items": []}})

    fake = _Http(reply)
    monkeypatch.setattr(connector_use, "_requests", lambda: fake)
    catalog.connect("spotify", {"client_id": "cid", "client_secret": "csecret-123"})
    connector_use.call("spotify", "search", params={"q": "daft punk", "type": "track"})
    connector_use.call("spotify", "search", params={"q": "air", "type": "track"})
    exchanges = [c for c in fake.calls if c["url"].startswith("https://accounts.spotify.com")]
    assert len(exchanges) == 1 and exchanges[0]["auth"] == ("cid", "csecret-123")
    assert fake.calls[-1]["headers"]["Authorization"] == "Bearer BQ-token"


def test_a_webhook_call_posts_to_the_saved_hook(stores, http):
    catalog.connect("zapier", {"webhook_url": "https://hooks.zapier.com/hooks/catch/1/abc"})
    result = connector_use.call("zapier", "send", params={"name": "Ada", "rows": "[1, 2]"})
    assert result["ok"] and http.calls[-1]["url"] == "https://hooks.zapier.com/hooks/catch/1/abc"
    assert http.calls[-1]["json"] == {"name": "Ada", "rows": [1, 2]}


def test_a_built_in_app_points_the_model_at_its_tools(stores, monkeypatch):
    monkeypatch.setattr(catalog, "_google_accounts", lambda product: [])
    monkeypatch.setattr(catalog, "_mail_accounts", lambda provider="": ["owner@gmail.com"])
    message = connector_use.tool_use_connector("gmail", "search", {"q": "is:unread"})
    assert "email_list" in message


def test_a_not_connected_sign_in_app_says_how_to_connect(stores, monkeypatch):
    monkeypatch.setattr(catalog, "_microsoft_accounts", lambda product: [])
    assert "Sign in with Microsoft" in connector_use.tool_use_connector("excel", "worksheets", {"item_id": "1"})


def test_a_website_connector_reads_its_own_pages_only(stores, monkeypatch):
    import absorb_sources

    connector_builder.connect("docs-site", {}, {"id": "docs-site", "name": "Docs", "kind": "website",
                                                 "base_url": "https://docs.example.com", "auth": {"type": "none"},
                                                 "fields": []})
    monkeypatch.setattr(absorb_sources, "fetch", lambda url, **_: (b"<title>Pricing</title><p>Ten dollars</p>",
                                                                  "text/html", url))
    result = connector_use.call("docs-site", path="/pricing")
    assert result["ok"] and "Ten dollars" in result["data"]
    with pytest.raises(connector_use.ConnectorCallError):
        connector_use.call("docs-site", path="https://elsewhere.example.org/")


def test_mentions_and_prediction_use_the_whole_catalogue(stores):
    assert connector_use.mentions("put this in &sheets and ping &vercel") == ["google_sheets", "vercel"]
    guess = connector_use.predict("check my latest vercel deployment", limit=1)
    assert guess and guess[0]["id"] == "vercel"


def test_the_catalogue_route_lists_everything_without_secrets(stores, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    catalog.connect("github", {"token": "ghp_" + "e" * 36})
    client = TestClient(server.app, client=("127.0.0.1", 50020))
    body = client.get("/api/connectors/catalog").json()
    assert body["total"] >= 80 and any(c["id"] == "github" and c["connected"] for c in body["connectors"])
    assert "ghp_" not in json.dumps(body)
    assert [c["id"] for c in body["categories"]][:2] == ["google", "microsoft"]
    detail = client.get("/api/connectors/catalog/gmail").json()["connector"]
    assert detail["kind"] == "oauth_google" and detail["actions"][0]["path"]
    assert client.get("/api/connectors/catalog/nope").status_code == 404
    assert client.post("/api/connectors/wikipedia/connect", json={"fields": {}}).json()["connector"]["connected"]
    assert client.delete("/api/connectors/wikipedia").json()["removed"]


def test_connector_writes_are_refused_from_another_machine(stores):
    from fastapi.testclient import TestClient

    import server

    remote = TestClient(server.app, client=("203.0.113.9", 50021))
    assert remote.post("/api/connectors/github/connect", json={"fields": {"token": "x" * 20}}).status_code == 403
    assert remote.post("/api/connectors/find", json={"text": "add vercel"}).status_code == 403
