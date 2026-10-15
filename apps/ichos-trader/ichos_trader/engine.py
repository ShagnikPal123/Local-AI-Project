"""The engine: one cycle passes through the whole team, and a supervised loop runs it 24/7.

One cycle (docs/DESIGN.md has the walk-through):

1. **Scout** (Iris) fetches every enabled market in parallel and ``ranking`` scores them.
2. **Strategist** (Sage) studies a few markets' history. In learn-first mode nothing is bought
   until the playbook is full, because a trader that has not studied is guessing.
3. **Advisor** (Atlas) matches each market to the strategy that worked best in markets like it.
4. **Traders** propose orders, the **mild skeptic** (Mira) stops or shrinks the fishy ones, and the
   hard rules in ``risk`` have the last word before the paper broker fills them.
5. Every few cycles the **manager** (Max) moves money between traders, hires, retires and tunes.
6. **Researcher** (Echo) writes a short note on the top pick, predictions are made and graded,
   and the **watchdog** shuts everything down if it is slow or losing.

The loop runs in a background thread and survives its own errors (a supervisor backs off and tries
again), so a bad response from one feed never stops the trader for good. Only the watchdog, the
owner or a shut-down of the process stops it, and ``resume_if_running`` picks it back up after a
restart.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from . import currency, ranking, risk, settings as settings_mod, store, watchdog
from .core import clock as market_clock, forecast
from .latency import Recorder, Stopwatch
from .markets import MarketHub
from .models import BrokerError, Instrument, Order, Snapshot
from .paper import PaperAccount
from .team import Team, advisor, manager, skeptic, strategist, traders

GROUPS = {"crypto": ["crypto"], "stocks": ["stock", "etf"], "fx": ["fx"]}
ALL_CLASSES = ["crypto", "stock", "etf", "fx"]
TOP = 40
PREDICT_TOP = 5
PREDICTION_HOURS = 24
ERROR_BACKOFF = (5, 15, 60, 300)


def _empty_state() -> Dict[str, Any]:
    return {"cycles": 0, "run_started_at": 0.0, "run_start_equity": 0.0, "stopped_reason": "", "paused": "",
            "last_cycle_at": 0.0, "next_cycle_at": 0.0, "scanned": 0, "markets": [], "plan": {},
            "predictions": [], "research": [], "errors": 0, "last_error": ""}


class Engine:
    def __init__(self, hub: Optional[MarketHub] = None, broker: Any = None, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.hub = hub or MarketHub(clock=clock)
        self.broker = broker or PaperAccount(clock)
        self.team = Team()
        self.recorder = Recorder()
        self.state: Dict[str, Any] = {**_empty_state(), **store.read("engine")}
        self._cycle_ms: Deque[float] = deque(self.state.pop("cycle_ms", []), maxlen=50)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- switching on and off -----------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            settings_mod.save({"running": True})
            self.state.update(stopped_reason="", paused="", errors=0,
                              run_started_at=self.clock(), run_start_equity=self.broker.account()["equity"])
            self._save()
        self.team.notes.add(self.team.one("manager"), "Switched on.", "info")
        self._launch()

    def stop(self, reason: str = "") -> None:
        with self._lock:
            settings_mod.save({"running": False})
            self.state["stopped_reason"] = reason
            self.state["paused"] = ""
            self._save()
        self.team.notes.add(self.team.one("manager"), reason or "Switched off by the owner.", "warn" if reason else "info")
        self.team.save()
        self._wake.set()

    def resume_if_running(self) -> None:
        """After a restart, carry on if it was on (24/7), unless the watchdog had stopped it."""
        if settings_mod.load().get("running") and not self.state.get("stopped_reason"):
            self._launch()

    def running(self) -> bool:
        return bool(settings_mod.load().get("running"))

    def _launch(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, name="ichos-trader", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        """The supervisor: run a cycle, wait the pace, and back off (never die) on errors."""
        while True:
            try:
                with self._lock:  # checked under the lock, so a stop can never be followed by one more cycle
                    if not self.running():
                        return
                    self.run_cycle()
                wait = float(settings_mod.effective().get("pace_seconds", 60))
            except Exception as error:  # noqa: BLE001 - the loop must outlive any one bad cycle
                with self._lock:
                    self.state["errors"] = int(self.state.get("errors", 0)) + 1
                    self.state["last_error"] = f"{type(error).__name__}: {error}"[:300]
                    self._save()
                wait = ERROR_BACKOFF[min(len(ERROR_BACKOFF) - 1, self.state["errors"] - 1)]
                self.team.notes.add(self.team.one("manager"), f"A cycle failed ({self.state['last_error']}); "
                                                              f"trying again in {wait} s.", "warn")
            if self._wake.wait(wait):
                self._wake.clear()

    # --- one cycle ----------------------------------------------------------------------------

    def run_cycle(self) -> Dict[str, Any]:
        with self._lock:
            return self._cycle()

    def _cycle(self) -> Dict[str, Any]:
        now = self.clock()
        cfg = settings_mod.effective()
        watch = Stopwatch()
        team = self.team

        with watch.stage("fetch"):
            snaps = self._scout(cfg)
        by_symbol = {s.symbol: s for s in snaps if not s.error and s.quote}
        with watch.stage("rank"):
            ranked = ranking.rank(list(by_symbol.values()))
        rows = {r["symbol"]: r for r in ranked}
        if hasattr(self.broker, "mark"):
            self.broker.mark({s: snap.quote.price for s, snap in by_symbol.items()})
        best = ranked[0]["symbol"] if ranked else "nothing"
        team.set_doing(team.one("scout"), f"Ranked {len(ranked)} of {len(snaps)} markets; {best} on top.")

        ages = [now - s.quote.at for s in by_symbol.values() if s.quote.at]
        self.state["paused"] = watchdog.stale(ages, cfg["shutdown"]) if ranked else "Paused: no prices came back."
        orders_done: List[Dict[str, Any]] = []
        learning = False
        decision_ms = 0.0
        if not self.state["paused"]:
            with watch.stage("study"):
                strategist.study(list(by_symbol.values()), team, now)
            learning = bool(cfg.get("learn_first")) and not strategist.learning_status()["done"]
            with watch.stage("advise"):
                advice = advisor.advise_all([by_symbol[r["symbol"]] for r in ranked[:120]], team)
            positions, account = self.broker.positions(), self.broker.account()
            orders: List[Order] = []
            with watch.stage("decide"):
                taken = {p["symbol"] for p in positions}
                for trader in team.traders() if positions or not learning else []:
                    proposed = traders.decide(trader, rows, advice, positions, account, cfg, taken, team)
                    orders += [o for o in proposed if o.side == "sell" or not learning]
                self.state["cycles"] = int(self.state["cycles"]) + 1
                if self.state["cycles"] % manager.EVERY == 0:
                    sells, chosen = manager.review(team, self.broker.fills(500), positions, account, rows, cfg)
                    orders += sells
                    if chosen:
                        store.write("chosen", chosen)
            decision_ms = (watch.stages.get("rank", 0) + watch.stages["advise"] + watch.stages["decide"]) / max(1, len(rows))
            with watch.stage("orders"):
                for order in orders:
                    done = self._execute(order, by_symbol.get(order.symbol), rows.get(order.symbol),
                                         advice.get(order.symbol), cfg, now)
                    if done:
                        orders_done.append(done)
            if learning:
                left = strategist.LEARN_TARGET - strategist.learning_status()["studied"]
                team.notes.add(team.one("strategist"), f"Learning first: {max(left, 0)} more markets to study "
                                                       "before the first buy.", "info")
        else:
            team.notes.add(team.one("scout"), self.state["paused"], "warn")

        with watch.stage("predict"):
            self._predict(ranked, by_symbol, now)
            self._research(ranked, now)

        account = self.broker.account()
        self._cycle_ms.append(watch.total_ms)
        self.recorder.add(watch.total_ms, decision_ms, dict(watch.stages), len(snaps))
        hours = (now - float(self.state["run_started_at"] or now)) / 3600
        reason = watchdog.check(recent_cycle_ms=list(self._cycle_ms), equity=account["equity"], peak=account["peak"],
                                run_start_equity=float(self.state["run_start_equity"] or account["equity"]),
                                run_hours=hours, rules=cfg["shutdown"])
        self.state.update(last_cycle_at=now, next_cycle_at=now + float(cfg["pace_seconds"]), scanned=len(snaps),
                          markets=ranked[:TOP], errors=0, plan=self._plan(ranked, cfg, learning, now))
        self._save()
        team.save()
        if reason and self.running():
            self.stop(reason)
        return {"ok": True, "ms": round(watch.total_ms, 1), "orders": orders_done, "learning": learning,
                "stopped": reason}

    def _scout(self, cfg: Dict[str, Any]) -> List[Snapshot]:
        classes = [c for market, on in cfg["markets"].items() if on for c in GROUPS.get(market, [market])]
        wanted = self.hub.instruments(classes)[: int(cfg["scan_limit"])]
        have = {i.symbol for i in wanted}
        held = {p["symbol"] for p in self.broker.positions()} - have
        if held:  # always price what is held, even if its market was switched off
            wanted += [i for i in self.hub.instruments(ALL_CLASSES) if i.symbol in held]
        return self._fetch(wanted)

    def _fetch(self, wanted: List[Instrument], with_book: bool = True) -> List[Snapshot]:
        """Snapshots of ``wanted`` with every price already in the account's currency."""
        base = self.broker.account()["currency"]
        extra: List[Instrument] = []
        if currency.needs_rates(wanted, base):  # fetch the currency pairs needed to convert, once
            names = {i.symbol for i in wanted}
            extra = [i for i in self.hub.instruments(["fx"]) if i.symbol in currency.RATE_PAIRS and i.symbol not in names]
        snaps = self.hub.snapshots(wanted + extra, with_book=with_book)
        worth = currency.rates(snaps, base)
        return [currency.to_base(s, base, worth) for s in snaps[:len(wanted)]]

    def _execute(self, order: Order, snap: Optional[Snapshot], row: Optional[Dict[str, Any]],
                 tip: Optional[Dict[str, Any]], cfg: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
        mira = self.team.one("skeptic")
        bot = next((b for b in self.team.active() if b["name"] == order.bot), mira)
        if snap is None or snap.quote is None:
            self.team.notes.add(bot, f"No price for {order.symbol}; order dropped.", "warn", order.symbol)
            return None
        size, level, why = skeptic.review(order, row, tip, float(cfg.get("skeptic", 0.5)), snap.quote.at, now)
        if why:
            self.team.notes.add(mira, f"{order.symbol}: {why}", level, order.symbol)
        if size <= 0:
            return None
        order = dataclasses.replace(order, qty=order.qty * size)
        qty, reasons = risk.check(order, snap.quote, snap.instrument, self.broker.account(), self.broker.positions(),
                                  cfg, self.broker.money())
        if qty <= 0:
            self.team.notes.add(bot, f"Rules stopped {order.side} {order.symbol}: " + " ".join(reasons), "warn", order.symbol)
            return None
        try:
            fill = self.broker.place(dataclasses.replace(order, qty=qty), snap.quote)
        except BrokerError as error:
            self.team.notes.add(bot, f"The broker refused {order.symbol}: {error}", "warn", order.symbol)
            return None
        strategist.record_fill(fill, tip or {}, self.team)
        self.team.notes.add(bot, f"{'Bought' if fill.side == 'buy' else 'Sold'} {fill.qty:.6g} {fill.symbol} at "
                                 f"{fill.price:,.4g} (${fill.value:,.2f}, practice money).", "trade", fill.symbol)
        return fill.to_dict()

    def speedtest(self) -> Dict[str, Any]:
        """A timed cycle on the current markets that places nothing and writes nothing to the feed."""
        with self._lock:
            cfg = settings_mod.effective()
            watch = Stopwatch()
            quiet = _QuietTeam(self.team)
            with watch.stage("fetch"):
                snaps = [s for s in self._scout(cfg) if not s.error and s.quote]
            with watch.stage("rank"):
                rows = {r["symbol"]: r for r in ranking.rank(snaps)}
            with watch.stage("decide"):
                advice = advisor.advise_all([s for s in snaps if s.symbol in rows][:120], quiet)
                positions, account = self.broker.positions(), self.broker.account()
                taken = {p["symbol"] for p in positions}
                for trader in quiet.traders():
                    traders.decide(trader, rows, advice, positions, account, cfg, taken, quiet)
            decision_ms = (watch.stages["rank"] + watch.stages["decide"]) / max(1, len(rows))
            self.recorder.add(watch.total_ms, decision_ms, dict(watch.stages), len(snaps))
            summary = self.recorder.summary()
            return {"grade": summary["grade"], "words": summary["words"], "stages": summary["stages"],
                    "decision_ms": round(decision_ms, 2), "cycle_ms": round(watch.total_ms, 1), "markets": len(snaps),
                    "targets": {k: {"fast": v[0], "ok": v[1]} for k, v in summary["targets"].items()}}

    # --- predictions, research and the plan ---------------------------------------------------

    def _predict(self, ranked: List[Dict[str, Any]], by_symbol: Dict[str, Snapshot], now: float) -> None:
        """Grade predictions that have come due, then make one for each top pick without one."""
        keep = []
        for p in self.state["predictions"]:
            snap = by_symbol.get(p["symbol"])
            if not p["graded"] and now - p["made_at"] >= p["horizon_h"] * 3600 and snap is not None:
                moved = (snap.quote.price / p["price"] - 1) * 100
                p.update(graded=True, actual_pct=round(moved, 2),
                         right=(moved > 0) == (p["expected_pct"] > 0) or abs(moved) < 0.1 and abs(p["expected_pct"]) < 0.1)
            keep.append(p)
        open_symbols = {p["symbol"] for p in keep if not p["graded"]}
        # The top picks, plus everything held: the money's predicted change is built from the holdings.
        wanted = [r["symbol"] for r in ranked[:PREDICT_TOP]] + [p["symbol"] for p in self.broker.positions()]
        for symbol in dict.fromkeys(wanted):
            snap = by_symbol.get(symbol)
            if snap is None or symbol in open_symbols:
                continue
            years = market_clock.periods_per_year(snap.instrument.asset_class)
            cone = forecast.predict(snap.closes, horizon=1, seed=int(now) % 100_000, periods_per_year=years)
            if not cone.get("ok"):
                continue
            keep.append({"symbol": symbol, "horizon_h": PREDICTION_HOURS, "expected_pct": cone["expected_change_pct"],
                         "low_pct": cone["band_pct"][0], "high_pct": cone["band_pct"][1],
                         "confidence": cone["confidence"], "price": snap.quote.price, "made_at": now,
                         "graded": False, "right": None})
        self.state["predictions"] = keep[-200:]

    def _research(self, ranked: List[Dict[str, Any]], now: float) -> None:
        """Echo's note on the top pick, at most once an hour per market, from the numbers alone."""
        if not ranked:
            return
        top = ranked[0]
        recent = [r for r in self.state["research"] if r["symbol"] == top["symbol"] and now - r["at"] < 3600]
        if recent:
            return
        echo = self.team.one("researcher")
        summary = (f"{top['name']}: rank {top['score']:.2f}, {top['signal']} at {top['confidence']:.0%}. "
                   f"Spread {top['spread_bps']:.1f} bp, about ${top['dollar_volume']:,.0f} traded a day, "
                   f"order flow {top['flow']:+.2f}. " + " ".join(top.get("reasons", [])[:2]))
        self.state["research"] = (self.state["research"] + [{"at": now, "symbol": top["symbol"], "summary": summary,
                                                             "source": "the numbers (no model)"}])[-40:]
        self.team.set_doing(echo, f"Wrote up {top['symbol']}.")

    def _plan(self, ranked: List[Dict[str, Any]], cfg: Dict[str, Any], learning: bool, now: float) -> Dict[str, Any]:
        held = self.broker.positions()
        steps = [f"Re-rank {len(ranked)} markets"]
        if held:
            steps.append(f"Check stops on {len(held)} holding{'s' if len(held) != 1 else ''}")
        if learning:
            steps.append(f"Study up to {strategist.PER_CYCLE} more markets before buying")
        if (int(self.state["cycles"]) + 1) % manager.EVERY == 0:
            steps.append("Manager reviews the team")
        return {"next_cycle_at": now + float(cfg["pace_seconds"]), "steps": steps,
                "focus": [r["symbol"] for r in ranked[:3]]}

    # --- the one-call dashboard ---------------------------------------------------------------

    def flatten(self) -> int:
        """Sell everything the bots hold, at the latest prices. Returns how many were sold."""
        with self._lock:
            sold = 0
            held = self.broker.positions()
            names = {p["symbol"] for p in held}
            snaps = {s.symbol: s for s in self._fetch([i for i in self.hub.instruments(ALL_CLASSES) if i.symbol in names],
                                                      with_book=False)}
            for pos in held:
                snap = snaps.get(pos["symbol"])
                if snap is None or snap.quote is None:
                    continue
                try:
                    self.broker.place(Order(pos["symbol"], "sell", pos["qty"], pos["asset_class"], "Owner",
                                            "Owner sold everything."), snap.quote)
                    sold += 1
                except BrokerError:
                    continue
            self.team.notes.add(self.team.one("manager"), f"Sold {sold} holding(s) on the owner's word.", "trade")
            self.team.save()
            return sold

    def status(self) -> Dict[str, str]:
        if not self.running():
            reason = self.state.get("stopped_reason", "")
            return {"state": "shutdown" if reason else "off", "state_words": reason or "Off. Press start to trade."}
        if self.state.get("paused"):
            return {"state": "paused", "state_words": self.state["paused"]}
        if settings_mod.effective().get("learn_first") and not strategist.learning_status()["done"]:
            return {"state": "learning", "state_words": strategist.learning_status()["words"] + " No buying yet."}
        return {"state": "trading", "state_words": f"Trading {self.state['scanned']} markets with "
                                                   f"{len(self.team.active())} bots."}

    def _money(self, account: Dict[str, Any], now: float) -> Dict[str, Any]:
        curve = self.broker.curve() if hasattr(self.broker, "curve") else []
        day_ago = next((p["equity"] for p in curve if p["t"] >= now - 86_400), account["start"])
        expected = low = high = 0.0
        open_preds = {p["symbol"]: p for p in self.state["predictions"] if not p["graded"]}
        for pos in self.broker.positions():
            p = open_preds.get(pos["symbol"])
            if p:
                weight = pos["value"] / max(account["equity"], 1)
                expected += weight * p["expected_pct"]
                low += weight * p["low_pct"]
                high += weight * p["high_pct"]
        today = account["equity"] - day_ago
        return {"currency": account["currency"], "equity": account["equity"], "cash": account["cash"],
                "start": account["start"], "pl": account["pl"], "pl_pct": account["pl_pct"],
                "today_pl": round(today, 2), "today_pl_pct": round(today / day_ago * 100, 3) if day_ago else 0.0,
                "predicted_pl_pct": round(expected, 2), "predicted_band_pct": [round(low, 2), round(high, 2)],
                "predicted_horizon_h": PREDICTION_HOURS}

    def dashboard(self) -> Dict[str, Any]:
        now = self.clock()
        with self._lock:
            account = self.broker.account()
            graded = [p for p in self.state["predictions"] if p["graded"]]
            right = sum(1 for p in graded if p["right"])
            bots = []
            for b in self.team.active():
                bots.append({"id": b["id"], "name": b["name"], "role": b["role"], "front": b["front"],
                             "status": b["status"], "doing": b["doing"], "style": b.get("style", ""),
                             "classes": b.get("classes", []), "pot": round(b.get("share", 0) * account["equity"], 2),
                             "share": b.get("share", 0), "pl_pct": b.get("pl_pct", 0.0), "trades": b.get("trades", 0),
                             "hired_at": b["hired_at"]})
            return {
                **self.status(),
                "stopped_reason": self.state.get("stopped_reason", ""),
                "money_kind": self.broker.money(),
                "market_source": self.hub.source,
                "money": self._money(account, now),
                "win_rate": {"closed": account["closed"], "wins": account["wins"], "rate": account["win_rate"]},
                "equity_curve": self._curve(account, now),
                "scanned": self.state["scanned"],
                "markets": self.state["markets"],
                "positions": self.broker.positions(),
                "trades": self.broker.fills(50),
                "bots": bots,
                "bots_running": sum(1 for b in bots if b["status"] == "working"),
                "thinking": self.team.notes.latest(60),
                "plan": self.state.get("plan") or {},
                "predictions": [p for p in reversed(self.state["predictions"])][:30],
                "prediction_record": {"graded": len(graded), "right": right,
                                      "rate": round(right / len(graded), 3) if graded else None},
                "research": list(reversed(self.state["research"]))[:20],
                "speed": self.recorder.summary(),
                "learning": strategist.learning_status(),
                "hires": self.team.roster.get("hires", []),
                "shifts": self.team.roster.get("shifts", []),
                "last_error": self.state.get("last_error", ""),
                "theme": settings_mod.load()["theme"],
                "updated_at": self.state.get("last_cycle_at") or now,
            }

    def _curve(self, account: Dict[str, Any], now: float) -> List[Dict[str, float]]:
        """The saved points (one per 5 minutes) plus where the money is right now."""
        curve = list(self.broker.curve()) if hasattr(self.broker, "curve") else []
        if not curve or now - curve[-1]["t"] > 1:
            curve.append({"t": now, "equity": account["equity"]})
        if len(curve) < 2:  # a line needs two points: start it from the opening balance
            begin = min(float(account.get("created_at") or now), curve[0]["t"] - 1)
            curve.insert(0, {"t": begin, "equity": float(account["start"])})
        return curve

    def _save(self) -> None:
        store.write("engine", {**self.state, "cycle_ms": list(self._cycle_ms)})


class _QuietTeam:
    """The team as the speed test sees it: same roster, but nothing is written to the thinking feed."""

    class _Silent:
        def add(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    def __init__(self, team: Team) -> None:
        self._team = team
        self.notes = self._Silent()

    def one(self, role: str) -> Dict[str, Any]:
        return dict(self._team.one(role))

    def traders(self) -> List[Dict[str, Any]]:
        return [dict(t) for t in self._team.traders()]

    def set_doing(self, *_args: Any, **_kwargs: Any) -> None:
        return None
