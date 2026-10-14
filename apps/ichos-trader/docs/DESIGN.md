# Ichos Trader: how it is built

This is the trading desk from Nyx Ichos split into its own app, as Shagnik asked in the Fixer Upper
doc (pages 3–4). It imports nothing from the main app, so `apps/ichos-trader/` can move to its own
GitHub repo unchanged. The main repo's README links here: "this is where the trader went".

## What one cycle does

Every `pace_seconds` (a minute by default) the engine runs one cycle:

1. **Scout** asks the market hub for every market that is switched on (stocks, crypto, currencies)
   and snapshots up to `scan_limit` of them (300 by default) in parallel: price, bid/ask, a day of
   volume, candles and, where the feed has one, the order book.
2. **Ranking** scores each market on four things Shagnik named, plus the price signal:
   - **liquidity**: dollars traded in a day (log scale, so $1 B is not 1000× better than $1 M);
   - **spread**: bid-ask gap in basis points, from the feed when it gives bid/ask, otherwise
     estimated from daily highs and lows (Corwin–Schultz);
   - **depth**: dollars resting within 1% of the price in the order book (crypto), or estimated
     from volume where there is no free book (stocks);
   - **order flow**: buy pressure minus sell pressure, from the book's imbalance or, without a
     book, from where each bar closed inside its range, weighted by volume.
   These make a **tradability** score; the signal (trend, momentum, RSI) and the strategist's best
   strategy for this market's mood make the **opportunity** score. Rank = both together.
3. **Advisor** picks, for each top market, the strategy that has worked best in this kind of market
   (rising, falling, quiet, wild) according to what the strategist learned.
4. **Traders** (the front bots) each own a pot of money and a set of markets. They turn the best
   picks into orders: sized by the risk dial, capped per market, with a stop-loss and take-profit.
5. **Skeptic** (mild) reads every order before it goes. It **blocks** only when something is very
   likely to fail: a spread far wider than normal, almost no liquidity, a straight-up spike that
   looks like a pump, the price feed is stale, or every strategy disagrees. Otherwise it may
   **shrink** the order and says why. Its strictness is a dial.
6. **Risk** checks the hard rules nobody can switch off: only its own money and what it earned, no
   borrowing, no shorting, no single market above its share, and nothing at all with real money.
7. The **broker** fills the order (the built-in practice account by default: real prices, plus
   spread, slippage and fees, so practice does not flatter it).
8. **Manager** looks at the whole team every few cycles: moves money from the trader doing worst to
   the one doing best, **hires** a trader for a market class with good opportunities and nobody on
   it, **retires** a trader that keeps losing, and tells the watchdog when the team is losing.
9. **Strategist** (a background bot) keeps studying: it backtests every strategy on fresh history
   for the markets being watched and files the results by market mood. That is "learn first", and
   it never stops.
10. **Watchdog** times the cycle and checks the money. It **shuts the trader down by itself** when
    cycles are too slow several times in a row, when equity has fallen too far from its best, when
    it has run for a day and is still below where it started, or when prices go stale. The reason
    is shown at the top of the dashboard.

Every bot writes what it is thinking into a short feed the dashboard shows live.

## Learn first

With `learn_first` on (the default), the first time it is switched on the trader studies before it
trades: the strategist backtests every strategy on every market it plans to use, and the state is
"learning" until it has. It trades with practice money only.

## What "fast" means here

Speed in trading depends on who you are:

| Who | Speed | Can we do it? |
|---|---|---|
| High-frequency firms | microseconds, with servers inside the exchange | No, and not trying |
| Retail algorithmic trading over the internet | the exchange round trip alone is 50–300 ms | This is our league |
| A person clicking | seconds | Far slower than us |

So the trader judges itself on the part it controls:

- **Decision time** (snapshot in → order out, per market): **fast ≤ 100 ms, ok ≤ 500 ms**, slow
  above. Pure arithmetic, measured every cycle; typically a few milliseconds.
- **Full cycle** (fetch and rank every market, decide, place orders): **fast ≤ 5 s, ok ≤ 15 s**.
  Fetching dominates, so it is done in parallel and cached.
- **AI model calls** (a local model or Claude) take 1–30 s, so they are **never on the order
  path**. Research runs beside the loop and its conclusions are cached for the bots to read.

It trades on 1-minute to 1-hour bars, where 100 ms costs nothing measurable. Strategies that need
sub-second speed (arbitrage, market making) are not attempted, and the dashboard says so.

## Staying on

- The engine runs in a background thread with a supervisor: an error in one cycle is logged and
  the next cycle runs; a crash of the loop itself restarts it.
- `run_trader.py --forever` restarts the whole server if it ever exits.
- Settings, the practice account and what it learned are saved after every change in crash-safe
  files, and `running` is saved, so a restart carries on where it was.
- It does not have to run on Shagnik's PC: it is a small Python web app that a cloud machine can
  run, with Google or GitHub login so only he can control it.

## Privacy

- Keys come from environment variables or `data/secrets.json` (never in git, never sent back to
  the browser: masked to the last 4 characters).
- Logins: local (no login on 127.0.0.1), a passcode, or Google / GitHub. Only addresses in
  `ICHOS_OWNER_EMAILS` (or GitHub names in `ICHOS_OWNER_GITHUB`) are owners. Anyone else who signs
  in is a viewer: sees the setup, never the keys, cannot place orders or change settings.

## Folder map

```
apps/ichos-trader/
  run_trader.py            start it (add --forever to restart on exit)
  ichos_trader/
    config.py store.py models.py
    core/                  maths copied from the main app (indicators, strategies, forecast, clock)
    markets/               feeds: simulated, stocks, crypto, currencies; the hub; the universe
    ranking.py latency.py
    team/                  scout, strategist, advisor, traders, skeptic, manager, researcher
    paper.py risk.py settings.py watchdog.py engine.py
    access/                logins and saved keys
    connectors/            brokers, local and free cloud models, Claude (only when asked)
    server.py              the web API
  web/                     the dashboard (React + TypeScript + Vite)
  tests/                   pytest, all offline
  docs/                    this file, API.md, CONNECTORS.md, STATUS_CHECK.md
```
