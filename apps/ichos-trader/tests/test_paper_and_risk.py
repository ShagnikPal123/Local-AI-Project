"""The practice account charges real-world costs, and the hard rules hold whatever a bot asks."""

from __future__ import annotations

import pytest

from ichos_trader import config, risk
from ichos_trader.models import BrokerError, Instrument, Order, Quote
from ichos_trader.paper import PaperAccount

BTC = Quote("BTC-USD", 100.0, 99.9, 100.1)
AAPL = Quote("AAPL", 50.0)


def test_buys_pay_the_ask_and_fees_and_sells_pay_the_bid():
    account = PaperAccount()
    buy = account.place(Order("BTC-USD", "buy", 10, "crypto", bot="Trader Vega"), BTC)
    assert buy.price > 100.1 and buy.fee > 0
    sell = account.place(Order("BTC-USD", "sell", 10, "crypto"), BTC)
    assert sell.price < 99.9
    state = account.account()
    assert state["equity"] < 10_000 and state["losses"] == 1 and state["win_rate"] == 0.0
    assert account.positions() == []


def test_a_winning_round_trip_counts_as_a_win():
    account = PaperAccount()
    account.place(Order("AAPL", "buy", 10, "stock"), AAPL)
    account.place(Order("AAPL", "sell", 10, "stock"), Quote("AAPL", 60.0))
    assert account.account()["wins"] == 1 and account.account()["realized"] > 90


def test_it_cannot_spend_money_it_does_not_have_or_sell_what_it_does_not_hold():
    account = PaperAccount()
    with pytest.raises(BrokerError, match="Not enough practice cash"):
        account.place(Order("AAPL", "buy", 1_000, "stock"), AAPL)
    with pytest.raises(BrokerError, match="No short selling"):
        account.place(Order("AAPL", "sell", 1, "stock"), AAPL)
    assert account.account()["cash"] == 10_000


def test_marking_prices_values_holdings_and_keeps_a_curve():
    account = PaperAccount()
    account.place(Order("AAPL", "buy", 10, "stock", bot="Trader Nova"), AAPL)
    account.mark({"AAPL": 55.0})
    position = account.positions()[0]
    assert position["price"] == 55.0 and position["pl"] > 0 and position["bot"] == "Trader Nova"
    assert len(account.curve()) == 1


def test_reset_starts_over_with_the_cash_asked_for():
    assert PaperAccount().reset(500)["equity"] == 500


def _check(order, quote=AAPL, positions=(), settings=None, account=None, inst=None, money="practice"):
    account = account or {"currency": "USD", "cash": 10_000.0, "equity": 10_000.0, "peak": 10_000.0}
    return risk.check(order, quote, inst or Instrument(order.symbol, order.asset_class), account, list(positions),
                      settings or config.default_settings(), money)


def test_real_money_is_always_refused():
    qty, why = _check(Order("AAPL", "buy", 1), money="real")
    assert qty == 0 and "Real money is off" in why[0]


def test_one_market_is_capped_at_its_share_of_the_money():
    qty, why = _check(Order("AAPL", "buy", 100))  # 5,000 wanted, cap is 20% of 10,000
    assert qty == pytest.approx(40) and "Trimmed" in why[0]


def test_buys_are_halved_after_a_drawdown_and_never_exceed_cash():
    account = {"currency": "USD", "cash": 100.0, "equity": 9_000.0, "peak": 10_000.0}
    qty, why = _check(Order("AAPL", "buy", 10), account=account)
    assert qty * 50 <= 100
    assert any("halved" in w for w in why) and any("no borrowing" in w for w in why)


def test_sells_are_limited_to_what_is_held_and_other_currencies_are_skipped():
    held = [{"symbol": "AAPL", "qty": 3, "value": 150.0}]
    assert _check(Order("AAPL", "sell", 10), positions=held)[0] == 3
    yen = Instrument("USD-JPY", "fx", quote_currency="JPY")
    qty, why = _check(Order("USD-JPY", "buy", 1, "fx"), quote=Quote("USD-JPY", 150.0), inst=yen)
    assert qty == 0 and "JPY" in why[0]
