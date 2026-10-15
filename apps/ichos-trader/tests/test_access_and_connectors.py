"""Logins, saved keys and connectors: owners change things, viewers only look, keys never leave."""

from __future__ import annotations

import pytest

from ichos_trader.access import auth, secrets
from ichos_trader.connectors import catalog, models
from ichos_trader.connectors.alpaca import LIVE_URL, AlpacaPaper
from ichos_trader.models import BrokerError, Order, Quote

FAKE_SECRET = "s" * 10 + "-not-a-real-key-WXYZ"


class Reply:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


class FakeHttp:
    """Answers by URL; records every call so a test can check where things went."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def _answer(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for part, data in self.answers.items():
            if url.endswith(part):
                return data if isinstance(data, Reply) else Reply(data)
        return Reply({}, 404)

    def get(self, url, **kwargs):
        return self._answer("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, **kwargs)

    def request(self, method, url, **kwargs):
        return self._answer(method, url, **kwargs)


def test_keys_come_back_masked_and_env_wins_over_the_file(monkeypatch):
    secrets.put("alpaca_secret_key", FAKE_SECRET)
    assert secrets.masked("alpaca_secret_key") == {"from": "file", "last4": "…WXYZ"}
    monkeypatch.setenv("ICHOS_ALPACA_SECRET_KEY", "e" * 20 + "ENV1")
    assert secrets.get("alpaca_secret_key").endswith("ENV1") and secrets.masked("alpaca_secret_key")["from"] == "env"
    secrets.put("short", "abc")
    assert secrets.masked("short") == {"from": "file", "last4": "…"}  # too short to show any of it
    secrets.forget("short")
    assert secrets.masked("short") == {}


def test_a_session_cookie_cannot_be_forged_or_kept_past_its_expiry():
    token = auth.session_for("Shagnik", "viewer")
    assert auth.unsign(token)["role"] == "viewer"
    body, mac = token.rsplit(".", 1)
    forged = auth.sign({"name": "x", "role": "owner", "exp": 9e12}).rsplit(".", 1)[0] + "." + mac
    assert auth.unsign(forged) is None
    assert auth.unsign(auth.sign({"role": "owner", "exp": 1})) is None


def test_local_mode_trusts_only_this_pc_and_a_passcode_switches_it_off():
    assert auth.current_user(None, "127.0.0.1")["role"] == "owner"
    assert auth.current_user(None, "203.0.113.9") is None
    secrets.put("passcode", "correct horse battery")
    assert auth.mode() == "passcode" and auth.current_user(None, "127.0.0.1") is None
    assert auth.check_passcode("correct horse battery") and not auth.check_passcode("wrong")


def test_github_login_makes_only_the_named_owner_an_owner(monkeypatch):
    secrets.put("github_client_id", "client-id-123")
    secrets.put("github_client_secret", FAKE_SECRET)
    monkeypatch.setenv("ICHOS_OWNER_GITHUB", "the-owner")
    start = auth.login_url("github", "http://127.0.0.1:8100/api/auth/callback/github")
    assert start["url"].startswith("https://github.com/login/oauth/authorize?") and start["state"] in start["url"]

    def http(login):
        return FakeHttp({"/access_token": {"access_token": "gho_fake"}, "/user": {"login": login, "name": login},
                         "/user/emails": [{"email": f"{login}@example.com", "primary": True, "verified": True}]})

    owner = auth.unsign(auth.finish_login("github", "code", "http://x/cb", http("the-owner")))
    guest = auth.unsign(auth.finish_login("github", "code", "http://x/cb", http("someone-else")))
    assert owner["role"] == "owner" and guest["role"] == "viewer" and guest["email"] == "someone-else@example.com"
    with pytest.raises(auth.AuthError):
        auth.finish_login("github", "code", "http://x/cb", FakeHttp({"/access_token": {"error": "bad_code"}}))
    with pytest.raises(auth.AuthError):
        auth.login_url("google", "http://x/cb")  # not set up


def test_alpaca_is_practice_only_and_sends_orders_to_the_paper_address():
    with pytest.raises(BrokerError):
        AlpacaPaper(base_url=LIVE_URL)
    with pytest.raises(BrokerError):
        AlpacaPaper(http=FakeHttp({})).test()  # no keys yet
    secrets.put("alpaca_key_id", "PKFAKEFAKEFAKE")
    secrets.put("alpaca_secret_key", FAKE_SECRET)
    http = FakeHttp({"/v2/orders": {"id": "o1", "filled_avg_price": "101.5"}})
    fill = AlpacaPaper(http=http).place(Order("BTC-USD", "buy", 0.5, "crypto", "Vega"), Quote("BTC-USD", 100.0))
    method, url, kwargs = http.calls[0]
    assert url == "https://paper-api.alpaca.markets/v2/orders" and kwargs["json"]["symbol"] == "BTC/USD"
    assert fill.price == 101.5 and fill.money == "practice"


def test_connecting_saves_keys_only_after_the_test_passes():
    def refused():
        raise BrokerError("Alpaca refused the keys.")

    with pytest.raises(ValueError, match="refused"):
        catalog.connect("alpaca", {"key_id": "PKFAKE", "secret_key": FAKE_SECRET}, tester=refused)
    assert secrets.get("alpaca_secret_key") is None
    row = catalog.connect("alpaca", {"key_id": "PKFAKE", "secret_key": FAKE_SECRET}, tester=lambda: "Connected.")
    assert row["connected"] and row["masked"]["secret_key"]["last4"] == "…WXYZ" and FAKE_SECRET not in str(row)
    with pytest.raises(ValueError, match="planned"):
        catalog.connect("kraken", {})
    with pytest.raises(ValueError, match="12 characters"):
        catalog.connect("passcode", {"passcode": "short"})


def test_claude_is_only_called_when_switched_on_and_never_sees_keys():
    dash = {"state_words": "Trading", "money": {"equity": 10_000}, "positions": [], "trades": [], "markets": [],
            "thinking": [{"bot": "Mira", "text": "Spread too wide."}]}
    with pytest.raises(models.ModelError, match="off"):
        models.ask_claude("Why?", dash, enabled=False)
    with pytest.raises(models.ModelError, match="no key"):
        models.ask_claude("Why?", dash, enabled=True)
    secrets.put("anthropic_api_key", FAKE_SECRET)
    http = FakeHttp({"/v1/messages": {"model": models.CLAUDE_MODEL, "content": [{"type": "text", "text": "Because."}]}})
    answer = models.ask_claude("Why?", dash, enabled=True, http=http)
    assert answer["answer"] == "Because."
    _, url, kwargs = http.calls[0]
    assert url == models.CLAUDE_URL and kwargs["headers"]["x-api-key"] == FAKE_SECRET
    assert FAKE_SECRET not in str(kwargs["json"]) and "Spread too wide" in str(kwargs["json"])


def test_alpaca_only_sees_and_sells_what_it_bought_and_keeps_to_the_budget():
    secrets.put("alpaca_key_id", "PKFAKEFAKEFAKE")
    secrets.put("alpaca_secret_key", FAKE_SECRET)
    positions = [{"symbol": "AAPL", "asset_class": "us_equity", "qty": "10", "avg_entry_price": "150",
                  "current_price": "160"},  # the person's own shares
                 {"symbol": "BTCUSD", "asset_class": "crypto", "qty": "0.5", "avg_entry_price": "100",
                  "current_price": "110"}]
    http = FakeHttp({"/v2/orders": {"id": "o1", "filled_avg_price": "100"}, "/v2/positions": positions,
                     "/v2/account": {"currency": "USD", "cash": "50000", "equity": "51655"}})
    broker = AlpacaPaper(http=http, budget=1_000)
    assert broker.positions() == []  # nothing bought yet: the person's AAPL is invisible
    with pytest.raises(BrokerError, match="only sells what it bought"):
        broker.place(Order("AAPL", "sell", 10, "stock", "Vega"), Quote("AAPL", 160.0))
    broker.place(Order("BTC-USD", "buy", 0.5, "crypto", "Vega"), Quote("BTC-USD", 100.0))
    mine = broker.positions()
    assert [p["symbol"] for p in mine] == ["BTC-USD"] and mine[0]["bot"] == "Vega"
    account = broker.account()
    assert account["cash"] == 950.0 and account["equity"] == 1005.0  # the budget, not the 50,000 in the account
    assert broker.fills(5)[0]["bot"] == "Vega"
