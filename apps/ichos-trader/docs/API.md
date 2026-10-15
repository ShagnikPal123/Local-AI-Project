# Ichos Trader web API

The dashboard talks to the trader only through these routes. All answers are JSON. Times are unix
seconds (`at`, `t`). Money is in the account's base currency (`currency`, USD by default) unless a
field says otherwise. Percentages are plain numbers (`2.5` means 2.5%).

**Who may call what.** Reading routes need a signed-in user (owner or viewer). Anything that
changes something (start, stop, settings, keys, Claude) needs the **owner**. A viewer can see how
the trader is set up but never use its keys or its account. When the app runs locally with no login
configured, the person at the PC is the owner.

Every request that changes something (anything but GET) must carry the header `x-ichos-trader: 1`.
The dashboard sends it; another website open in the same browser cannot, so it cannot press the
buttons. In local mode the page must be opened at `127.0.0.1` or `localhost`.

Errors come back as `{"detail": "a sentence the owner can read"}` with a 4xx status.

---

## Who am I

`GET /api/me`

```json
{"user": {"name": "Sam", "email": "", "role": "owner"},
 "auth_mode": "local",               // "local" | "passcode" | "google" | "github"
 "providers": ["google", "github"],  // login buttons to show when signed out
 "signed_in": true}
```

`GET /api/auth/login/{provider}` redirects to Google or GitHub. `GET /api/auth/callback/{provider}`
finishes the login and redirects to `/`. `POST /api/auth/passcode` `{"passcode": "…"}` signs in with
the local passcode. `POST /api/auth/logout`.

## Health

`GET /api/health` (no login) → `{"ok": true, "version": "0.1.0", "uptime_s": 12.3}`

## The dashboard (one call draws the whole screen)

`GET /api/dashboard`

```json
{
  "state": "trading",          // "off" | "learning" | "trading" | "paused" | "shutdown"
  "state_words": "Trading 14 markets with 6 bots.",
  "stopped_reason": "",        // filled when the watchdog shut it down
  "money_kind": "practice",    // "practice" | "real" - shown big, never ambiguous
  "broker": "Practice account (simulated money)",  // or "Alpaca practice account"
  "broker_error": "",          // why the broker can't be reached; the rest of the screen still draws
  "budget": null,              // with Alpaca: the most money the bots may use
  "money": {
    "currency": "USD", "equity": 10234.5, "cash": 6120.0, "start": 10000.0,
    "pl": 234.5, "pl_pct": 2.35, "today_pl": 41.2, "today_pl_pct": 0.4,
    "predicted_pl_pct": 0.8,                 // predicted change of equity over the horizon
    "predicted_band_pct": [-1.9, 3.1],       // 10th..90th percentile
    "predicted_horizon_h": 24
  },
  "win_rate": {"closed": 31, "wins": 19, "rate": 0.613},
  "equity_curve": [{"t": 1760400000, "equity": 10000.0}],
  "scanned": 287,              // markets looked at in the last cycle
  "markets": [                 // the ranked top (up to 40), best first
    {"symbol": "BTC-USD", "name": "Bitcoin", "asset_class": "crypto", "price": 67012.5,
     "change_pct": 1.2, "score": 0.81, "signal": "buy", "confidence": 0.72,
     "liquidity": 0.97, "spread_bps": 0.4, "depth_usd": 4200000.0, "flow": 0.31,
     "tradability": 0.93, "open": true, "sparkline": [66010.1, 66500.0]}
  ],
  "positions": [
    {"symbol": "ETH-USD", "asset_class": "crypto", "qty": 0.5, "avg_price": 2400.0, "price": 2460.0,
     "value": 1230.0, "pl": 30.0, "pl_pct": 2.5, "bot": "Trader Ava"}
  ],
  "trades": [                  // newest first, up to 50
    {"at": 1760400000, "symbol": "ETH-USD", "side": "buy", "qty": 0.5, "price": 2400.0, "value": 1200.0,
     "fee": 1.2, "bot": "Trader Ava", "reason": "Trend up, tight spread", "money": "practice"}
  ],
  "bots": [
    {"id": "bot-1", "name": "Scout", "role": "scout", "front": false, "status": "working",
     "doing": "Ranking 287 markets", "pot": 0.0, "pl_pct": 0.0, "trades": 0, "hired_at": 1760400000}
  ],
  "bots_running": 6,
  "thinking": [                // newest first, up to 60
    {"at": 1760400000, "bot": "Skeptic", "role": "skeptic", "level": "warn", "symbol": "DOGE-USD",
     "text": "Spread is 38 bp, three times normal. Halving the size."}
  ],
  "plan": {"next_cycle_at": 1760400060, "steps": ["Re-rank markets", "Check stops on 3 holdings"],
           "focus": ["BTC-USD", "NVDA"]},
  "predictions": [
    {"symbol": "BTC-USD", "horizon_h": 24, "expected_pct": 0.9, "low_pct": -2.1, "high_pct": 3.8,
     "confidence": 0.55, "made_at": 1760400000, "graded": false, "right": null}
  ],
  "prediction_record": {"graded": 40, "right": 24, "rate": 0.6},
  "research": [
    {"at": 1760400000, "symbol": "NVDA", "summary": "Earnings in 2 days; skeptic keeps size small.",
     "source": "local model"}
  ],
  "speed": {"last_cycle_ms": 812.0, "p50_ms": 640.0, "p95_ms": 1500.0, "decision_ms": 3.2,
            "grade": "fast", "words": "Decisions take 3 ms; a full 287-market scan 0.8 s.",
            "stages": {"fetch": 700.0, "rank": 40.0, "decide": 3.2, "orders": 1.1}},
  "learning": {"done": true, "studied": 24, "total": 24, "words": "Studied 24 markets.",
               "best": [{"strategy": "trend_sma", "title": "Trend (20/50)", "regime": "rising", "edge_pct": 3.1}]},
  "theme": {"accent": "#7c6cff", "mode": "dark", "sync": "none"},
  "updated_at": 1760400000
}
```

## Switching it on and off

| Route | Body | Does |
|---|---|---|
| `POST /api/control/start` | – | Turns the trader on. It studies first if it has not yet (learn-first). |
| `POST /api/control/stop` | `{"reason": "…"}` optional | Turns it off. Holdings stay; nothing new is bought. |
| `POST /api/control/cycle` | – | Runs one cycle now and returns `{"ok": true, "ms": 812.0}`. |
| `POST /api/control/flatten` | – | Sells everything the bots hold (practice account). |

Each returns the new dashboard `state` and `state_words`.

## Tuning

`GET /api/settings` → the settings object (see `ichos_trader/config.py` `default_settings`) plus
`"chosen"`: the values auto mode picked and a sentence of why for each:

```json
{"settings": {"auto": true, "risk": 0.5, "...": "..."},
 "chosen": {"risk": {"value": 0.42, "why": "Two losing days; leaning careful."}},
 "limits": {"risk": [0, 1], "max_positions": [1, 40], "pace_seconds": [10, 3600]}}
```

`PUT /api/settings` with any subset of settings. A number the owner sends is **pinned** (auto
leaves it alone) unless `"unpin": ["risk"]` is sent, which hands it back to auto mode.

## Speed test

`POST /api/speedtest` → runs a timed cycle on the current markets without placing orders:

```json
{"grade": "fast", "words": "…", "stages": {"fetch": 640.0, "rank": 35.0, "decide": 2.9},
 "decision_ms": 2.9, "cycle_ms": 690.0, "markets": 287,
 "targets": {"decision_ms": {"fast": 100, "ok": 500}, "cycle_ms": {"fast": 5000, "ok": 15000}}}
```

## Setup (the first screen)

`GET /api/setup` → `{"done": false, "broker": "sim", "start_cash": 10000, "currency": "USD", "budget": 0,
"alpaca": false, "currencies": [...], "workers": 16, "cpus": 4}`

`POST /api/setup` `{"amount": 2500, "currency": "EUR", "broker": "sim" | "alpaca", "start": true}` (owner) →
stops the trader, sets the money (the practice account's starting cash, or Alpaca's budget), marks
setup done, and starts again when `start` is true. 400 with a plain sentence when the amount is
missing or Alpaca's keys are not added yet.

## Practice account

`POST /api/paper/reset` `{"cash": 10000}` → empties the practice account and starts again.

## Connectors (brokers, data, models)

`GET /api/connectors`

```json
[{"id": "alpaca", "kind": "broker", "title": "Alpaca", "connected": false, "money": "practice",
  "recommended": true, "why": "Stocks and crypto in one free API, with a free practice account.",
  "fields": [{"key": "key_id", "label": "API key ID", "secret": false},
             {"key": "secret_key", "label": "Secret key", "secret": true}],
  "status": "Not connected", "masked": {}}]
```

`POST /api/connectors/{id}` with the field values (owner only) connects and tests it. Keys are
never sent back: `masked` shows the last 4 characters at most. `DELETE /api/connectors/{id}`
forgets the keys.

## Claude, only when asked

`POST /api/claude/ask` `{"question": "Why did it sell ETH?"}` (owner only) → `{"answer": "…",
"model": "…", "used_context": ["dashboard"]}`. Refused with a sentence when the Claude connector
is off or has no key. The trader never calls Claude by itself.
